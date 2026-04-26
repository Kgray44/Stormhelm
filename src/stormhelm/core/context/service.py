from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from stormhelm.core.context.models import ActiveWorkContext, ContextEntity
from stormhelm.core.orchestrator.session_state import ConversationStateStore


_CODE_MARKERS = ("def ", "class ", "import ", "return ", "{", "};", "=>", "const ", "let ", "#include")


class ActiveContextService:
    def __init__(self, session_state: ConversationStateStore) -> None:
        self.session_state = session_state

    def classify_clipboard(self, raw_value: object) -> dict[str, Any]:
        return self._classify_payload(raw_value)

    def classify_selection(self, raw_value: object) -> dict[str, Any]:
        return self._classify_payload(raw_value)

    def update_from_turn(
        self,
        *,
        session_id: str,
        workspace_context: dict[str, Any] | None,
        active_posture: dict[str, Any] | None,
        active_request_state: dict[str, Any] | None,
        recent_tool_results: list[dict[str, Any]] | None,
        input_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        existing = self.snapshot(session_id)
        workspace_context = workspace_context or {}
        active_posture = active_posture or {}
        active_request_state = active_request_state or {}
        input_context = input_context or {}
        opened_items = workspace_context.get("opened_items") if isinstance(workspace_context.get("opened_items"), list) else []
        active_item = workspace_context.get("active_item") if isinstance(workspace_context.get("active_item"), dict) else {}
        input_recent_entities = self._input_recent_entities(input_context)
        recent_entities = self._recent_entities(
            active_item=active_item,
            opened_items=opened_items,
            fallback=[*input_recent_entities, *list(existing.get("recent_entities", []) or [])],
        )
        context = ActiveWorkContext(
            active_goal=str(active_posture.get("active_goal") or existing.get("active_goal") or "").strip(),
            workspace=dict(workspace_context.get("workspace") or existing.get("workspace") or {}),
            selection=self._normalize_input_descriptor(input_context.get("selection")) or dict(existing.get("selection") or {}),
            clipboard=self._normalize_input_descriptor(input_context.get("clipboard")) or dict(existing.get("clipboard") or {}),
            recent_entities=recent_entities,
            last_action=str(active_posture.get("last_completed_action") or existing.get("last_action") or "").strip(),
            current_problem_domain=str(active_request_state.get("family") or existing.get("current_problem_domain") or "").strip(),
            pending_next_steps=[str(item).strip() for item in active_posture.get("pending_next_steps", []) if str(item).strip()]
            or [str(item).strip() for item in existing.get("pending_next_steps", []) if str(item).strip()],
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        payload = context.to_dict()
        recent_resolutions = self._input_recent_context_resolutions(input_context)
        if not recent_resolutions:
            recent_resolutions = self.session_state.get_recent_context_resolutions(session_id)
        if recent_resolutions:
            payload["recent_context_resolutions"] = recent_resolutions[:4]
        self.session_state.set_active_context(session_id, payload)
        return payload

    def snapshot(self, session_id: str) -> dict[str, Any]:
        return self.session_state.get_active_context(session_id)

    def remember_resolution(self, session_id: str, resolution: dict[str, Any]) -> None:
        if not isinstance(resolution, dict) or not resolution:
            return
        self.session_state.remember_context_resolution(session_id, resolution)

    def _input_recent_context_resolutions(self, input_context: dict[str, Any]) -> list[dict[str, Any]]:
        supplied = input_context.get("recent_context_resolutions")
        if not isinstance(supplied, list):
            return []
        compact: list[dict[str, Any]] = []
        for item in supplied:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip()
            if not kind:
                continue
            payload = {
                key: value
                for key, value in item.items()
                if key in {"kind", "result", "trace", "source", "freshness", "label"}
            }
            compact.append(payload)
            if len(compact) >= 4:
                break
        return compact

    def _input_recent_entities(self, input_context: dict[str, Any]) -> list[dict[str, Any]]:
        supplied = input_context.get("recent_entities")
        if not isinstance(supplied, list):
            return []
        entities: list[dict[str, Any]] = []
        for item in supplied:
            if not isinstance(item, dict):
                continue
            entity = self._entity_from_item(item)
            if entity is None:
                continue
            payload = entity.to_dict()
            if payload not in entities:
                entities.append(payload)
            if len(entities) >= 8:
                break
        return entities

    def _recent_entities(
        self,
        *,
        active_item: dict[str, Any],
        opened_items: list[dict[str, Any]],
        fallback: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        if active_item:
            entity = self._entity_from_item(active_item)
            if entity:
                entities.append(entity.to_dict())
        for item in opened_items:
            entity = self._entity_from_item(item)
            if entity is None:
                continue
            payload = entity.to_dict()
            if payload not in entities:
                entities.append(payload)
        for item in fallback:
            if isinstance(item, dict) and item not in entities:
                entities.append(dict(item))
        return entities[:8]

    def _entity_from_item(self, item: dict[str, Any]) -> ContextEntity | None:
        title = str(item.get("title") or item.get("name") or "").strip()
        path = str(item.get("path") or "").strip() or None
        url = str(item.get("url") or "").strip() or None
        kind = str(item.get("kind") or item.get("viewer") or "").strip()
        item_id = str(item.get("itemId") or "").strip() or None
        if not any((title, path, url)):
            return None
        return ContextEntity(title=title or Path(path or url or "").name, kind=kind, path=path, url=url, item_id=item_id)

    def _normalize_input_descriptor(self, descriptor: object) -> dict[str, Any]:
        if isinstance(descriptor, dict):
            kind = str(descriptor.get("kind") or "").strip()
            value = descriptor.get("value")
            preview = str(descriptor.get("preview") or "").strip()
            normalized = {
                "kind": kind,
                "value": value,
                "preview": preview or self._preview_value(value),
            }
            if kind:
                return normalized
            return self._classify_payload(value)
        return self._classify_payload(descriptor)

    def _classify_payload(self, raw_value: object) -> dict[str, Any]:
        if raw_value is None:
            return {}
        text = str(raw_value).strip()
        if not text:
            return {}
        parsed = urlparse(text)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return {"kind": "url", "value": text, "preview": text}
        if self._looks_like_multi_path(text):
            paths = [line.strip() for line in text.splitlines() if line.strip()]
            return {"kind": "paths", "value": paths, "preview": paths[0]}
        if self._looks_like_path(text):
            return {"kind": "file_path", "value": text, "preview": text}
        if any(marker in text for marker in _CODE_MARKERS) or re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(", text):
            return {"kind": "code", "value": text, "preview": self._preview_value(text)}
        return {"kind": "text", "value": text, "preview": self._preview_value(text)}

    def _preview_value(self, value: object) -> str:
        text = " ".join(str(value or "").split()).strip()
        if len(text) <= 120:
            return text
        return text[:117].rstrip() + "..."

    def _looks_like_path(self, text: str) -> bool:
        candidate = text.strip().strip('"')
        return bool(re.match(r"^[a-zA-Z]:[\\/]", candidate) or candidate.startswith("\\\\"))

    def _looks_like_multi_path(self, text: str) -> bool:
        lines = [line.strip().strip('"') for line in text.splitlines() if line.strip()]
        return len(lines) >= 2 and all(self._looks_like_path(line) for line in lines)
