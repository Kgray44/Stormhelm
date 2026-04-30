from __future__ import annotations

from dataclasses import dataclass
import re
from statistics import mean
from typing import Any
from uuid import uuid4

from stormhelm.core.screen_awareness.models import CurrentScreenContext
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import ScreenInterpretation
from stormhelm.core.screen_awareness.models import ScreenObservation
from stormhelm.core.screen_awareness.models import confidence_level_for_score
from stormhelm.core.screen_awareness.observation import best_live_visible_text
from stormhelm.core.screen_awareness.observation import best_visible_text
from stormhelm.core.screen_awareness.observation import has_live_screen_signal


_BROWSER_PROCESSES = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi"}
_EDITOR_PROCESSES = {"code", "pycharm64", "pycharm", "sublime_text", "notepad++", "notepad"}
_MATH_PATTERN = re.compile(r"^[0-9\.\+\-\*\/\(\)\s%]+$")


def _preview(text: str | None, *, limit: int = 120) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _screen_confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


def _window_title(observation: ScreenObservation) -> str:
    return str(observation.focus_metadata.get("window_title") or "").strip()


def _process_name(observation: ScreenObservation) -> str:
    return str(observation.focus_metadata.get("process_name") or observation.app_identity or "").strip().lower()


def _active_item(observation: ScreenObservation) -> dict[str, Any]:
    active_item = observation.workspace_snapshot.get("active_item")
    return dict(active_item) if isinstance(active_item, dict) else {}


def _likely_environment(observation: ScreenObservation) -> str | None:
    process_name = _process_name(observation)
    active_item = _active_item(observation)
    active_url = str(active_item.get("url") or "").strip().lower()
    title = _window_title(observation).lower()
    if process_name in _BROWSER_PROCESSES or active_url.startswith(("http://", "https://")):
        return "browser"
    if process_name in _EDITOR_PROCESSES or observation.selection_metadata.get("kind") == "code":
        return "editor"
    if "settings" in process_name or "settings" in title:
        return "system_settings"
    if process_name:
        return "desktop_app"
    if active_item:
        return "workspace_surface"
    return None


def _visible_purpose(observation: ScreenObservation, visible_text: str | None) -> str | None:
    active_item = _active_item(observation)
    url = str(active_item.get("url") or "").strip().lower()
    title = _window_title(observation).lower()
    if visible_text and _extract_visible_errors(visible_text):
        return "error_or_warning"
    if visible_text and _looks_like_math_expression(visible_text):
        return "math_expression"
    if any(marker in url for marker in {"/docs", "docs.", "readthedocs", "documentation"}) or "docs" in title:
        return "documentation"
    if "settings" in title:
        return "settings"
    if active_item or observation.focus_metadata:
        return "application_surface"
    return None


def _extract_visible_errors(text: str | None) -> list[str]:
    candidate = str(text or "").strip()
    if not candidate:
        return []
    errors: list[str] = []
    patterns = (
        r"\b[A-Z][A-Za-z]+Error\b[^\n]*",
        r"\bTraceback\b[^\n]*",
        r"\bwarning\b[^\n]*",
        r"\bfailed\b[^\n]*",
        r"\bexception\b[^\n]*",
    )
    for pattern in patterns:
        errors.extend(match.group(0).strip() for match in re.finditer(pattern, candidate, flags=re.IGNORECASE))
    if not errors and any(token in candidate.lower() for token in {"error", "warning", "failed", "exception"}):
        errors.append(_preview(candidate))
    deduped: list[str] = []
    for entry in errors:
        if entry not in deduped:
            deduped.append(entry)
    return deduped[:3]


def _looks_like_math_expression(text: str | None) -> bool:
    candidate = str(text or "").strip()
    return bool(candidate and len(candidate) <= 64 and _MATH_PATTERN.fullmatch(candidate))


def _candidate_next_actions(visible_errors: list[str], environment: str | None, visible_purpose: str | None) -> list[str]:
    if visible_errors:
        first = visible_errors[0].lower()
        if "nameerror" in first:
            return ["Check where the missing name should be defined or imported before it is used."]
        return ["Inspect the exact visible error line or full message before taking corrective action."]
    if visible_purpose == "documentation":
        return ["Stay on the current reference and focus on the selected section if you want a deeper explanation."]
    if environment == "editor":
        return ["Select the exact line or block you want explained for a stronger grounded answer."]
    return ["Share or select the most relevant visible text if you want a tighter grounded bearing."]


def _likely_task(environment: str | None, visible_purpose: str | None, visible_errors: list[str], visible_text: str | None) -> str | None:
    if visible_errors:
        return "debugging a visible error"
    if visible_purpose == "math_expression":
        return "solving a visible math expression"
    if visible_purpose == "documentation":
        return "reading documentation"
    if environment == "editor":
        return "reviewing code"
    if visible_text:
        return "inspecting current screen content"
    return None


def _visible_entities(observation: ScreenObservation, environment: str | None) -> list[str]:
    entities: list[str] = []
    title = _window_title(observation)
    active_item = _active_item(observation)
    if title:
        entities.append(title)
    if active_item.get("title"):
        entities.append(str(active_item["title"]))
    if active_item.get("url"):
        entities.append(str(active_item["url"]))
    if environment:
        entities.append(environment)
    deduped: list[str] = []
    for item in entities:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[:4]


