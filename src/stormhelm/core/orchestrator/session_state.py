from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stormhelm.core.intelligence.language import fuzzy_ratio, normalize_lookup_phrase, normalize_phrase
from stormhelm.core.memory import SemanticMemoryRepository, SemanticMemoryService
from stormhelm.core.memory.models import MemorySourceClass
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.shared.time import utc_now_iso


class _NullSemanticMemoryService:
    def list_recent_session_tool_results(
        self,
        session_id: str,
        *,
        max_age_seconds: float | None = None,
    ) -> list[dict[str, object]]:
        return []

    def remember_session_tool_result(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_family: str,
        arguments: dict[str, object],
        result: dict[str, object],
        captured_at: str | None,
    ) -> None:
        return None

    def list_recent_context_resolutions(self, session_id: str) -> list[dict[str, object]]:
        return []

    def remember_context_resolution(self, session_id: str, resolution: dict[str, object]) -> None:
        return None

    def list_aliases(self, category: str) -> dict[str, dict[str, object]]:
        return {}

    def remember_alias(self, category: str, alias: str, *, target: dict[str, object]) -> None:
        return None

    def resolve_alias(self, category: str, phrase: str, *, threshold: float = 0.84) -> dict[str, object] | None:
        return None

    def get_learned_preferences(self) -> dict[str, dict[str, object]]:
        return {}

    def remember_preference(
        self,
        scope: str,
        key: str,
        value: object,
        *,
        source_class: str,
    ) -> None:
        return None

    def preference_value(self, scope: str, key: str, *, minimum_count: int = 1) -> object | None:
        return None


