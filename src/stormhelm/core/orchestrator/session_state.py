from __future__ import annotations

from stormhelm.core.memory.repositories import PreferencesRepository


class ConversationStateStore:
    def __init__(self, preferences: PreferencesRepository) -> None:
        self.preferences = preferences

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

    def _key(self, session_id: str, role: str) -> str:
        return f"assistant.session.{session_id}.{role}.previous_response_id"

    def _workspace_key(self, session_id: str) -> str:
        return f"assistant.session.{session_id}.active_workspace_id"
