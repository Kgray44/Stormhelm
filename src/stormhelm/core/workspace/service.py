from __future__ import annotations

from typing import Any

from stormhelm.config.models import AppConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository


class WorkspaceService:
    def __init__(
        self,
        *,
        config: AppConfig,
        repository: WorkspaceRepository,
        notes: NotesRepository,
        conversations: ConversationRepository,
        preferences: PreferencesRepository,
        session_state: ConversationStateStore,
        indexer: WorkspaceIndexer,
        events: EventBuffer,
        persona: PersonaContract,
    ) -> None:
        self.config = config
        self.repository = repository
        self.notes = notes
        self.conversations = conversations
        self.preferences = preferences
        self.session_state = session_state
        self.indexer = indexer
        self.events = events
        self.persona = persona

    def assemble_workspace(self, query: str, *, session_id: str) -> dict[str, Any]:
        topic = self._extract_topic(query)
        workspace = self._ensure_workspace(topic)
        file_candidates = self.indexer.search_files(topic, limit=6)
        note_candidates = self._matching_notes(topic, limit=2)
        for item in [*file_candidates, *note_candidates]:
            self.repository.upsert_item(workspace.workspace_id, item)
        items = [item.to_action_item() for item in self.repository.list_items(workspace.workspace_id, limit=8)]
        self.session_state.set_active_workspace_id(session_id, workspace.workspace_id)
        self.repository.record_activity(
            workspace_id=workspace.workspace_id,
            session_id=session_id,
            activity_type="assemble",
            description=f"Assembled workspace for {topic}.",
            payload={"query": query, "item_count": len(items)},
        )
        summary = self.persona.workspace_assembled(workspace.name, len(items), "local memory and indexed bearings")
        return {
            "workspace": workspace.to_dict(),
            "items": items,
            "summary": summary,
            "action": {
                "type": "workspace_restore",
                "target": "deck",
                "module": "chartroom",
                "section": "working-set",
                "workspace": workspace.to_dict(),
                "items": items,
                "active_item_id": items[0]["itemId"] if items else "",
            },
        }

    def restore_workspace(self, query: str, *, session_id: str) -> dict[str, Any]:
        topic = self._extract_topic(query)
        current_workspace = None
        if "where we left off" in query.lower() or "continue" in query.lower():
            active_id = self.session_state.get_active_workspace_id(session_id)
            if active_id:
                current_workspace = self.repository.get_workspace(active_id)
        matches = [current_workspace] if current_workspace is not None else []
        if not matches:
            matches = self.repository.search_workspaces(topic, limit=5)
        if not matches:
            return self.assemble_workspace(query, session_id=session_id)

        workspace = matches[0]
        items = [item.to_action_item() for item in self.repository.list_items(workspace.workspace_id, limit=8)]
        self.session_state.set_active_workspace_id(session_id, workspace.workspace_id)
        self.repository.record_activity(
            workspace_id=workspace.workspace_id,
            session_id=session_id,
            activity_type="restore",
            description=f"Restored workspace {workspace.name}.",
            payload={"query": query, "item_count": len(items)},
        )
        summary = self.persona.workspace_restored(workspace.name, len(items), "retained workspace memory")
        return {
            "workspace": workspace.to_dict(),
            "items": items,
            "summary": summary,
            "action": {
                "type": "workspace_restore",
                "target": "deck",
                "module": "chartroom",
                "section": "working-set",
                "workspace": workspace.to_dict(),
                "items": items,
                "active_item_id": items[0]["itemId"] if items else "",
            },
        }

    def remember_actions(
        self,
        *,
        session_id: str,
        prompt: str,
        actions: list[dict[str, Any]],
        surface_mode: str,
        active_module: str,
    ) -> None:
        del surface_mode, active_module
        if not actions:
            return
        active_id = self.session_state.get_active_workspace_id(session_id)
        for action in actions:
            action_type = str(action.get("type", "")).strip().lower()
            if action_type == "workspace_restore":
                workspace_data = action.get("workspace", {})
                if not isinstance(workspace_data, dict):
                    continue
                workspace = self.repository.upsert_workspace(
                    workspace_id=str(workspace_data.get("workspaceId") or ""),
                    name=str(workspace_data.get("name", "Recovered Workspace")),
                    topic=str(workspace_data.get("topic", workspace_data.get("name", "workspace"))),
                    summary=str(workspace_data.get("summary", "")),
                    tags=list(workspace_data.get("tags", [])) if isinstance(workspace_data.get("tags"), list) else [],
                )
                self.session_state.set_active_workspace_id(session_id, workspace.workspace_id)
                for item in action.get("items", []):
                    if isinstance(item, dict):
                        self.repository.upsert_item(workspace.workspace_id, item)
                active_id = workspace.workspace_id
                continue
            if action_type == "workspace_open":
                if not active_id:
                    workspace = self._ensure_workspace(self._extract_topic(prompt))
                    self.session_state.set_active_workspace_id(session_id, workspace.workspace_id)
                    active_id = workspace.workspace_id
                item = action.get("item")
                if isinstance(item, dict):
                    self.repository.upsert_item(active_id, item)
                    self.repository.record_activity(
                        workspace_id=active_id,
                        session_id=session_id,
                        activity_type="open",
                        description=f"Held {item.get('title', 'item')} in the Deck.",
                        payload={"prompt": prompt},
                    )

    def active_workspace_summary(self, session_id: str) -> dict[str, Any]:
        active_id = self.session_state.get_active_workspace_id(session_id)
        if not active_id:
            return {}
        workspace = self.repository.get_workspace(active_id)
        if workspace is None:
            return {}
        items = [item.to_action_item() for item in self.repository.list_items(active_id, limit=8)]
        return {
            "workspace": workspace.to_dict(),
            "opened_items": items,
            "active_item": items[0] if items else {},
        }

    def _ensure_workspace(self, topic: str):
        matches = self.repository.search_workspaces(topic, limit=1)
        if matches:
            return matches[0]
        name = " ".join(part.capitalize() for part in topic.split()) or "Recovered Workspace"
        return self.repository.upsert_workspace(name=name, topic=topic, summary=f"Workspace for {topic}.")

    def _matching_notes(self, topic: str, *, limit: int) -> list[dict[str, Any]]:
        lowered = topic.lower()
        matches: list[dict[str, Any]] = []
        for note in self.notes.list_notes(limit=25):
            combined = f"{note.title} {note.content}".lower()
            if lowered not in combined:
                continue
            matches.append(
                {
                    "kind": "text",
                    "viewer": "text",
                    "title": note.title,
                    "subtitle": "Logbook",
                    "module": "logbook",
                    "section": "notes",
                    "summary": note.content[:120],
                    "content": note.content,
                }
            )
            if len(matches) >= limit:
                break
        return matches

    def _extract_topic(self, query: str) -> str:
        lowered = query.lower().strip()
        replacements = [
            "set up a workspace for",
            "setup a workspace for",
            "restore the",
            "workspace",
            "continue the",
            "bring back the",
            "open my",
            "continue where we left off",
            "pick up where we left off",
            "gather everything relevant for",
        ]
        topic = lowered
        for phrase in replacements:
            topic = topic.replace(phrase, " ")
        topic = " ".join(topic.split()).strip(" .")
        return topic or "current work"