class ConversationStateStore:
    def __init__(
        self,
        preferences: PreferencesRepository,
        memory: SemanticMemoryService | None = None,
    ) -> None:
        self.preferences = preferences
        if memory is not None:
            self.memory = memory
            return
        database = getattr(preferences, "database", None)
        if database is not None:
            self.memory = SemanticMemoryService(SemanticMemoryRepository(database))
            return
        self.memory = _NullSemanticMemoryService()

    def get_previous_response_id(self, session_id: str, *, role: str = "planner") -> str | None:
        state = self.preferences.get_all()
        key = self._key(session_id, role)
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value
        return None

    def set_previous_response_id(self, session_id: str, response_id: str | None, *, role: str = "planner") -> None:
        self.preferences.set_preference(self._key(session_id, role), response_id or "")

    def clear_previous_response_id(self, session_id: str, *, role: str = "planner") -> None:
        self.preferences.set_preference(self._key(session_id, role), "")

    def get_active_workspace_id(self, session_id: str) -> str | None:
        state = self.preferences.get_all()
        value = state.get(self._workspace_key(session_id))
        if isinstance(value, str) and value.strip():
            return value
        return None

    def set_active_workspace_id(self, session_id: str, workspace_id: str | None) -> None:
        self.preferences.set_preference(self._workspace_key(session_id), workspace_id or "")

    def get_active_task_id(self, session_id: str) -> str | None:
        state = self.preferences.get_all()
        value = state.get(self._task_key(session_id))
        if isinstance(value, str) and value.strip():
            return value
        return None

    def set_active_task_id(self, session_id: str, task_id: str | None) -> None:
        self.preferences.set_preference(self._task_key(session_id), task_id or "")

    def clear_active_task_id(self, session_id: str) -> None:
        self.preferences.set_preference(self._task_key(session_id), "")

    def get_active_posture(self, session_id: str) -> dict[str, object]:
        state = self.preferences.get_all()
        value = state.get(self._posture_key(session_id))
        if isinstance(value, dict):
            return dict(value)
        return {}

    def set_active_posture(self, session_id: str, posture: dict[str, object] | None) -> None:
        self.preferences.set_preference(self._posture_key(session_id), posture or {})

    def clear_active_posture(self, session_id: str) -> None:
        self.preferences.set_preference(self._posture_key(session_id), {})

    def get_active_request_state(self, session_id: str) -> dict[str, object]:
        state = self.preferences.get_all()
        value = state.get(self._request_state_key(session_id))
        if isinstance(value, dict):
            return dict(value)
        return {}

    def set_active_request_state(self, session_id: str, request_state: dict[str, object] | None) -> None:
        self.preferences.set_preference(self._request_state_key(session_id), request_state or {})

    def clear_active_request_state(self, session_id: str) -> None:
        self.preferences.set_preference(self._request_state_key(session_id), {})

    def get_recent_tool_results(
        self,
        session_id: str,
        *,
        max_age_seconds: float | None = None,
    ) -> list[dict[str, object]]:
        memory_results = self.memory.list_recent_session_tool_results(
            session_id,
            max_age_seconds=max_age_seconds,
        )
        if memory_results:
            return memory_results
        state = self.preferences.get_all()
        value = state.get(self._recent_tool_results_key(session_id))
        if not isinstance(value, list):
            return []
        results = [dict(item) for item in value if isinstance(item, dict)]
        if max_age_seconds is None:
            return results
        threshold = datetime.now(timezone.utc).timestamp() - max_age_seconds
        filtered: list[dict[str, object]] = []
        for item in results:
            captured_at = item.get("captured_at")
            if not isinstance(captured_at, str):
                continue
            try:
                captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if captured >= threshold:
                filtered.append(item)
        return filtered

    def remember_tool_result(
        self,
        session_id: str,
        *,
        tool_name: str,
        arguments: dict[str, object],
        result: dict[str, object] | None,
        captured_at: str | None,
    ) -> None:
        self.memory.remember_session_tool_result(
            session_id=session_id,
            tool_name=tool_name,
            tool_family=self._tool_family(tool_name),
            arguments=dict(arguments),
            result=dict(result) if isinstance(result, dict) else {},
            captured_at=captured_at,
        )
        entry = {
            "tool_name": tool_name,
            "family": self._tool_family(tool_name),
            "arguments": dict(arguments),
            "result": dict(result) if isinstance(result, dict) else {},
            "captured_at": captured_at or utc_now_iso(),
        }
        state = self.preferences.get_all()
        existing = state.get(self._recent_tool_results_key(session_id))
        results = [dict(item) for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
        self.preferences.set_preference(self._recent_tool_results_key(session_id), [entry, *results][:12])

    def get_active_context(self, session_id: str) -> dict[str, object]:
        state = self.preferences.get_all()
        value = state.get(self._active_context_key(session_id))
        if isinstance(value, dict):
            return dict(value)
        return {}

    def set_active_context(self, session_id: str, context: dict[str, object] | None) -> None:
        self.preferences.set_preference(self._active_context_key(session_id), context or {})

    def get_recent_context_resolutions(self, session_id: str) -> list[dict[str, object]]:
        memory_results = self.memory.list_recent_context_resolutions(session_id)
        if memory_results:
            return memory_results
        state = self.preferences.get_all()
        value = state.get(self._recent_context_resolutions_key(session_id))
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    def remember_context_resolution(self, session_id: str, resolution: dict[str, object]) -> None:
        self.memory.remember_context_resolution(session_id, dict(resolution))
        entry = dict(resolution)
        entry.setdefault("captured_at", utc_now_iso())
        state = self.preferences.get_all()
        existing = state.get(self._recent_context_resolutions_key(session_id))
        resolutions = [dict(item) for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
        self.preferences.set_preference(self._recent_context_resolutions_key(session_id), [entry, *resolutions][:8])

    def get_suggestion_state(self, session_id: str) -> dict[str, object]:
        state = self.preferences.get_all()
        value = state.get(self._suggestion_state_key(session_id))
        if isinstance(value, dict):
            return dict(value)
        return {}

    def set_suggestion_state(self, session_id: str, suggestion_state: dict[str, object] | None) -> None:
        self.preferences.set_preference(self._suggestion_state_key(session_id), suggestion_state or {})

    def clear_suggestion_state(self, session_id: str) -> None:
        self.preferences.set_preference(self._suggestion_state_key(session_id), {})

    def get_aliases(self, category: str) -> dict[str, dict[str, object]]:
        aliases = self.memory.list_aliases(category)
        if aliases:
            return aliases
        state = self.preferences.get_all()
        value = state.get(self._alias_memory_key())
        if not isinstance(value, dict):
            return {}
        category_value = value.get(category)
        if not isinstance(category_value, dict):
            return {}
        return {str(key): dict(item) for key, item in category_value.items() if isinstance(item, dict)}

    def remember_alias(self, category: str, alias: str, *, target: dict[str, object]) -> None:
        normalized = normalize_lookup_phrase(alias) or normalize_phrase(alias)
        if not self._alias_allowed(normalized):
            return
        self.memory.remember_alias(category, normalized, target=dict(target))
        aliases = self._all_aliases()
        category_bucket = dict(aliases.get(category) or {})
        existing = category_bucket.get(normalized)
        existing_payload = dict(existing) if isinstance(existing, dict) else {}
        count = int(existing_payload.get("count", 0) or 0) + 1
        category_bucket[normalized] = {
            **existing_payload,
            **dict(target),
            "alias": normalized,
            "count": count,
            "last_used_at": utc_now_iso(),
            "source_class": MemorySourceClass.INFERRED.value,
        }
        aliases[category] = category_bucket
        self.preferences.set_preference(self._alias_memory_key(), aliases)

    def resolve_alias(self, category: str, phrase: str, *, threshold: float = 0.84) -> dict[str, object] | None:
        resolved = self.memory.resolve_alias(category, phrase, threshold=threshold)
        if resolved is not None:
            return resolved
        normalized = normalize_lookup_phrase(phrase) or normalize_phrase(phrase)
        if not normalized:
            return None
        aliases = self.get_aliases(category)
        exact = aliases.get(normalized)
        if isinstance(exact, dict):
            return {**exact, "matched_alias": normalized, "confidence": 1.0}
        best_key = ""
        best_payload: dict[str, object] | None = None
        best_score = 0.0
        for key, payload in aliases.items():
            score = fuzzy_ratio(normalized, key)
            if score > best_score:
                best_score = score
                best_key = key
                best_payload = payload
        if best_payload is None or best_score < threshold:
            return None
        return {**best_payload, "matched_alias": best_key, "confidence": best_score}

    def get_learned_preferences(self) -> dict[str, dict[str, object]]:
        learned = self.memory.get_learned_preferences()
        if learned:
            return learned
        state = self.preferences.get_all()
        value = state.get(self._preference_memory_key())
        if not isinstance(value, dict):
            return {}
        return {
            str(scope): {str(key): item for key, item in bucket.items()}
            for scope, bucket in value.items()
            if isinstance(bucket, dict)
        }

    def remember_preference(self, scope: str, key: str, value: object) -> None:
        self.memory.remember_preference(
            scope,
            key,
            value,
            source_class=MemorySourceClass.OPERATOR_PROVIDED.value,
        )
        preferences = self.get_learned_preferences()
        scope_bucket = dict(preferences.get(scope) or {})
        existing = scope_bucket.get(key)
        existing_entry = dict(existing) if isinstance(existing, dict) else {}
        count = int(existing_entry.get("count", 0) or 0) + 1 if existing_entry.get("value") == value else 1
        scope_bucket[key] = {
            "value": value,
            "count": count,
            "updated_at": utc_now_iso(),
            "confidence": round(min(0.55 + (0.1 * count), 0.95), 3),
            "source_class": MemorySourceClass.OPERATOR_PROVIDED.value,
            "operator_locked": bool(existing_entry.get("operator_locked", False)),
        }
        preferences[scope] = scope_bucket
        self.preferences.set_preference(self._preference_memory_key(), preferences)

    def preference_value(self, scope: str, key: str, *, minimum_count: int = 1) -> object | None:
        value = self.memory.preference_value(scope, key, minimum_count=minimum_count)
        if value is not None:
            return value
        scope_bucket = self.get_learned_preferences().get(scope, {})
        if not isinstance(scope_bucket, dict):
            return None
        entry = scope_bucket.get(key)
        if not isinstance(entry, dict):
            return None
        if int(entry.get("count", 0)) < minimum_count:
            return None
        return entry.get("value")

    def _key(self, session_id: str, role: str) -> str:
        return f"assistant.session.{session_id}.{role}.previous_response_id"

    def _workspace_key(self, session_id: str) -> str:
        return f"assistant.session.{session_id}.active_workspace_id"

    def _task_key(self, session_id: str) -> str:
        return f"assistant.session.{session_id}.active_task_id"

    def _posture_key(self, session_id: str) -> str:
        return f"assistant.session.{session_id}.active_posture"

    def _recent_tool_results_key(self, session_id: str) -> str:
        return f"assistant.session.{session_id}.recent_tool_results"

    def _request_state_key(self, session_id: str) -> str:
        return f"assistant.session.{session_id}.active_request_state"

    def _active_context_key(self, session_id: str) -> str:
        return f"assistant.session.{session_id}.active_context"

    def _recent_context_resolutions_key(self, session_id: str) -> str:
        return f"assistant.session.{session_id}.recent_context_resolutions"

    def _suggestion_state_key(self, session_id: str) -> str:
        return f"assistant.session.{session_id}.suggestion_state"

    def _alias_memory_key(self) -> str:
        return "assistant.memory.aliases"

    def _preference_memory_key(self) -> str:
        return "assistant.memory.preferences"

    def _all_aliases(self) -> dict[str, dict[str, Any]]:
        state = self.preferences.get_all()
        value = state.get(self._alias_memory_key())
        if not isinstance(value, dict):
            return {}
        aliases: dict[str, dict[str, Any]] = {}
        for category, bucket in value.items():
            if isinstance(bucket, dict):
                aliases[str(category)] = {str(key): dict(item) for key, item in bucket.items() if isinstance(item, dict)}
        return aliases

    def _alias_allowed(self, alias: str) -> bool:
        if not alias or len(alias) < 2:
            return False
        if alias in {"workspace", "project", "thing", "stuff", "setup", "environment", "current work"}:
            return False
        return True

    def _tool_family(self, tool_name: str) -> str:
        families = {
            "power_status": "power",
            "power_projection": "power",
            "resource_status": "resource",
            "storage_status": "storage",
            "network_status": "network",
            "machine_status": "machine",
            "location_status": "location",
            "saved_locations": "location",
            "save_location": "location",
            "weather_current": "weather",
            "active_apps": "applications",
            "browser_context": "browser",
            "activity_summary": "activity",
            "desktop_search": "search",
            "workflow_execute": "workflow",
            "repair_action": "repair",
            "routine_execute": "routine",
            "routine_save": "routine",
            "trusted_hook_register": "trusted_hook",
            "trusted_hook_execute": "trusted_hook",
            "file_operation": "file_operation",
            "maintenance_action": "maintenance",
            "recent_files": "files",
            "workspace_restore": "workspace",
            "workspace_assemble": "workspace",
            "workspace_save": "workspace",
            "workspace_clear": "workspace",
            "workspace_archive": "workspace",
            "workspace_rename": "workspace",
            "workspace_tag": "workspace",
            "workspace_list": "workspace",
            "workspace_where_left_off": "workspace",
            "workspace_next_steps": "workspace",
            "deck_open_url": "browser",
            "external_open_url": "browser",
            "deck_open_file": "files",
            "external_open_file": "files",
        }
        return families.get(tool_name, tool_name)
