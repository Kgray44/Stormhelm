from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from stormhelm.core.intelligence.language import fuzzy_ratio, normalize_lookup_phrase, normalize_phrase
from stormhelm.core.memory import SemanticMemoryRepository, SemanticMemoryService
from stormhelm.core.memory.models import MemorySourceClass
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.shared.time import utc_now_iso

_CONTEXT_RESOLUTION_SCALAR_KEYS = {
    "kind",
    "query",
    "summary",
    "detail",
    "state",
    "source",
    "freshness",
    "label",
    "intent",
    "captured_at",
}
_CONTEXT_RESOLUTION_STRUCTURED_KEYS = {
    "result",
    "failure",
    "trace",
    "verification",
    "recovery_plan",
    "recovery_result",
    "preview",
    "attempt",
    "telemetry",
}
_TRACE_KEEP_KEYS = {
    "operation",
    "operation_type",
    "result_state",
    "verification_state",
    "fallback_reason",
    "duration_ms",
    "total_duration_ms",
    "slowest_stage",
}
_ACTIVE_REQUEST_TOP_KEYS = {
    "family",
    "subject",
    "request_type",
    "query_shape",
    "captured_at",
    "context_source",
    "context_freshness",
    "context_reusable",
    "requested_action",
}
_ACTIVE_REQUEST_PARAMETER_KEYS = {
    "approval_outcome",
    "approval_scope",
    "context_freshness",
    "context_reusable",
    "destination_alias",
    "execution_type",
    "follow_up_reuse",
    "operation_type",
    "path",
    "pending_preview",
    "pending_relay_request_id",
    "payload_hint",
    "query",
    "query_shape",
    "recipient",
    "request_stage",
    "requested_action",
    "result_state",
    "selected_source_route",
    "target_name",
    "trust_request_id",
    "url",
    "workflow_kind",
    "ambiguity_choices",
    "note_text",
}
_ACTIVE_REQUEST_TRUST_KEYS = {
    "approval_scope",
    "expires_at",
    "prompt_id",
    "reason",
    "request_id",
    "state",
    "status",
    "trust_prompt_id",
}
_ACTIVE_REQUEST_STRUCTURED_QUERY_KEYS = {
    "comparison_target",
    "current_context_reference",
    "domain",
    "execution_type",
    "output_mode",
    "output_type",
    "query_shape",
    "requested_action",
}


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
        value = self._preference_value(self._request_state_key(session_id))
        if isinstance(value, dict):
            return dict(value)
        return {}

    def set_active_request_state(self, session_id: str, request_state: dict[str, object] | None) -> None:
        self.preferences.set_preference(
            self._request_state_key(session_id),
            _compact_active_request_state(request_state or {}),
        )

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

    def get_turn_context_snapshot(
        self,
        session_id: str,
        *,
        max_age_seconds: float | None = None,
        prefer_local_memory: bool = False,
    ) -> dict[str, object]:
        """Load the per-turn context buckets with one preference snapshot.

        The command-eval compact path writes continuity state to both semantic
        memory and local preferences. Reading the local snapshot first avoids
        repeated empty semantic-memory queries while preserving the same
        session-scoped state and freshness rules.
        """
        keys = (
            self._posture_key(session_id),
            self._request_state_key(session_id),
            self._active_context_key(session_id),
            self._recent_tool_results_key(session_id),
            self._recent_context_resolutions_key(session_id),
            self._preference_memory_key(),
        )
        state = self._preference_values(keys)
        recent_tool_results: list[dict[str, object]] = []
        if not prefer_local_memory:
            recent_tool_results = self.memory.list_recent_session_tool_results(
                session_id,
                max_age_seconds=max_age_seconds,
            )
        if not recent_tool_results:
            recent_tool_results = self._recent_tool_results_from_state(
                state,
                session_id,
                max_age_seconds=max_age_seconds,
            )

        recent_context_resolutions: list[dict[str, object]] = []
        if not prefer_local_memory:
            recent_context_resolutions = self.memory.list_recent_context_resolutions(session_id)
        if not recent_context_resolutions:
            recent_context_resolutions = self._recent_context_resolutions_from_state(state, session_id)

        learned_preferences: dict[str, dict[str, object]] = {}
        if not prefer_local_memory:
            learned_preferences = self.memory.get_learned_preferences()
        if not learned_preferences:
            learned_preferences = self._learned_preferences_from_state(state)

        return {
            "active_posture": self._dict_value(state, self._posture_key(session_id)),
            "active_request_state": self._dict_value(state, self._request_state_key(session_id)),
            "active_context": self._dict_value(state, self._active_context_key(session_id)),
            "recent_tool_results": recent_tool_results,
            "recent_context_resolutions": recent_context_resolutions,
            "learned_preferences": learned_preferences,
            "source": "local_preference_snapshot" if prefer_local_memory else "semantic_memory_then_local_snapshot",
        }

    def _dict_value(self, state: dict[str, object], key: str) -> dict[str, object]:
        value = state.get(key)
        if isinstance(value, dict):
            return dict(value)
        return {}

    def _recent_tool_results_from_state(
        self,
        state: dict[str, object],
        session_id: str,
        *,
        max_age_seconds: float | None = None,
    ) -> list[dict[str, object]]:
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
        state = self._preference_values((self._recent_context_resolutions_key(session_id),))
        return self._recent_context_resolutions_from_state(state, session_id)

    def _recent_context_resolutions_from_state(
        self,
        state: dict[str, object],
        session_id: str,
    ) -> list[dict[str, object]]:
        value = state.get(self._recent_context_resolutions_key(session_id))
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    def remember_context_resolution(self, session_id: str, resolution: dict[str, object]) -> None:
        command_eval_dry_run = os.environ.get("STORMHELM_COMMAND_EVAL_DRY_RUN", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        entry = _compact_context_resolution(resolution)
        if not command_eval_dry_run:
            self.memory.remember_context_resolution(session_id, dict(entry))
        entry.setdefault("captured_at", utc_now_iso())
        existing = self._preference_value(self._recent_context_resolutions_key(session_id))
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
        return self._learned_preferences_from_state(state)

    def _learned_preferences_from_state(self, state: dict[str, object]) -> dict[str, dict[str, object]]:
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

    def _preference_value(self, key: str) -> object | None:
        reader = getattr(self.preferences, "get_preference", None)
        if callable(reader):
            return reader(key)
        return self.preferences.get_all().get(key)

    def _preference_values(self, keys: tuple[str, ...] | list[str]) -> dict[str, object]:
        reader = getattr(self.preferences, "get_many", None)
        if callable(reader):
            return dict(reader(list(keys)))
        all_values = self.preferences.get_all()
        return {key: all_values.get(key) for key in keys}

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


def _compact_context_resolution(resolution: dict[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {}
    for key in _CONTEXT_RESOLUTION_SCALAR_KEYS:
        if key in resolution:
            value = resolution.get(key)
            if value not in (None, "", [], {}):
                compact[key] = _compact_value(value, depth=1)
    for key in _CONTEXT_RESOLUTION_STRUCTURED_KEYS:
        if key in resolution:
            value = resolution.get(key)
            if value not in (None, "", [], {}):
                compact[key] = _compact_value(value, depth=2)
    analysis = resolution.get("analysis_result")
    if isinstance(analysis, dict):
        compact["analysis_result"] = _compact_screen_analysis(analysis)
    if "kind" not in compact and resolution.get("kind"):
        compact["kind"] = str(resolution.get("kind"))
    return compact or {"summary": "Stored recent context resolution."}


def _compact_active_request_state(request_state: dict[str, object]) -> dict[str, object]:
    if not isinstance(request_state, dict) or not request_state:
        return {}
    compact: dict[str, object] = {}
    for key in _ACTIVE_REQUEST_TOP_KEYS:
        value = request_state.get(key)
        if value not in (None, "", [], {}):
            compact[key] = _compact_value(value, depth=1)
    parameters = request_state.get("parameters")
    if isinstance(parameters, dict):
        compact_parameters: dict[str, object] = {}
        for key in _ACTIVE_REQUEST_PARAMETER_KEYS:
            value = parameters.get(key)
            if value in (None, "", [], {}):
                continue
            if key == "pending_preview":
                compact_parameters[key] = _compact_pending_preview(value)
            else:
                compact_parameters[key] = _compact_value(value, depth=1)
        if compact_parameters:
            compact["parameters"] = compact_parameters
    trust = request_state.get("trust")
    if isinstance(trust, dict):
        compact_trust = {
            key: _compact_value(trust.get(key), depth=1)
            for key in _ACTIVE_REQUEST_TRUST_KEYS
            if trust.get(key) not in (None, "", [], {})
        }
        if compact_trust:
            compact["trust"] = compact_trust
    route = request_state.get("route")
    if isinstance(route, dict):
        compact_route = {
            key: _compact_value(route.get(key), depth=1)
            for key in ("response_mode", "tool_name", "route_family", "route_mode", "result_state")
            if route.get(key) not in (None, "", [], {})
        }
        if compact_route:
            compact["route"] = compact_route
    structured_query = request_state.get("structured_query")
    if isinstance(structured_query, dict):
        compact_query = {
            key: _compact_value(structured_query.get(key), depth=1)
            for key in _ACTIVE_REQUEST_STRUCTURED_QUERY_KEYS
            if structured_query.get(key) not in (None, "", [], {})
        }
        slots = structured_query.get("slots")
        if isinstance(slots, dict):
            compact_slots = {
                key: _compact_value(slots.get(key), depth=1)
                for key in _ACTIVE_REQUEST_PARAMETER_KEYS
                if slots.get(key) not in (None, "", [], {})
            }
            if compact_slots:
                compact_query["slots"] = compact_slots
        if compact_query:
            compact["structured_query"] = compact_query
    for key in ("pending_approval", "trust_prompt_id", "request_stage"):
        value = request_state.get(key)
        if value not in (None, "", [], {}):
            compact[key] = _compact_value(value, depth=1)
    return compact


def _compact_pending_preview(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    destination = value.get("destination") if isinstance(value.get("destination"), dict) else {}
    payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
    policy = value.get("policy") if isinstance(value.get("policy"), dict) else {}
    fingerprint = value.get("fingerprint") if isinstance(value.get("fingerprint"), dict) else {}
    compact: dict[str, object] = {
        "route_mode": value.get("route_mode"),
        "note_text": value.get("note_text"),
        "state": value.get("state"),
        "screen_awareness_used": value.get("screen_awareness_used"),
        "ambiguity_reason": value.get("ambiguity_reason"),
        "candidate_summaries": list(value.get("candidate_summaries") or [])
        if isinstance(value.get("candidate_summaries"), list)
        else [],
        "created_at": value.get("created_at"),
        "expires_at": value.get("expires_at"),
    }
    if destination:
        compact["destination"] = {
            key: destination.get(key)
            for key in (
                "alias",
                "label",
                "destination_kind",
                "route_mode",
                "navigation_mode",
                "search_query",
                "thread_uri",
                "trusted",
                "matched_alias",
                "confidence",
            )
            if destination.get(key) not in (None, "", [], {})
        }
    if payload:
        compact["payload"] = {
            key: payload.get(key)
            for key in (
                "kind",
                "summary",
                "provenance",
                "confidence",
                "title",
                "url",
                "path",
                "text",
                "preview_text",
                "metadata",
                "warnings",
                "screen_awareness_used",
            )
            if payload.get(key) not in (None, "", [], {})
        }
    if policy:
        compact["policy"] = {
            key: policy.get(key)
            for key in ("outcome", "warnings", "blocks", "requires_confirmation")
            if policy.get(key) not in (None, "", [], {})
        }
    if fingerprint:
        compact["fingerprint"] = {
            key: fingerprint.get(key)
            for key in (
                "fingerprint_id",
                "destination_alias",
                "destination_label",
                "destination_kind",
                "route_mode",
                "payload_kind",
                "payload_source",
                "payload_identity",
                "payload_hash",
                "note_hash",
                "source_anchor",
            )
            if fingerprint.get(key) not in (None, "", [], {})
        }
    return {
        key: item
        for key, item in compact.items()
        if item not in (None, "", [], {})
    }


def _compact_screen_analysis(analysis: dict[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {}
    for key in ("verification_state", "fallback_reason", "result_state"):
        value = analysis.get(key)
        if value not in (None, ""):
            compact[key] = _compact_value(value, depth=1)
    confidence = analysis.get("confidence")
    if isinstance(confidence, dict):
        compact["confidence"] = {
            key: confidence.get(key)
            for key in ("level", "score")
            if confidence.get(key) not in (None, "")
        }
    limitations = analysis.get("limitations")
    if isinstance(limitations, list):
        compact["limitations"] = [
            _compact_value(item, depth=2)
            for item in limitations[:4]
            if isinstance(item, dict)
        ]
    observation = analysis.get("observation")
    if isinstance(observation, dict):
        observation_payload: dict[str, object] = {}
        for key in ("captured_at", "source_types_used", "app_identity", "selected_text", "visual_text"):
            value = observation.get(key)
            if value not in (None, "", [], {}):
                observation_payload[key] = _compact_value(value, depth=1)
        visual_metadata = observation.get("visual_metadata")
        if isinstance(visual_metadata, dict) and isinstance(visual_metadata.get("screen_capture"), dict):
            screen_capture = dict(visual_metadata.get("screen_capture") or {})
            observation_payload["screen_capture"] = {
                key: screen_capture.get(key)
                for key in ("enabled", "attempted", "captured", "reason", "scope")
                if screen_capture.get(key) not in (None, "")
            }
        if observation_payload:
            compact["observation"] = observation_payload
    latency_trace = analysis.get("latency_trace")
    if isinstance(latency_trace, dict):
        compact["latency_trace"] = {
            key: latency_trace.get(key)
            for key in ("total_duration_ms", "slowest_stage")
            if latency_trace.get(key) not in (None, "")
        }
    return compact


def _compact_value(value: object, *, depth: int) -> object:
    if isinstance(value, str):
        return value if len(value) <= 240 else value[:237].rstrip() + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_compact_value(item, depth=depth - 1) for item in value[:6]] if depth > 0 else f"list[{len(value)}]"
    if isinstance(value, dict):
        if depth <= 0:
            return {
                "keys": [str(key) for key in list(value.keys())[:8]],
                "truncated": True,
            }
        keys = list(value.keys())
        selected_keys = keys[:12]
        if "trace" in selected_keys:
            selected_keys = [key for key in selected_keys if key != "trace"]
        compact = {
            str(key): _compact_value(value.get(key), depth=depth - 1)
            for key in selected_keys
            if value.get(key) not in (None, "", [], {})
        }
        if set(value.keys()).issubset(_TRACE_KEEP_KEYS):
            return compact
        if len(keys) > len(selected_keys):
            compact["truncated"] = True
            compact["omitted_key_count"] = len(keys) - len(selected_keys)
        return compact
    return str(value)
