from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from stormhelm.core.screen_awareness.models import (
    AdapterFallbackReason,
    AppAdapterId,
    AppAdapterResolution,
    AppSemanticContext,
    AppSemanticTarget,
    BrowserFormSemantic,
    BrowserSemanticContext,
    BrowserTabIdentity,
    CurrentScreenContext,
    ExplorerSemanticContext,
    GroundingCandidateRole,
    ScreenConfidence,
    ScreenConfidenceLevel,
    ScreenObservation,
    ScreenSourceType,
)


_BROWSER_PROCESSES = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi"}
_EDITOR_PROCESSES = {"code", "pycharm64", "pycharm", "sublime_text", "notepad++", "notepad"}
_TERMINAL_PROCESSES = {"windows terminal", "windowsterminal", "cmd", "powershell", "pwsh", "wt"}
_SETTINGS_PROCESSES = {"systemsettings", "settings"}
_EXPLORER_PROCESSES = {"explorer"}
_STALE_SEMANTIC_SECONDS = 180.0


def _clean_text(value: object) -> str | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    return text or None


def _confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    if bounded <= 0.0:
        level = ScreenConfidenceLevel.NONE
    elif bounded < 0.35:
        level = ScreenConfidenceLevel.LOW
    elif bounded < 0.7:
        level = ScreenConfidenceLevel.MEDIUM
    else:
        level = ScreenConfidenceLevel.HIGH
    return ScreenConfidence(score=bounded, level=level, note=note)


def _process_name(observation: ScreenObservation) -> str:
    return str(observation.focus_metadata.get("process_name") or observation.app_identity or "").strip().lower()


def _window_title(observation: ScreenObservation) -> str:
    return str(observation.focus_metadata.get("window_title") or "").strip()


def _freshness_seconds(payload: dict[str, Any]) -> float | None:
    raw = payload.get("freshness_seconds")
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _is_stale(payload: dict[str, Any]) -> bool:
    freshness = _freshness_seconds(payload)
    return freshness is not None and freshness > _STALE_SEMANTIC_SECONDS


def _role_from_label(role_hint: str | None, label: str, default: GroundingCandidateRole) -> GroundingCandidateRole:
    lowered = f"{str(role_hint or '').strip().lower()} {label.lower()}"
    if any(token in lowered for token in {"button", "cta"}):
        return GroundingCandidateRole.BUTTON
    if any(token in lowered for token in {"checkbox", "toggle"}):
        return GroundingCandidateRole.CHECKBOX
    if any(token in lowered for token in {"field", "input", "textbox"}):
        return GroundingCandidateRole.FIELD
    if "tab" in lowered:
        return GroundingCandidateRole.TAB
    if any(token in lowered for token in {"warning", "alert", "banner"}):
        return GroundingCandidateRole.WARNING
    if any(token in lowered for token in {"error", "failure"}):
        return GroundingCandidateRole.ERROR
    if any(token in lowered for token in {"dialog", "modal", "popup"}):
        return GroundingCandidateRole.POPUP
    if any(token in lowered for token in {"page", "document"}):
        return GroundingCandidateRole.DOCUMENT
    return default