def _visible_messages(observation: ScreenObservation, visible_text: str | None) -> list[str]:
    messages: list[str] = []
    if visible_text:
        messages.append(_preview(visible_text))
    title = _window_title(observation)
    if title and title not in messages:
        messages.append(title)
    return messages[:3]


@dataclass(slots=True)
class DeterministicScreenInterpreter:
    def interpret(
        self,
        observation: ScreenObservation,
        *,
        operator_text: str,
    ) -> ScreenInterpretation:
        del operator_text
        live_visible_text = best_live_visible_text(observation)
        visible_text = best_visible_text(observation)
        environment = _likely_environment(observation)
        visible_purpose = _visible_purpose(observation, visible_text)
        visible_errors = _extract_visible_errors(visible_text)

        environment_score = 0.9 if observation.focus_metadata else 0.6 if observation.workspace_snapshot else 0.0
        content_score = (
            0.95
            if observation.selected_text
            else 0.88
            if observation.visual_text
            else 0.78
            if live_visible_text
            else 0.32
            if observation.clipboard_text
            else 0.0
        )
        interpretation_score = 0.9 if visible_errors or _looks_like_math_expression(visible_text) else 0.7 if visible_purpose else 0.4 if environment else 0.0

        uncertainty_notes: list[str] = []
        if not observation.selected_text and not observation.visual_text and not observation.clipboard_text:
            uncertainty_notes.append("Only partial native context was available; no direct selected text was present.")
        if observation.clipboard_text and not has_live_screen_signal(observation):
            uncertainty_notes.append("Only clipboard text was available, and it may not match the live current screen.")
        screen_capture = observation.visual_metadata.get("screen_capture") if isinstance(observation.visual_metadata, dict) else None
        if isinstance(screen_capture, dict) and screen_capture.get("captured") and not observation.visual_text:
            uncertainty_notes.append("A screenshot was captured, but no local OCR or provider vision text was available.")
        if visible_text is None:
            uncertainty_notes.append("The visible content signal was incomplete.")

        findings: list[str] = []
        if visible_errors:
            findings.extend(visible_errors)
        elif visible_text:
            findings.append(_preview(visible_text))
        elif _window_title(observation):
            findings.append(_window_title(observation))

        return ScreenInterpretation(
            likely_environment=environment,
            visible_purpose=visible_purpose,
            visible_messages=_visible_messages(observation, visible_text),
            visible_entities=_visible_entities(observation, environment),
            visible_errors=visible_errors,
            blockers=list(visible_errors),
            candidate_next_actions=_candidate_next_actions(visible_errors, environment, visible_purpose),
            likely_task=_likely_task(environment, visible_purpose, visible_errors, visible_text),
            question_relevant_findings=findings[:3],
            confidence_by_facet={
                "environment": _screen_confidence(environment_score, "Environment confidence comes from focused window and workspace context."),
                "content": _screen_confidence(content_score, "Content confidence depends on how much direct visible text was available."),
                "interpretation": _screen_confidence(interpretation_score, "Interpretation confidence reflects how specific the visible pattern was."),
            },
            uncertainty_notes=uncertainty_notes,
        )


@dataclass(slots=True)
class DeterministicContextSynthesizer:
    def synthesize(
        self,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
    ) -> CurrentScreenContext:
        scores = [confidence.score for confidence in interpretation.confidence_by_facet.values()]
        overall = mean(scores) if scores else 0.0
        process_label = str(observation.focus_metadata.get("process_name") or observation.app_identity or "").strip()
        title = _window_title(observation)
        live_visible_text = best_live_visible_text(observation)
        summary_parts: list[str] = []
        if process_label:
            summary_parts.append(f"{process_label.title()} is focused")
        if title:
            if summary_parts:
                summary_parts[-1] = f"{summary_parts[-1]} on \"{title}\""
            else:
                summary_parts.append(f"The current window appears to be \"{title}\"")
        if observation.selected_text:
            summary_parts.append(f"Selected text reads: {_preview(observation.selected_text)}")
        elif observation.visual_text:
            summary_parts.append(f"Visible text reads: {_preview(observation.visual_text)}")
        elif live_visible_text:
            summary_parts.append(f"Visible cue: {_preview(live_visible_text)}")
        elif observation.clipboard_text:
            summary_parts.append(f"Clipboard hint available: {_preview(observation.clipboard_text)}")
        elif interpretation.question_relevant_findings:
            summary_parts.append(f"Visible cue: {interpretation.question_relevant_findings[0]}")
        summary = ". ".join(part.rstrip(".") for part in summary_parts if part).strip()
        if summary:
            summary += "."

        sensitivity_markers: list[str] = []
        if observation.sensitivity.value not in {"unknown", "normal"}:
            sensitivity_markers.append(observation.sensitivity.value)

        return CurrentScreenContext(
            context_id=f"screen-phase1-{uuid4().hex}",
            active_environment=interpretation.likely_environment,
            summary=summary or "The current screen context is only partially available.",
            visible_task_state=interpretation.likely_task or interpretation.visible_purpose,
            blockers_or_prompts=list(interpretation.blockers),
            candidate_next_steps=list(interpretation.candidate_next_actions),
            confidence=_screen_confidence(overall, "Overall screen confidence blends environment, content, and interpretation confidence."),
            sensitivity_markers=sensitivity_markers,
            ephemeral_context_id=f"screen-phase1-{uuid4().hex}",
        )