def _semantic_target(
    *,
    candidate_id: str,
    label: str,
    role: GroundingCandidateRole,
    enabled: bool | None = None,
    parent_container: str | None = None,
    bounds: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AppSemanticTarget:
    return AppSemanticTarget(
        candidate_id=candidate_id,
        label=label,
        role=role,
        visible=True,
        enabled=enabled,
        parent_container=parent_container,
        bounds=dict(bounds or {}),
        source_type=ScreenSourceType.APP_ADAPTER,
        semantic_metadata=dict(metadata or {}),
    )


@dataclass(slots=True)
class SemanticAdapter:
    adapter_id: AppAdapterId

    def supports(self, *, observation: ScreenObservation, payload: dict[str, Any]) -> bool:
        raise NotImplementedError

    def resolve(self, *, observation: ScreenObservation, payload: dict[str, Any]) -> AppAdapterResolution:
        raise NotImplementedError


@dataclass(slots=True)
class BrowserSemanticAdapter(SemanticAdapter):
    adapter_id: AppAdapterId = AppAdapterId.BROWSER

    def supports(self, *, observation: ScreenObservation, payload: dict[str, Any]) -> bool:
        del payload
        return _process_name(observation) in _BROWSER_PROCESSES

    def resolve(self, *, observation: ScreenObservation, payload: dict[str, Any]) -> AppAdapterResolution:
        if not self.supports(observation=observation, payload=payload):
            return AppAdapterResolution(
                adapter_id=self.adapter_id,
                available=False,
                confidence=_confidence(0.0, "Browser semantics were offered on a non-browser surface."),
                freshness_seconds=_freshness_seconds(payload),
                fallback_reason=AdapterFallbackReason.CONFLICTING_SURFACE,
                provenance_note="Browser semantics conflicted with the current focused surface.",
            )
        if _is_stale(payload):
            return AppAdapterResolution(
                adapter_id=self.adapter_id,
                available=False,
                confidence=_confidence(0.18, "Browser semantics are stale."),
                freshness_seconds=_freshness_seconds(payload),
                fallback_reason=AdapterFallbackReason.STALE_SEMANTIC_STATE,
                provenance_note="Browser semantics were present but stale, so Stormhelm fell back to generic screen bearings.",
            )

        page = dict(payload.get("page") or {}) if isinstance(payload.get("page"), dict) else {}
        tab = dict(payload.get("tab") or {}) if isinstance(payload.get("tab"), dict) else {}
        page_title = _clean_text(page.get("title")) or _clean_text(tab.get("title")) or _clean_text(_window_title(observation))
        url = _clean_text(page.get("url")) or _clean_text(tab.get("url"))
        loading_state = _clean_text(payload.get("loading_state")) or "unknown"
        validation_messages = [_clean_text(item) for item in payload.get("validation_messages") or []]
        validation_messages = [item for item in validation_messages if item]

        semantic_targets: list[AppSemanticTarget] = []
        form_fields: list[BrowserFormSemantic] = []
        hidden_fields = 0
        for raw_field in payload.get("form_fields") or []:
            if not isinstance(raw_field, dict):
                continue
            label = _clean_text(raw_field.get("label")) or _clean_text(raw_field.get("name")) or _clean_text(raw_field.get("field_id"))
            field_id = _clean_text(raw_field.get("field_id")) or label
            if not label or not field_id:
                continue
            visible = bool(raw_field.get("visible", True))
            role = _role_from_label(str(raw_field.get("role") or raw_field.get("kind") or "field"), label, GroundingCandidateRole.FIELD)
            enabled = raw_field.get("enabled") if isinstance(raw_field.get("enabled"), bool) else None
            browser_field = BrowserFormSemantic(
                field_id=field_id,
                label=label,
                role=role,
                visible=visible,
                enabled=enabled,
                kind=_clean_text(raw_field.get("kind")),
                semantic_type=_clean_text(raw_field.get("semantic_type")),
                bounds=dict(raw_field.get("bounds") or {}) if isinstance(raw_field.get("bounds"), dict) else {},
                metadata={key: value for key, value in raw_field.items() if key not in {"field_id", "label", "role", "visible", "enabled", "kind", "semantic_type", "bounds"}},
            )
            form_fields.append(browser_field)
            if not visible:
                hidden_fields += 1
                continue
            semantic_targets.append(
                _semantic_target(
                    candidate_id=field_id,
                    label=label,
                    role=role,
                    enabled=enabled,
                    parent_container=_clean_text(raw_field.get("region")) or "browser_form",
                    bounds=dict(raw_field.get("bounds") or {}) if isinstance(raw_field.get("bounds"), dict) else {},
                    metadata={
                        "adapter_id": self.adapter_id.value,
                        "semantic_kind": "form_field",
                        "visible": True,
                        **browser_field.metadata,
                    },
                )
            )

        if page_title:
            semantic_targets.insert(
                0,
                _semantic_target(
                    candidate_id=f"browser-page::{page_title.lower().replace(' ', '-')}",
                    label=page_title,
                    role=GroundingCandidateRole.DOCUMENT,
                    parent_container="browser_page",
                    metadata={"adapter_id": self.adapter_id.value, "semantic_kind": "page", "url": url},
                ),
            )

        summary_parts: list[str] = []
        if page_title:
            summary_parts.append(f'Browser semantics identify the active page as "{page_title}"')
        if url:
            summary_parts.append(f"at {url}")
        if loading_state and loading_state not in {"complete", "interactive", "unknown"}:
            summary_parts.append(f"while the page still reports {loading_state}")
        if validation_messages:
            summary_parts.append(f'Validation cue: "{validation_messages[0]}"')
        summary = ". ".join(part.rstrip(".") for part in summary_parts if part).strip()
        if summary:
            summary += "."

        fallback_reason = None
        if hidden_fields and len(semantic_targets) <= 1:
            fallback_reason = AdapterFallbackReason.HIDDEN_ONLY_SEMANTIC_TARGETS

        semantic_context = AppSemanticContext(
            adapter_id=self.adapter_id,
            summary=summary or "Browser semantics are available but only partially populated.",
            page_title=page_title,
            url=url,
            loading_state=loading_state,
            tab_identity=BrowserTabIdentity(
                title=_clean_text(tab.get("title")) or page_title,
                index=int(tab["index"]) if isinstance(tab.get("index"), int) else None,
                active=bool(tab.get("active", True)),
                url=_clean_text(tab.get("url")) or url,
            ),
            browser=BrowserSemanticContext(
                page_title=page_title,
                url=url,
                tab_identity=BrowserTabIdentity(
                    title=_clean_text(tab.get("title")) or page_title,
                    index=int(tab["index"]) if isinstance(tab.get("index"), int) else None,
                    active=bool(tab.get("active", True)),
                    url=_clean_text(tab.get("url")) or url,
                ),
                loading_state=loading_state,
                validation_messages=list(validation_messages),
                form_fields=form_fields,
            ),
            metadata={"adapter_surface": "browser"},
        )
        return AppAdapterResolution(
            adapter_id=self.adapter_id,
            available=bool(page_title or url or semantic_targets),
            confidence=_confidence(0.86 if page_title or url else 0.62, "Browser DOM and tab semantics provided a fresh semantic bearing."),
            semantic_context=semantic_context,
            semantic_targets=semantic_targets,
            freshness_seconds=_freshness_seconds(payload),
            fallback_reason=fallback_reason,
            provenance_note="Browser semantics fused the focused browser surface with page, tab, and visible form metadata.",
            used_for_context=True,
        )


@dataclass(slots=True)
class FileExplorerSemanticAdapter(SemanticAdapter):
    adapter_id: AppAdapterId = AppAdapterId.FILE_EXPLORER

    def supports(self, *, observation: ScreenObservation, payload: dict[str, Any]) -> bool:
        del payload
        return _process_name(observation) in _EXPLORER_PROCESSES

    def resolve(self, *, observation: ScreenObservation, payload: dict[str, Any]) -> AppAdapterResolution:
        if not self.supports(observation=observation, payload=payload):
            return AppAdapterResolution(
                adapter_id=self.adapter_id,
                available=False,
                confidence=_confidence(0.0, "File Explorer semantics were offered on a non-Explorer surface."),
                freshness_seconds=_freshness_seconds(payload),
                fallback_reason=AdapterFallbackReason.CONFLICTING_SURFACE,
                provenance_note="File Explorer semantics conflicted with the current focused surface.",
            )
        if _is_stale(payload):
            return AppAdapterResolution(
                adapter_id=self.adapter_id,
                available=False,
                confidence=_confidence(0.18, "File Explorer semantics are stale."),
                freshness_seconds=_freshness_seconds(payload),
                fallback_reason=AdapterFallbackReason.STALE_SEMANTIC_STATE,
                provenance_note="File Explorer semantics were stale, so generic screen bearings remain authoritative.",
            )
        current_path = _clean_text(payload.get("current_path"))
        selected_item = dict(payload.get("selected_item") or {}) if isinstance(payload.get("selected_item"), dict) else {}
        selected_name = _clean_text(selected_item.get("name")) or _clean_text(selected_item.get("label"))
        selected_kind = _clean_text(selected_item.get("kind"))
        semantic_targets: list[AppSemanticTarget] = []
        if selected_name:
            semantic_targets.append(
                _semantic_target(
                    candidate_id=f"explorer-selection::{selected_name.lower()}",
                    label=selected_name,
                    role=GroundingCandidateRole.ITEM,
                    parent_container=current_path,
                    metadata={"adapter_id": self.adapter_id.value, "semantic_kind": "selected_item", "item_kind": selected_kind},
                )
            )
        summary_parts: list[str] = []
        if current_path:
            summary_parts.append(f'File Explorer is open to "{current_path}"')
        if selected_name:
            summary_parts.append(f'"{selected_name}" is selected')
        summary = ". ".join(part.rstrip(".") for part in summary_parts if part).strip()
        if summary:
            summary += "."
        return AppAdapterResolution(
            adapter_id=self.adapter_id,
            available=bool(current_path or selected_name),
            confidence=_confidence(0.84 if selected_name else 0.72 if current_path else 0.24, "File Explorer semantics exposed the current folder and selection."),
            semantic_context=AppSemanticContext(
                adapter_id=self.adapter_id,
                summary=summary or "File Explorer semantics are only partially available.",
                current_path=current_path,
                selected_item_label=selected_name,
                selected_item_kind=selected_kind,
                explorer=ExplorerSemanticContext(
                    current_path=current_path,
                    selected_item_name=selected_name,
                    selected_item_kind=selected_kind,
                ),
                metadata={"adapter_surface": "file_explorer"},
            ),
            semantic_targets=semantic_targets,
            freshness_seconds=_freshness_seconds(payload),
            provenance_note="File Explorer semantics exposed the current folder and selected item.",
            used_for_context=True,
        )


@dataclass(slots=True)
class LightweightSemanticAdapter(SemanticAdapter):
    process_names: tuple[str, ...] = ()
    surface_label: str = ""

    def supports(self, *, observation: ScreenObservation, payload: dict[str, Any]) -> bool:
        del payload
        return _process_name(observation) in set(self.process_names)

    def resolve(self, *, observation: ScreenObservation, payload: dict[str, Any]) -> AppAdapterResolution:
        if not self.supports(observation=observation, payload=payload):
            return AppAdapterResolution(
                adapter_id=self.adapter_id,
                available=False,
                confidence=_confidence(0.0, f"{self.surface_label} semantics conflicted with the current focused surface."),
                freshness_seconds=_freshness_seconds(payload),
                fallback_reason=AdapterFallbackReason.CONFLICTING_SURFACE,
                provenance_note=f"{self.surface_label} semantics conflicted with the current focused surface.",
            )
        if _is_stale(payload):
            return AppAdapterResolution(
                adapter_id=self.adapter_id,
                available=False,
                confidence=_confidence(0.18, f"{self.surface_label} semantics are stale."),
                freshness_seconds=_freshness_seconds(payload),
                fallback_reason=AdapterFallbackReason.STALE_SEMANTIC_STATE,
                provenance_note=f"{self.surface_label} semantics were stale, so generic screen bearings remain authoritative.",
            )
        section = _clean_text(payload.get("section")) or _clean_text(payload.get("page_title")) or _clean_text(_window_title(observation))
        summary = f'{self.surface_label} semantics identify the current section as "{section}".' if section else f"{self.surface_label} semantics are only partially available."
        semantic_targets = [
            _semantic_target(
                candidate_id=f"{self.adapter_id.value}::{section.lower().replace(' ', '-')}",
                label=section,
                role=GroundingCandidateRole.DOCUMENT,
                parent_container=self.adapter_id.value,
                metadata={"adapter_id": self.adapter_id.value, "semantic_kind": "section"},
            )
        ] if section else []
        return AppAdapterResolution(
            adapter_id=self.adapter_id,
            available=bool(section),
            confidence=_confidence(0.68 if section else 0.2, f"{self.surface_label} semantics supplied a narrow section-level bearing."),
            semantic_context=AppSemanticContext(
                adapter_id=self.adapter_id,
                summary=summary,
                page_title=section,
                metadata={"adapter_surface": self.surface_label.lower().replace(" ", "_")},
            ),
            semantic_targets=semantic_targets,
            freshness_seconds=_freshness_seconds(payload),
            provenance_note=f"{self.surface_label} semantics supplied a narrow section-level bearing.",
            used_for_context=True,
        )


class SemanticAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[SemanticAdapter] = [
            BrowserSemanticAdapter(),
            FileExplorerSemanticAdapter(),
            LightweightSemanticAdapter(adapter_id=AppAdapterId.SYSTEM_SETTINGS, process_names=tuple(_SETTINGS_PROCESSES), surface_label="System Settings"),
            LightweightSemanticAdapter(adapter_id=AppAdapterId.TERMINAL, process_names=tuple(_TERMINAL_PROCESSES), surface_label="Terminal"),
            LightweightSemanticAdapter(adapter_id=AppAdapterId.EDITOR, process_names=tuple(_EDITOR_PROCESSES), surface_label="Editor"),
        ]

    def supported_adapter_ids(self) -> list[str]:
        return [adapter.adapter_id.value for adapter in self._adapters]

    def resolve(
        self,
        *,
        observation: ScreenObservation,
        active_context: dict[str, Any],
    ) -> AppAdapterResolution | None:
        adapter_semantics = active_context.get("adapter_semantics")
        if not isinstance(adapter_semantics, dict):
            process = _process_name(observation)
            if process in _BROWSER_PROCESSES:
                return AppAdapterResolution(
                    adapter_id=AppAdapterId.BROWSER,
                    available=False,
                    confidence=_confidence(0.0, "No browser semantic payload was available."),
                    fallback_reason=AdapterFallbackReason.NO_SEMANTIC_STATE,
                    provenance_note="Browser semantics were unavailable, so Stormhelm used generic screen bearings.",
                )
            return None

        for adapter in self._adapters:
            payload = adapter_semantics.get(adapter.adapter_id.value)
            if isinstance(payload, dict):
                return adapter.resolve(observation=observation, payload=payload)

        process = _process_name(observation)
        inferred_adapter = self._inferred_adapter_id(process)
        if inferred_adapter is None:
            return None
        return AppAdapterResolution(
            adapter_id=inferred_adapter,
            available=False,
            confidence=_confidence(0.0, "The current app surface has no semantic adapter payload."),
            fallback_reason=AdapterFallbackReason.NO_SEMANTIC_STATE,
            provenance_note="No adapter semantic payload was available, so Stormhelm used generic screen bearings.",
        )

    def enrich_context(
        self,
        *,
        current_context: CurrentScreenContext,
        resolution: AppAdapterResolution | None,
    ) -> CurrentScreenContext:
        if resolution is None:
            return current_context
        current_context.adapter_resolution = resolution
        current_context.semantic_targets = list(resolution.semantic_targets)
        if not resolution.available or resolution.semantic_context is None:
            return current_context
        semantic_context = resolution.semantic_context
        if semantic_context.summary:
            base_summary = str(current_context.summary or "").strip()
            if base_summary and semantic_context.summary not in base_summary:
                current_context.summary = f"{base_summary.rstrip('.')} {semantic_context.summary}"
            else:
                current_context.summary = semantic_context.summary
        current_context.active_environment = resolution.adapter_id.value
        if semantic_context.loading_state and semantic_context.loading_state not in {"complete", "interactive", "unknown"}:
            current_context.visible_task_state = semantic_context.loading_state
        if semantic_context.browser is not None and semantic_context.browser.validation_messages:
            for message in semantic_context.browser.validation_messages:
                if message not in current_context.blockers_or_prompts:
                    current_context.blockers_or_prompts.append(message)
        if semantic_context.selected_item_label and semantic_context.selected_item_label not in current_context.candidate_next_steps:
            current_context.candidate_next_steps.append(semantic_context.selected_item_label)
        return current_context

    def _inferred_adapter_id(self, process_name: str) -> AppAdapterId | None:
        lowered = str(process_name or "").strip().lower()
        if lowered in _BROWSER_PROCESSES:
            return AppAdapterId.BROWSER
        if lowered in _EXPLORER_PROCESSES:
            return AppAdapterId.FILE_EXPLORER
        if lowered in _SETTINGS_PROCESSES:
            return AppAdapterId.SYSTEM_SETTINGS
        if lowered in _TERMINAL_PROCESSES:
            return AppAdapterId.TERMINAL
        if lowered in _EDITOR_PROCESSES:
            return AppAdapterId.EDITOR
        return None
