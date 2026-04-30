from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from stormhelm.config.models import AppConfig
from stormhelm.core.intelligence.language import fuzzy_ratio, normalize_lookup_phrase, normalize_phrase, token_overlap
from stormhelm.core.events import EventBuffer
from stormhelm.core.memory import MemoryQuery, MemoryRetrievalIntent, SemanticMemoryRepository, SemanticMemoryService
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.models import (
    WorkspaceAssemblyPlan,
    WorkspaceContinuitySnapshot,
    WorkspaceInclusionReason,
    WorkspaceRecord,
    WorkspaceResumeContext,
    WorkspaceRoleCluster,
    WorkspaceSessionPosture,
    WorkspaceTemplateDefinition,
)
from stormhelm.core.workspace.repository import WorkspaceRepository


_VAGUE_TOPIC_TOKENS = {
    "again",
    "before",
    "bring",
    "can",
    "continue",
    "could",
    "doing",
    "files",
    "for",
    "from",
    "left",
    "me",
    "old",
    "pull",
    "show",
    "stuff",
    "that",
    "the",
    "thing",
    "things",
    "up",
    "we",
    "were",
    "what",
    "would",
    "you",
}

_SURFACE_PURPOSES = {
    "opened-items": "What is actively in use right now?",
    "references": "What supports this work?",
    "findings": "What have we learned or confirmed?",
    "session": "What is the current work session about?",
    "tasks": "What still needs doing?",
    "files": "What concrete file assets matter here?",
    "logbook": "What has been recorded or remembered?",
}

_SURFACE_TITLES = {
    "opened-items": "Opened Items",
    "references": "References",
    "findings": "Findings",
    "session": "Session",
    "tasks": "Tasks",
    "files": "Files",
    "logbook": "Logbook",
}

_SURFACE_PRESENTATION_KINDS = {
    "opened-items": "collection",
    "references": "collection",
    "findings": "highlights",
    "session": "panels",
    "tasks": "task-groups",
    "files": "collection",
    "logbook": "collection",
}

WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT = 100
WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT = 100
WORKSPACE_PAYLOAD_WARN_BYTES = 1_000_000
WORKSPACE_PAYLOAD_FAIL_BYTES = 5_000_000
_WORKSPACE_COMPACT_STRING_LIMIT = 600
_WORKSPACE_COMPACT_ITEM_KEYS = (
    "itemId",
    "id",
    "kind",
    "viewer",
    "title",
    "subtitle",
    "module",
    "section",
    "url",
    "path",
    "summary",
    "detail",
    "badge",
    "role",
    "source",
    "score",
    "status",
    "inclusionReasons",
    "whyIncluded",
    "surfaceLinks",
)

_WORKSPACE_COMMAND_TOKENS = {
    "a",
    "an",
    "assemble",
    "bring",
    "back",
    "build",
    "can",
    "continue",
    "could",
    "create",
    "environment",
    "for",
    "from",
    "make",
    "my",
    "new",
    "open",
    "please",
    "prepare",
    "reopen",
    "restore",
    "resume",
    "set",
    "setup",
    "start",
    "the",
    "up",
    "would",
    "workspace",
    "workspaces",
    "you",
}


def _add_workspace_subspan(subspans: dict[str, float], key: str, started_at: float) -> None:
    subspans[key] = round(float(subspans.get(key, 0.0)) + (perf_counter() - started_at) * 1000, 3)


def _empty_workspace_subspans() -> dict[str, float]:
    return {
        "workspace_state_load_ms": 0.0,
        "workspace_db_query_ms": 0.0,
        "workspace_file_scan_ms": 0.0,
        "workspace_index_or_search_ms": 0.0,
        "workspace_save_write_ms": 0.0,
        "workspace_task_graph_ms": 0.0,
        "workspace_event_emit_ms": 0.0,
        "workspace_dto_build_ms": 0.0,
        "workspace_payload_build_ms": 0.0,
    }

_TOPIC_TOKEN_NORMALIZATIONS = {
    "researching": "research",
    "investigating": "research",
    "studying": "research",
}


def _default_workspace_templates() -> dict[str, WorkspaceTemplateDefinition]:
    templates = [
        WorkspaceTemplateDefinition(
            key="project",
            title="Project",
            description="Balanced project workspace for active work, supporting files, and next steps.",
            aliases=["project", "workspace", "engineering", "project workspace"],
            default_module="chartroom",
            default_section="session",
            emphasis=["session", "tasks", "opened-items", "files", "references"],
            search_keywords=["project", "plan", "task", "notes", "reference"],
            preferred_extensions=[".md", ".txt", ".json", ".toml", ".py", ".ts", ".tsx"],
            surface_weights={"session": 1.0, "tasks": 0.95, "opened-items": 0.85, "files": 0.8, "references": 0.7, "logbook": 0.55},
            purpose_summary="the strongest active files, support material, and next steps for the project",
        ),
        WorkspaceTemplateDefinition(
            key="troubleshooting",
            title="Troubleshooting",
            description="Operational troubleshooting workspace with diagnostics-first posture.",
            aliases=["troubleshooting", "troubleshoot", "debug", "repair", "fix", "issue"],
            default_module="systems",
            default_section="diagnostics",
            emphasis=["session", "tasks", "opened-items", "references", "files"],
            search_keywords=["diagnostic", "log", "error", "issue", "trace", "report", "network", "crash"],
            preferred_extensions=[".log", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".ps1"],
            surface_weights={"session": 1.0, "tasks": 0.95, "opened-items": 0.9, "references": 0.8, "files": 0.8, "logbook": 0.7},
            purpose_summary="diagnostic surfaces, retained issue context, and the strongest troubleshooting materials",
        ),
        WorkspaceTemplateDefinition(
            key="research",
            title="Research",
            description="Reference-heavy research workspace with findings and supporting material.",
            aliases=["research", "investigate", "investigation", "study"],
            default_module="browser",
            default_section="references",
            emphasis=["references", "findings", "files", "logbook", "tasks"],
            search_keywords=["research", "reference", "study", "analysis", "doc", "docs", "paper"],
            preferred_extensions=[".md", ".txt", ".pdf", ".html", ".csv"],
            surface_weights={"references": 1.0, "findings": 0.95, "files": 0.8, "logbook": 0.75, "tasks": 0.65, "opened-items": 0.55},
            purpose_summary="supporting references, findings space, and the most relevant research material",
        ),
        WorkspaceTemplateDefinition(
            key="writing",
            title="Writing",
            description="Writing workspace centered on drafts, notes, and supporting references.",
            aliases=["writing", "write", "draft", "essay", "article", "note"],
            default_module="files",
            default_section="opened-items",
            emphasis=["opened-items", "files", "logbook", "references", "tasks"],
            search_keywords=["draft", "outline", "notes", "reference", "writing"],
            preferred_extensions=[".md", ".txt", ".markdown"],
            surface_weights={"opened-items": 1.0, "files": 0.9, "logbook": 0.8, "references": 0.65, "tasks": 0.65},
            purpose_summary="the active draft, supporting notes, and nearby references",
        ),
        WorkspaceTemplateDefinition(
            key="project-planning",
            title="Project Planning",
            description="Planning workspace centered on posture, tasks, and recorded context.",
            aliases=["planning", "plan", "roadmap", "milestone", "project planning"],
            default_module="chartroom",
            default_section="tasks",
            emphasis=["tasks", "session", "logbook", "references", "files"],
            search_keywords=["plan", "roadmap", "task", "timeline", "milestone"],
            preferred_extensions=[".md", ".txt", ".csv", ".json"],
            surface_weights={"tasks": 1.0, "session": 0.95, "logbook": 0.85, "references": 0.7, "files": 0.65},
            purpose_summary="task posture, retained notes, and the planning material that supports the next steps",
        ),
        WorkspaceTemplateDefinition(
            key="review-analysis",
            title="Review",
            description="Review and analysis workspace for evidence, findings, and next actions.",
            aliases=["review", "analysis", "audit", "assess"],
            default_module="chartroom",
            default_section="findings",
            emphasis=["findings", "references", "files", "tasks", "session"],
            search_keywords=["review", "analysis", "audit", "evidence", "finding"],
            preferred_extensions=[".md", ".txt", ".json", ".csv", ".log"],
            surface_weights={"findings": 1.0, "references": 0.95, "files": 0.8, "tasks": 0.7, "session": 0.7},
            purpose_summary="the strongest evidence, findings, and follow-up actions for the review",
        ),
        WorkspaceTemplateDefinition(
            key="systems-diagnostics",
            title="Systems Diagnostics",
            description="System-level diagnostics workspace for machine and operational investigation.",
            aliases=["systems diagnostics", "system diagnostics", "machine diagnostics", "machine"],
            default_module="systems",
            default_section="diagnostics",
            emphasis=["session", "tasks", "references", "files", "logbook"],
            search_keywords=["system", "diagnostic", "machine", "latency", "driver", "performance"],
            preferred_extensions=[".log", ".txt", ".md", ".json", ".ini", ".cfg"],
            surface_weights={"session": 1.0, "tasks": 0.9, "references": 0.8, "files": 0.8, "logbook": 0.7},
            purpose_summary="diagnostic surfaces and the strongest recent system materials",
        ),
        WorkspaceTemplateDefinition(
            key="minecraft-admin",
            title="Minecraft Admin",
            description="Minecraft administration workspace for server, mods, configs, and operational notes.",
            aliases=["minecraft admin", "minecraft", "server admin", "mods", "plugins"],
            default_module="files",
            default_section="working-set",
            emphasis=["files", "opened-items", "references", "tasks", "logbook"],
            search_keywords=["minecraft", "server", "mod", "mods", "plugin", "plugins", "config"],
            preferred_extensions=[".txt", ".md", ".json", ".toml", ".yaml", ".yml", ".properties"],
            surface_weights={"files": 1.0, "opened-items": 0.9, "references": 0.8, "tasks": 0.7, "logbook": 0.65},
            purpose_summary="server files, supporting references, and the current admin task posture",
        ),
    ]
    return {template.key: template for template in templates}


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
        memory: SemanticMemoryService | None = None,
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
        self.memory = memory or SemanticMemoryService(SemanticMemoryRepository(repository.database))
        self.templates = _default_workspace_templates()

    def _compact_workspace_item(self, item: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {}
        compact: dict[str, Any] = {}
        for key in _WORKSPACE_COMPACT_ITEM_KEYS:
            if key not in item:
                continue
            value = item.get(key)
            if isinstance(value, str):
                compact[key] = value[:_WORKSPACE_COMPACT_STRING_LIMIT]
            elif isinstance(value, (int, float, bool)) or value is None:
                compact[key] = value
            elif key in {"inclusionReasons", "whyIncluded"} and isinstance(value, list):
                compact[key] = [
                    compact_reason
                    for compact_reason in (self._compact_workspace_reason(entry) for entry in value[:8])
                    if compact_reason
                ]
            elif key == "surfaceLinks" and isinstance(value, list):
                compact[key] = [
                    compact_link
                    for compact_link in (self._compact_workspace_surface_link(entry) for entry in value[:8])
                    if compact_link
                ]
            elif isinstance(value, list):
                compact[key] = [
                    str(entry)[:_WORKSPACE_COMPACT_STRING_LIMIT]
                    if not isinstance(entry, dict)
                    else self._compact_workspace_item(entry)
                    for entry in value[:8]
                ]
            elif isinstance(value, dict):
                compact[key] = {
                    str(child_key): (
                        str(child_value)[:_WORKSPACE_COMPACT_STRING_LIMIT]
                        if not isinstance(child_value, (int, float, bool, type(None)))
                        else child_value
                    )
                    for child_key, child_value in list(value.items())[:8]
                    if str(child_key) in {"label", "value", "type", "source", "reason", "code"}
                }
        if not compact.get("itemId"):
            identity = str(item.get("itemId") or item.get("url") or item.get("path") or item.get("title") or "").strip()
            if identity:
                compact["itemId"] = identity[:_WORKSPACE_COMPACT_STRING_LIMIT]
        if not compact.get("title") and item.get("name"):
            compact["title"] = str(item.get("name"))[:_WORKSPACE_COMPACT_STRING_LIMIT]
        return compact

    def _compact_workspace_reason(self, reason: object) -> dict[str, Any] | None:
        if not isinstance(reason, dict):
            text = str(reason).strip()
            return {"detail": text[:_WORKSPACE_COMPACT_STRING_LIMIT]} if text else None
        compact: dict[str, Any] = {}
        for key in ("code", "label", "detail", "reason", "source", "type", "value"):
            value = str(reason.get(key) or "").strip()
            if value:
                compact[key] = value[:_WORKSPACE_COMPACT_STRING_LIMIT]
        score = reason.get("score")
        if isinstance(score, (int, float)):
            compact["score"] = round(float(score), 3)
        return compact or None

    def _compact_workspace_surface_link(self, link: object) -> dict[str, Any] | None:
        if not isinstance(link, dict):
            return None
        compact: dict[str, Any] = {}
        for key in ("sourceSurface", "targetSurface"):
            value = str(link.get(key) or "").strip()
            if value:
                compact[key] = value[:_WORKSPACE_COMPACT_STRING_LIMIT]
        reasons = link.get("reasons")
        if isinstance(reasons, list):
            compact_reasons = [
                compact_reason
                for compact_reason in (self._compact_workspace_reason(reason) for reason in reasons[:8])
                if compact_reason
            ]
            if compact_reasons:
                compact["reasons"] = compact_reasons
        return compact or None

    def _bounded_workspace_items(
        self,
        items: object,
        *,
        limit: int = WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT,
        query: str = "",
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_item_list(items)
        effective_limit = max(0, int(limit))
        displayed = [self._compact_workspace_item(item) for item in normalized[:effective_limit]]
        total_count = len(normalized)
        omitted_count = max(0, total_count - len(displayed))
        summary: dict[str, Any] = {
            "total_count": total_count,
            "displayed_count": len(displayed),
            "truncated": omitted_count > 0,
            "omitted_count": omitted_count,
            "limit": effective_limit,
        }
        if query:
            summary["query"] = query
        if filters:
            summary["filters"] = dict(filters)
        if omitted_count > 0:
            summary["continuation_token"] = f"offset:{len(displayed)}"
        return {"items": displayed, "summary": summary}

    def _cap_payload_list(
        self,
        payload: dict[str, Any],
        key: str,
        summary_key: str,
        *,
        limit: int = WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT,
    ) -> None:
        bounded = self._bounded_workspace_items(payload.get(key), limit=limit)
        payload[key] = bounded["items"]
        payload[summary_key] = bounded["summary"]

    def _compact_workspace_payload(
        self,
        workspace: WorkspaceRecord,
        *,
        limit: int = WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT,
    ) -> dict[str, Any]:
        if limit <= 0:
            return self._workspace_reference_payload(workspace)
        payload = workspace.to_dict()
        self._cap_payload_list(payload, "references", "referencesSummary", limit=limit)
        self._cap_payload_list(payload, "findings", "findingsSummary", limit=limit)
        self._cap_payload_list(payload, "sessionNotes", "sessionNotesSummary", limit=limit)
        return payload

    def _empty_workspace_list_summary(
        self,
        *,
        total_count: int,
        limit: int = 0,
    ) -> dict[str, Any]:
        return {
            "total_count": max(0, int(total_count)),
            "displayed_count": 0,
            "truncated": max(0, int(total_count)) > 0,
            "omitted_count": max(0, int(total_count)),
            "limit": max(0, int(limit)),
            "continuation_token": "offset:0" if total_count > 0 else "",
        }

    def _workspace_reference_payload(self, workspace: WorkspaceRecord) -> dict[str, Any]:
        return {
            "workspaceId": workspace.workspace_id,
            "name": workspace.name,
            "topic": workspace.topic,
            "summary": workspace.summary,
            "title": workspace.title,
            "status": workspace.status,
            "category": workspace.category,
            "templateKey": workspace.template_key,
            "templateSource": workspace.template_source,
            "problemDomain": workspace.problem_domain,
            "activeGoal": workspace.active_goal,
            "currentTaskState": workspace.current_task_state,
            "lastCompletedAction": workspace.last_completed_action,
            "lastSurfaceMode": workspace.last_surface_mode,
            "lastActiveModule": workspace.last_active_module,
            "lastActiveSection": workspace.last_active_section,
            "pendingNextSteps": list(workspace.pending_next_steps),
            "whereLeftOff": workspace.where_left_off,
            "pinned": workspace.pinned,
            "archived": workspace.archived,
            "archivedAt": workspace.archived_at,
            "lastSnapshotAt": workspace.last_snapshot_at,
            "tags": list(workspace.tags),
            "createdAt": workspace.created_at,
            "updatedAt": workspace.updated_at,
            "lastOpenedAt": workspace.last_opened_at,
            "referencesSummary": self._empty_workspace_list_summary(total_count=len(workspace.references)),
            "findingsSummary": self._empty_workspace_list_summary(total_count=len(workspace.findings)),
            "sessionNotesSummary": self._empty_workspace_list_summary(total_count=len(workspace.session_notes)),
            "detailLoadDeferred": True,
        }

    def _compact_continuity_payload(
        self,
        continuity: WorkspaceContinuitySnapshot,
        *,
        limit: int = WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT,
    ) -> dict[str, Any]:
        payload = continuity.to_dict()
        payload["activeItem"] = self._compact_workspace_item(payload.get("activeItem"))
        self._cap_payload_list(payload, "openedItems", "openedItemsSummary", limit=limit)
        self._cap_payload_list(payload, "references", "referencesSummary", limit=limit)
        self._cap_payload_list(payload, "findings", "findingsSummary", limit=limit)
        self._cap_payload_list(payload, "sessionNotes", "sessionNotesSummary", limit=limit)
        return payload

    def _compact_snapshot_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        compact = dict(payload) if isinstance(payload, dict) else {}
        workspace_payload = compact.get("workspace")
        if isinstance(workspace_payload, dict):
            for key, summary_key in (
                ("references", "referencesSummary"),
                ("findings", "findingsSummary"),
                ("sessionNotes", "sessionNotesSummary"),
            ):
                self._cap_payload_list(workspace_payload, key, summary_key, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)
        for key, summary_key in (
            ("opened_items", "openedItemsSummary"),
            ("references", "referencesSummary"),
            ("findings", "findingsSummary"),
            ("session_notes", "sessionNotesSummary"),
        ):
            if key in compact:
                bounded = self._bounded_workspace_items(compact.get(key), limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)
                compact[key] = bounded["items"]
                compact[summary_key] = bounded["summary"]
        continuity = compact.get("continuity")
        if isinstance(continuity, dict):
            for key, summary_key in (
                ("openedItems", "openedItemsSummary"),
                ("references", "referencesSummary"),
                ("findings", "findingsSummary"),
                ("sessionNotes", "sessionNotesSummary"),
            ):
                self._cap_payload_list(continuity, key, summary_key, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)
        if isinstance(compact.get("surface_content"), dict):
            compact["surface_content"] = self._normalize_surface_content(compact.get("surface_content"))
        compact["payloadGuardrails"] = self._payload_guardrail_metadata(compact)
        return compact

    def _payload_guardrail_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            payload_bytes = len(json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            payload_bytes = 0
        item_count = self._count_embedded_workspace_items(payload)
        truncated = self._contains_truncated_workspace_items(payload)
        reasons: list[str] = []
        if payload_bytes >= WORKSPACE_PAYLOAD_FAIL_BYTES:
            reasons.append("response_payload_over_fail_guardrail")
        elif payload_bytes >= WORKSPACE_PAYLOAD_WARN_BYTES:
            reasons.append("response_payload_over_warn_guardrail")
        if truncated:
            reasons.append("workspace_items_truncated")
        return {
            "response_json_bytes": payload_bytes,
            "workspace_item_count": item_count,
            "active_context_bytes": payload_bytes,
            "active_context_item_count": item_count,
            "truncated_workspace_items": truncated,
            "payload_guardrail_triggered": bool(reasons),
            "payload_guardrail_reason": ",".join(reasons),
            "warn_threshold_bytes": WORKSPACE_PAYLOAD_WARN_BYTES,
            "fail_threshold_bytes": WORKSPACE_PAYLOAD_FAIL_BYTES,
        }

    def _count_embedded_workspace_items(self, value: Any) -> int:
        if isinstance(value, dict):
            count = 0
            for key, item in value.items():
                if key in {"items", "opened_items", "openedItems", "references", "findings", "session_notes", "sessionNotes"} and isinstance(item, list):
                    count += len(item)
                    continue
                count += self._count_embedded_workspace_items(item)
            return count
        if isinstance(value, list):
            return sum(self._count_embedded_workspace_items(item) for item in value)
        return 0

    def _contains_truncated_workspace_items(self, value: Any) -> bool:
        if isinstance(value, dict):
            if bool(value.get("truncated")):
                return True
            return any(self._contains_truncated_workspace_items(item) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_truncated_workspace_items(item) for item in value)
        return False

    def _compact_context_payload(self, value: Any, *, depth: int = 0) -> Any:
        if depth > 5:
            return {"truncated": True, "reason": "max_context_depth"}
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key)
                if normalized_key in {"embedding", "vector", "raw", "content"}:
                    continue
                if normalized_key in {"items", "references", "findings", "sessionNotes", "session_notes", "openedItems", "opened_items"} and isinstance(item, list):
                    bounded = self._bounded_workspace_items(item, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)
                    compact[normalized_key] = bounded["items"]
                    compact[f"{normalized_key}Summary"] = bounded["summary"]
                    continue
                compact[normalized_key] = self._compact_context_payload(item, depth=depth + 1)
            return compact
        if isinstance(value, list):
            displayed = [self._compact_context_payload(item, depth=depth + 1) for item in value[:WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT]]
            if len(value) > WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT:
                displayed.append(
                    {
                        "truncated": True,
                        "total_count": len(value),
                        "displayed_count": WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
                        "omitted_count": len(value) - WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
                    }
                )
            return displayed
        if isinstance(value, str):
            return value[:_WORKSPACE_COMPACT_STRING_LIMIT]
        return value

    def capture_workspace_context(
        self,
        *,
        session_id: str,
        prompt: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
    ) -> None:
        context = workspace_context if isinstance(workspace_context, dict) else {}
        workspace_data = context.get("workspace") if isinstance(context.get("workspace"), dict) else {}
        opened_items = self._normalize_item_list(context.get("opened_items"))
        active_item = context.get("active_item") if isinstance(context.get("active_item"), dict) else {}
        if not workspace_data and not opened_items and not active_item and not self.session_state.get_active_workspace_id(session_id):
            return
        workspace = self._resolve_or_create_workspace(session_id=session_id, prompt=prompt, workspace_data=workspace_data)
        if workspace is None:
            return

        section = str(context.get("section", "")).strip().lower()
        template_key = str(workspace_data.get("templateKey") or workspace.template_key).strip().lower()
        template_source = str(workspace_data.get("templateSource") or workspace.template_source).strip().lower()
        problem_domain = str(
            workspace_data.get("problemDomain")
            or context.get("problem_domain")
            or workspace.problem_domain
            or self.session_state.get_active_context(session_id).get("current_problem_domain")
            or ""
        ).strip()
        template = self.templates.get(template_key) if template_key else None
        active_goal = str(workspace_data.get("activeGoal", workspace.active_goal or workspace.summary)).strip()
        current_status = str(
            workspace_data.get("currentStatus")
            or workspace.status
            or f"{surface_mode.strip().lower()}:{active_module.strip().lower()}"
        ).strip()
        pending_next_steps = self._normalize_string_list(
            workspace_data.get("pendingNextSteps")
            or self.session_state.get_active_posture(session_id).get("pending_next_steps")
            or workspace.pending_next_steps
            or self._derive_next_steps(prompt, active_item, opened_items)
        )
        likely_next = self._likely_next_bearing(
            pending_next_steps=pending_next_steps,
            active_item=active_item,
            opened_items=opened_items,
        )
        current_task_state = str(workspace_data.get("currentTaskState") or prompt or workspace.current_task_state).strip()
        last_completed_action = str(workspace_data.get("lastCompletedAction") or workspace.last_completed_action).strip()
        existing_surface_content = self._normalize_surface_content(
            workspace_data.get("surfaceContent") or context.get("surfaceContent")
        )
        references = self._normalize_item_list(
            workspace_data.get("references")
            or self._cluster_items(existing_surface_content, "references")
            or [item for item in opened_items if str(item.get("role", "")).lower() == "reference"]
            or workspace.references
        )
        findings = self._normalize_item_list(
            workspace_data.get("findings")
            or self._cluster_items(existing_surface_content, "findings")
            or workspace.findings
        )
        session_notes = self._normalize_item_list(
            workspace_data.get("sessionNotes")
            or self._cluster_items(existing_surface_content, "logbook")
            or workspace.session_notes
        )
        where_left_off = str(
            workspace_data.get("whereLeftOff")
            or self._build_where_left_off(
                workspace_name=workspace.name,
                active_goal=active_goal,
                last_completed_action=last_completed_action,
                pending_next_steps=pending_next_steps,
                active_item=active_item,
            )
        ).strip()

        workspace = self.repository.upsert_workspace(
            workspace_id=workspace.workspace_id,
            name=str(workspace_data.get("name", workspace.name)),
            topic=str(workspace_data.get("topic", workspace.topic)),
            summary=str(workspace_data.get("summary", workspace.summary)),
            title=str(workspace_data.get("title", workspace.title or workspace.name)),
            status=current_status,
            category=str(workspace_data.get("category", workspace.category or workspace.topic)),
            template_key=template_key,
            template_source=template_source,
            problem_domain=problem_domain,
            active_goal=active_goal,
            current_task_state=current_task_state,
            last_completed_action=last_completed_action,
            last_surface_mode=surface_mode.strip().lower(),
            last_active_module=active_module.strip().lower(),
            last_active_section=section,
            pending_next_steps=pending_next_steps,
            references=references,
            findings=findings,
            session_notes=session_notes,
            where_left_off=where_left_off,
            pinned=bool(workspace_data.get("pinned", workspace.pinned)),
            archived=bool(workspace_data.get("archived", workspace.archived)),
            archived_at=str(workspace_data.get("archivedAt", workspace.archived_at)),
            last_snapshot_at=workspace.last_snapshot_at,
            tags=self._normalize_string_list(workspace_data.get("tags") or workspace.tags),
        )

        for item in opened_items:
            self.repository.upsert_item(workspace.workspace_id, self._prepare_item(item, default_module=active_module))
        if active_item:
            self.repository.upsert_item(workspace.workspace_id, self._prepare_item(active_item, default_module=active_module))

        continuity = WorkspaceContinuitySnapshot(
            active_goal=active_goal,
            current_task_state=current_task_state,
            last_completed_action=last_completed_action,
            pending_next_steps=pending_next_steps,
            where_left_off=where_left_off,
            problem_domain=problem_domain,
            active_item=dict(active_item) if active_item else (opened_items[0] if opened_items else {}),
            opened_items=opened_items,
            references=references,
            findings=findings,
            session_notes=session_notes,
        )
        session_posture = WorkspaceSessionPosture(
            surface_mode=surface_mode.strip().lower() or "deck",
            active_module=active_module.strip().lower() or "chartroom",
            active_section=section or workspace.last_active_section or (template.default_section if template else "overview"),
            emphasis=list(template.emphasis) if template is not None else [],
            restored_from_saved_posture=False,
        )
        capabilities = self._workspace_capabilities(restore_saved_posture=bool(workspace.last_snapshot_at))
        surface_content = existing_surface_content or self._surface_content_from_workspace_state(
            workspace=workspace,
            continuity=continuity,
            session_posture=session_posture,
            opened_items=opened_items,
            active_item=active_item,
            likely_next=likely_next,
        )
        self.memory.sync_workspace_memory(
            workspace,
            continuity=continuity,
            session_posture=session_posture,
            opened_items=opened_items,
            source_surface="capture_workspace_context",
        )
        bounded_opened_items = self._bounded_workspace_items(
            opened_items,
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_references = self._bounded_workspace_items(
            references,
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_findings = self._bounded_workspace_items(
            findings,
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_session_notes = self._bounded_workspace_items(
            session_notes,
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_surface_content = self._normalize_surface_content(surface_content)
        self.session_state.set_active_workspace_id(session_id, workspace.workspace_id)
        self.session_state.set_active_posture(
            session_id,
            {
                "workspace": self._workspace_view_payload(
                    workspace,
                    likely_next=likely_next,
                    where_left_off=where_left_off,
                    pending_next_steps=pending_next_steps,
                    continuity=continuity,
                    session_posture=session_posture,
                    capabilities=capabilities,
                    surface_content=bounded_surface_content,
                ),
                "surface_mode": surface_mode,
                "active_module": active_module,
                "section": section,
                "opened_items": bounded_opened_items,
                "active_item": self._compact_workspace_item(active_item if active_item else (opened_items[0] if opened_items else {})),
                "active_goal": active_goal,
                "current_task_state": current_task_state,
                "last_completed_action": last_completed_action,
                "pending_next_steps": pending_next_steps,
                "references": bounded_references,
                "findings": bounded_findings,
                "session_notes": bounded_session_notes,
                "where_left_off": where_left_off,
                "likely_next": likely_next,
                "template_key": template_key,
                "template_source": template_source,
                "problem_domain": problem_domain,
                "continuity": self._compact_continuity_payload(continuity, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT),
                "session_posture": session_posture.to_dict(),
                "capabilities": capabilities,
                "surface_content": bounded_surface_content,
            },
        )

    def assemble_workspace(self, query: str, *, session_id: str, compact: bool = False) -> dict[str, Any]:
        subspans = _empty_workspace_subspans()
        state_started = perf_counter()
        assembly_focus = self._resolve_assembly_focus(session_id=session_id, query=query)
        topic = str(assembly_focus.get("topic") or "current work")
        workspace = assembly_focus.get("workspace")
        if not isinstance(workspace, WorkspaceRecord):
            workspace = self._ensure_workspace(topic)
        _add_workspace_subspan(subspans, "workspace_state_load_ms", state_started)
        if compact:
            return self._finalize_workspace_fast_summary(
                workspace=workspace,
                query=query,
                session_id=session_id,
                activity_type="assemble",
                summary=self.persona.report(f"Started a compact workspace summary for {workspace.topic or workspace.name}."),
                route_handler_subspans=subspans,
            )
        template, template_source, template_confidence, template_reasons = self._resolve_template(
            query=query,
            topic=topic,
            workspace=workspace,
            active_context=self.session_state.get_active_context(session_id),
            allow_generic=True,
        )
        index_started = perf_counter()
        plan = self._build_workspace_plan(
            query=query,
            session_id=session_id,
            workspace=workspace,
            template=template,
            template_source=template_source,
            template_confidence=template_confidence,
            template_reasons=template_reasons,
            resume_context=WorkspaceResumeContext(
                source="template_defaults",
                basis="template defaults",
                used_saved_posture=False,
                used_template_defaults=True,
                restored_fields=[],
                limitations=["No saved posture existed yet, so template defaults were used."],
            ),
        )
        _add_workspace_subspan(subspans, "workspace_index_or_search_ms", index_started)
        return self._finalize_workspace_plan(
            plan=plan,
            query=query,
            session_id=session_id,
            activity_type="assemble",
            description=f"Assembled workspace for {topic}.",
            bearing_title=self._workspace_bearing_title("assemble", template=template, query=query, workspace=plan.workspace),
            summary=self._workspace_summary("assemble", query=query, plan=plan),
            route_handler_subspans=subspans,
        )

    def restore_workspace(self, query: str, *, session_id: str, compact: bool = False) -> dict[str, Any]:
        selection = self._select_workspace_for_restore(query, session_id=session_id)
        ambiguous = selection.get("ambiguous") if isinstance(selection, dict) else None
        if isinstance(ambiguous, list) and len(ambiguous) >= 2:
            names = [str(item.get("name", "workspace")).strip() for item in ambiguous[:2]]
            return {
                "summary": self.persona.clarification(f"Do you mean {names[0]} or {names[1]}"),
                "workspace": {},
                "items": [],
                "action": {
                    "type": "clarify",
                    "options": names,
                },
            }
        workspace = selection.get("workspace") if isinstance(selection, dict) else None
        if workspace is None:
            return self.assemble_workspace(query, session_id=session_id, compact=compact)
        if workspace.archived:
            workspace = self.repository.set_archived(workspace.workspace_id, False) or workspace
        if compact:
            return self._finalize_workspace_fast_summary(
                workspace=workspace,
                query=query,
                session_id=session_id,
                activity_type="restore",
                summary=self.persona.report(f"Restored compact workspace bearings for {workspace.name}."),
            )
        snapshot = self.repository.get_latest_snapshot(workspace.workspace_id)
        payload = snapshot.payload if snapshot is not None else {}
        template, template_source, template_confidence, template_reasons = self._resolve_template(
            query=query,
            topic=workspace.topic,
            workspace=workspace,
            active_context=self.session_state.get_active_context(session_id),
            allow_generic=True,
        )
        resume_context = self._resume_context_from_restore(
            workspace=workspace,
            snapshot_payload=payload,
            basis=str(selection.get("basis") or "retained workspace memory"),
        )
        plan = self._build_workspace_plan(
            query=query,
            session_id=session_id,
            workspace=workspace,
            template=template,
            template_source=template_source,
            template_confidence=template_confidence,
            template_reasons=template_reasons,
            resume_context=resume_context,
            snapshot_payload=payload,
        )
        return self._finalize_workspace_plan(
            plan=plan,
            query=query,
            session_id=session_id,
            activity_type="restore",
            description=f"Restored workspace {workspace.name}.",
            bearing_title=self._workspace_bearing_title("restore", template=template, query=query, workspace=plan.workspace),
            summary=self._workspace_summary("restore", query=query, plan=plan),
        )

    def remember_actions(
        self,
        *,
        session_id: str,
        prompt: str,
        actions: list[dict[str, Any]],
        surface_mode: str,
        active_module: str,
    ) -> None:
        if not actions:
            return
        active_id = self.session_state.get_active_workspace_id(session_id)
        posture = self.session_state.get_active_posture(session_id)
        for action in actions:
            action_type = str(action.get("type", "")).strip().lower()
            if action_type == "workspace_restore":
                workspace_data = action.get("workspace", {})
                if not isinstance(workspace_data, dict):
                    continue
                continuity_payload = workspace_data.get("continuity", {})
                if not isinstance(continuity_payload, dict):
                    continuity_payload = {}
                session_posture_payload = workspace_data.get("sessionPosture", {})
                if not isinstance(session_posture_payload, dict):
                    session_posture_payload = {}
                surface_content = self._normalize_surface_content(workspace_data.get("surfaceContent"))
                workspace = self.repository.upsert_workspace(
                    workspace_id=str(workspace_data.get("workspaceId") or ""),
                    name=str(workspace_data.get("name", "Recovered Workspace")),
                    topic=str(workspace_data.get("topic", workspace_data.get("name", "workspace"))),
                    summary=str(workspace_data.get("summary", "")),
                    title=str(workspace_data.get("title", workspace_data.get("name", "Recovered Workspace"))),
                    status=str(workspace_data.get("status", "")),
                    category=str(workspace_data.get("category", "")),
                    template_key=str(workspace_data.get("templateKey", "")),
                    template_source=str(workspace_data.get("templateSource", "")),
                    problem_domain=str(workspace_data.get("problemDomain", continuity_payload.get("problemDomain", ""))),
                    active_goal=str(workspace_data.get("activeGoal", continuity_payload.get("activeGoal", ""))),
                    current_task_state=str(workspace_data.get("currentTaskState", continuity_payload.get("currentTaskState", prompt))),
                    last_completed_action=str(
                        workspace_data.get("lastCompletedAction", continuity_payload.get("lastCompletedAction", "Restored retained workspace bearings."))
                    ),
                    last_surface_mode=str(workspace_data.get("lastSurfaceMode", session_posture_payload.get("surfaceMode", surface_mode))),
                    last_active_module=str(workspace_data.get("lastActiveModule", session_posture_payload.get("activeModule", active_module))),
                    last_active_section=str(workspace_data.get("lastActiveSection", session_posture_payload.get("activeSection", action.get("section", "")))),
                    pending_next_steps=self._normalize_string_list(workspace_data.get("pendingNextSteps")),
                    references=self._normalize_item_list(workspace_data.get("references")),
                    findings=self._normalize_item_list(workspace_data.get("findings")),
                    session_notes=self._normalize_item_list(workspace_data.get("sessionNotes")),
                    where_left_off=str(workspace_data.get("whereLeftOff", "")),
                    tags=self._normalize_string_list(workspace_data.get("tags")),
                )
                self.session_state.set_active_workspace_id(session_id, workspace.workspace_id)
                items = self._normalize_item_list(action.get("items"))
                for item in items:
                    self.repository.upsert_item(workspace.workspace_id, item)
                posture = {
                    "workspace": self._workspace_view_payload(
                        workspace,
                        likely_next=str(workspace_data.get("likelyNext", "")),
                        where_left_off=str(workspace_data.get("whereLeftOff", "")),
                        pending_next_steps=workspace.pending_next_steps,
                        continuity=WorkspaceContinuitySnapshot(
                            active_goal=str(workspace_data.get("activeGoal", continuity_payload.get("activeGoal", ""))),
                            current_task_state=str(workspace_data.get("currentTaskState", continuity_payload.get("currentTaskState", prompt))),
                            last_completed_action=str(
                                workspace_data.get("lastCompletedAction", continuity_payload.get("lastCompletedAction", "Restored retained workspace bearings."))
                            ),
                            pending_next_steps=workspace.pending_next_steps,
                            where_left_off=str(workspace_data.get("whereLeftOff", continuity_payload.get("whereLeftOff", ""))),
                            problem_domain=str(workspace_data.get("problemDomain", continuity_payload.get("problemDomain", ""))),
                            active_item=next(
                                (item for item in items if item.get("itemId") == action.get("active_item_id")),
                                items[0] if items else {},
                            ),
                            opened_items=items,
                            references=workspace.references,
                            findings=workspace.findings,
                            session_notes=workspace.session_notes,
                        ),
                        session_posture=WorkspaceSessionPosture(
                            surface_mode=str(session_posture_payload.get("surfaceMode", surface_mode)),
                            active_module=str(session_posture_payload.get("activeModule", action.get("module", active_module))),
                            active_section=str(session_posture_payload.get("activeSection", action.get("section", ""))),
                            emphasis=self._normalize_string_list(session_posture_payload.get("emphasis")),
                            restored_from_saved_posture=bool(session_posture_payload.get("restoredFromSavedPosture")),
                        ),
                        capabilities=dict(workspace_data.get("capabilities")) if isinstance(workspace_data.get("capabilities"), dict) else None,
                        surface_content=surface_content,
                        resume_context=WorkspaceResumeContext(
                            source=str(workspace_data.get("resumeContext", {}).get("source", "workspace_memory"))
                            if isinstance(workspace_data.get("resumeContext"), dict)
                            else "workspace_memory",
                            basis=str(workspace_data.get("resumeContext", {}).get("basis", "retained workspace memory"))
                            if isinstance(workspace_data.get("resumeContext"), dict)
                            else "retained workspace memory",
                            used_saved_posture=bool(
                                workspace_data.get("resumeContext", {}).get("usedSavedPosture")
                                if isinstance(workspace_data.get("resumeContext"), dict)
                                else False
                            ),
                            used_template_defaults=bool(
                                workspace_data.get("resumeContext", {}).get("usedTemplateDefaults", False)
                                if isinstance(workspace_data.get("resumeContext"), dict)
                                else False
                            ),
                            restored_fields=self._normalize_string_list(
                                workspace_data.get("resumeContext", {}).get("restoredFields")
                                if isinstance(workspace_data.get("resumeContext"), dict)
                                else []
                            ),
                            limitations=self._normalize_string_list(
                                workspace_data.get("resumeContext", {}).get("limitations")
                                if isinstance(workspace_data.get("resumeContext"), dict)
                                else []
                            ),
                        ),
                    ),
                    "surface_mode": str(session_posture_payload.get("surfaceMode", surface_mode)),
                    "active_module": str(session_posture_payload.get("activeModule", action.get("module", active_module))),
                    "section": str(session_posture_payload.get("activeSection", action.get("section", ""))).strip().lower(),
                    "opened_items": items,
                    "active_item": next(
                        (item for item in items if item.get("itemId") == action.get("active_item_id")),
                        items[0] if items else {},
                    ),
                    "active_goal": workspace.active_goal,
                    "current_task_state": workspace.current_task_state or prompt,
                    "last_completed_action": workspace.last_completed_action or "Restored retained workspace bearings.",
                    "pending_next_steps": workspace.pending_next_steps,
                    "references": workspace.references,
                    "findings": workspace.findings,
                    "session_notes": workspace.session_notes,
                    "where_left_off": workspace.where_left_off,
                    "likely_next": str(workspace_data.get("likelyNext", "")),
                    "template_key": workspace.template_key,
                    "template_source": workspace.template_source,
                    "problem_domain": workspace.problem_domain,
                    "continuity": dict(continuity_payload) if continuity_payload else {},
                    "session_posture": dict(session_posture_payload) if session_posture_payload else {},
                    "capabilities": dict(workspace_data.get("capabilities")) if isinstance(workspace_data.get("capabilities"), dict) else {},
                    "surface_content": surface_content,
                    "resume_context": dict(workspace_data.get("resumeContext")) if isinstance(workspace_data.get("resumeContext"), dict) else {},
                }
                self.session_state.set_active_posture(session_id, posture)
                active_id = workspace.workspace_id
                continue
            if action_type == "workspace_open":
                if not active_id:
                    workspace = self._ensure_workspace(self._extract_topic(prompt))
                    self.session_state.set_active_workspace_id(session_id, workspace.workspace_id)
                    active_id = workspace.workspace_id
                item = action.get("item")
                if isinstance(item, dict):
                    prepared_item = self._prepare_item(item, default_module=active_module)
                    self.repository.upsert_item(active_id, prepared_item)
                    self.repository.record_activity(
                        workspace_id=active_id,
                        session_id=session_id,
                        activity_type="open",
                        description=f"Held {prepared_item.get('title', 'item')} in the Deck.",
                        payload={"prompt": prompt},
                    )
                    posture["opened_items"] = self._merge_items(
                        posture.get("opened_items") if isinstance(posture.get("opened_items"), list) else [],
                        [prepared_item],
                    )
                    posture["active_item"] = dict(prepared_item)
                    posture["current_task_state"] = prompt
                    posture["last_completed_action"] = f"Held {prepared_item.get('title', 'item')} in the Deck."
        if posture:
            self.session_state.set_active_posture(session_id, posture)

    def active_workspace_summary(self, session_id: str) -> dict[str, Any]:
        posture = self.session_state.get_active_posture(session_id)
        workspace = self._workspace_from_posture(session_id, posture)
        if workspace is None:
            return {}
        items = self._normalize_item_list(posture.get("opened_items"))
        if not items:
            items = [item.to_action_item() for item in self.repository.list_items(workspace.workspace_id, limit=8)]
        active_item = posture.get("active_item") if isinstance(posture.get("active_item"), dict) else {}
        if not active_item:
            active_item = items[0] if items else {}
        pending_next_steps = self._normalize_string_list(posture.get("pending_next_steps") or workspace.pending_next_steps)
        where_left_off = str(posture.get("where_left_off") or workspace.where_left_off)
        continuity = self._continuity_from_posture(workspace, posture, items, active_item)
        session_posture = self._session_posture_from_posture(workspace, posture)
        surface_content = self._normalize_surface_content(posture.get("surface_content")) or self._surface_content_from_workspace_state(
            workspace=workspace,
            continuity=continuity,
            session_posture=session_posture,
            opened_items=items,
            active_item=active_item,
            likely_next=str(posture.get("likely_next") or ""),
        )
        capabilities = dict(posture.get("capabilities")) if isinstance(posture.get("capabilities"), dict) else self._workspace_capabilities(
            restore_saved_posture=bool(workspace.last_snapshot_at)
        )
        likely_next = str(posture.get("likely_next") or self._likely_next_bearing(
            pending_next_steps=pending_next_steps,
            active_item=active_item,
            opened_items=items,
        ))
        memory_context = self._workspace_memory_context(
            workspace,
            session_id=session_id,
            query=" ".join(
                part
                for part in [
                    workspace.topic,
                    workspace.active_goal,
                    where_left_off,
                ]
                if part
            ),
        )
        bounded_items = self._bounded_workspace_items(items, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)["items"]
        bounded_references = self._bounded_workspace_items(
            self._normalize_item_list(posture.get("references") or workspace.references),
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_findings = self._bounded_workspace_items(
            self._normalize_item_list(posture.get("findings") or workspace.findings),
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_session_notes = self._bounded_workspace_items(
            self._normalize_item_list(posture.get("session_notes") or workspace.session_notes),
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_surface_content = self._normalize_surface_content(surface_content)
        bounded_active_item = self._compact_workspace_item(active_item)
        return {
            "workspace": self._workspace_view_payload(
                workspace,
                likely_next=likely_next,
                where_left_off=where_left_off,
                pending_next_steps=pending_next_steps,
                continuity=continuity,
                session_posture=session_posture,
                capabilities=capabilities,
                surface_content=bounded_surface_content,
            ),
            "opened_items": bounded_items,
            "active_item": bounded_active_item,
            "active_goal": str(posture.get("active_goal") or workspace.active_goal),
            "current_task_state": str(posture.get("current_task_state") or workspace.current_task_state),
            "last_completed_action": str(posture.get("last_completed_action") or workspace.last_completed_action),
            "pending_next_steps": pending_next_steps,
            "where_left_off": where_left_off,
            "likely_next": likely_next,
            "references": bounded_references,
            "findings": bounded_findings,
            "session_notes": bounded_session_notes,
            "surface_content": bounded_surface_content,
            "memoryContext": memory_context,
            "action": {
                "type": "workspace_restore",
                "target": "deck",
                "module": str(posture.get("active_module", "chartroom")),
                "section": str(posture.get("section", "overview")),
                "workspace": self._workspace_view_payload(
                    workspace,
                    likely_next=likely_next,
                    where_left_off=where_left_off,
                    pending_next_steps=pending_next_steps,
                    continuity=continuity,
                    session_posture=session_posture,
                    capabilities=capabilities,
                    surface_content=bounded_surface_content,
                ),
                "items": bounded_items,
                "active_item_id": str(bounded_active_item.get("itemId", "")) if bounded_active_item else "",
            },
        }

    def active_workspace_summary_compact(self, session_id: str) -> dict[str, Any]:
        posture = self.session_state.get_active_posture(session_id)
        workspace = self._workspace_from_posture(session_id, posture)
        if workspace is None:
            return {}
        items = self._normalize_item_list(posture.get("opened_items"))
        if not items:
            items = [
                item.to_action_item()
                for item in self.repository.list_items(workspace.workspace_id, limit=2)
            ]
        active_item = posture.get("active_item") if isinstance(posture.get("active_item"), dict) else {}
        if not active_item and items:
            active_item = items[0]
        pending_next_steps = self._normalize_string_list(posture.get("pending_next_steps") or workspace.pending_next_steps)
        where_left_off = str(posture.get("where_left_off") or workspace.where_left_off)
        likely_next = str(
            posture.get("likely_next")
            or self._likely_next_bearing(
                pending_next_steps=pending_next_steps,
                active_item=active_item,
                opened_items=items,
            )
        )
        bounded_items = self._bounded_workspace_items(items, limit=2)
        bounded_references = self._bounded_workspace_items(
            self._normalize_item_list(posture.get("references") or workspace.references),
            limit=0,
        )
        workspace_payload = self._compact_workspace_payload(workspace, limit=0)
        workspace_payload["pendingNextSteps"] = list(pending_next_steps)
        workspace_payload["whereLeftOff"] = where_left_off
        workspace_payload["summary"] = where_left_off or workspace.summary
        workspace_payload["likelyNext"] = likely_next
        workspace_payload["openedItemsSummary"] = bounded_items["summary"]
        workspace_payload["referencesSummary"] = bounded_references["summary"]
        workspace_payload["capabilities"] = (
            dict(posture.get("capabilities")) if isinstance(posture.get("capabilities"), dict) else self._workspace_capabilities(
                restore_saved_posture=bool(workspace.last_snapshot_at)
            )
        )
        workspace_payload["detailLoadDeferred"] = True
        workspace_payload["workspaceSummaryCompact"] = {
            "workspaceId": workspace.workspace_id,
            "name": workspace.name,
            "topic": workspace.topic,
            "openedItemCount": bounded_items["summary"]["total_count"],
            "referenceCount": bounded_references["summary"]["total_count"],
            "pendingNextStepCount": len(pending_next_steps),
            "detailLoadDeferred": True,
        }
        return {
            "workspace": workspace_payload,
            "workspace_summary_compact": dict(workspace_payload["workspaceSummaryCompact"]),
            "opened_items": bounded_items["items"],
            "openedItemsSummary": bounded_items["summary"],
            "active_item": self._compact_workspace_item(active_item),
            "active_goal": str(posture.get("active_goal") or workspace.active_goal),
            "current_task_state": str(posture.get("current_task_state") or workspace.current_task_state),
            "last_completed_action": str(posture.get("last_completed_action") or workspace.last_completed_action),
            "pending_next_steps": pending_next_steps,
            "where_left_off": where_left_off,
            "likely_next": likely_next,
            "references": bounded_references["items"],
            "referencesSummary": bounded_references["summary"],
            "detail_load_deferred": True,
            "action": {
                "type": "workspace_restore",
                "target": "deck",
                "module": str(posture.get("active_module", "chartroom")),
                "section": str(posture.get("section", "overview")),
                "workspace": workspace_payload,
                "items": bounded_items["items"],
                "active_item_id": str(self._compact_workspace_item(active_item).get("itemId", "")) if active_item else "",
                "detail_load_deferred": True,
            },
        }

    def link_material_into_active_workspace(
        self,
        *,
        session_id: str,
        item: dict[str, Any],
        target_surface: str,
        reasons: list[WorkspaceInclusionReason] | list[dict[str, Any]] | None = None,
        source_surface: str = "environment",
        activity_description: str = "",
        workspace_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary = workspace_summary or self.active_workspace_summary(session_id)
        workspace_payload = summary.get("workspace") if isinstance(summary.get("workspace"), dict) else {}
        if not workspace_payload:
            return {"workspace": {}, "action": {}, "already_linked": False}

        target = str(target_surface or "references").strip().lower() or "references"
        posture = self.session_state.get_active_posture(session_id)
        surface_content = self._normalize_surface_content(summary.get("surface_content") or workspace_payload.get("surfaceContent"))
        prepared = self._prepare_item(
            dict(item),
            default_module=str(item.get("module") or ("browser" if item.get("url") else "files") or "chartroom"),
        )
        prepared["section"] = target
        normalized_reasons = self._normalize_workspace_link_reasons(reasons)
        if normalized_reasons:
            prepared["inclusionReasons"] = normalized_reasons
            prepared["surfaceLinks"] = [
                {
                    "sourceSurface": source_surface,
                    "targetSurface": target,
                    "reasons": list(normalized_reasons),
                }
            ]

        existing_cluster = surface_content.get(target, {})
        existing_items = self._normalize_item_list(existing_cluster.get("items"))
        already_linked = any(self._item_identity(candidate) == self._item_identity(prepared) for candidate in existing_items)
        cluster_payload = dict(existing_cluster)
        cluster_payload["items"] = self._merge_items(existing_items, [prepared])
        surface_content[target] = cluster_payload

        opened_items = self._normalize_item_list(summary.get("opened_items"))
        active_item = summary.get("active_item") if isinstance(summary.get("active_item"), dict) else {}
        references = self._normalize_item_list(summary.get("references"))
        findings = self._normalize_item_list(summary.get("findings"))
        session_notes = self._normalize_item_list(summary.get("session_notes"))

        if target == "references":
            references = self._merge_items(references, [prepared])
        elif target == "findings":
            findings = self._merge_items(findings, [prepared])
        elif target == "logbook":
            session_notes = self._merge_items(session_notes, [prepared])
        elif target == "opened-items":
            opened_items = self._merge_items(opened_items, [prepared])
            active_item = dict(prepared)

        updated_workspace_payload = {
            **workspace_payload,
            "references": references,
            "findings": findings,
            "sessionNotes": session_notes,
            "surfaceContent": surface_content,
        }
        self.capture_workspace_context(
            session_id=session_id,
            prompt=activity_description or f"Linked {prepared.get('title', 'material')} into the workspace.",
            surface_mode=str(posture.get("surface_mode", "deck")) or "deck",
            active_module=str(posture.get("active_module", "chartroom")) or "chartroom",
            workspace_context={
                "workspace": updated_workspace_payload,
                "module": str(posture.get("active_module", "chartroom")) or "chartroom",
                "section": str(posture.get("section", target)) or target,
                "opened_items": opened_items,
                "active_item": active_item,
            },
        )

        active_workspace_id = self.session_state.get_active_workspace_id(session_id)
        if active_workspace_id:
            self.repository.record_activity(
                workspace_id=active_workspace_id,
                session_id=session_id,
                activity_type="link_material",
                description=activity_description or f"Linked {prepared.get('title', 'material')} into {target}.",
                payload={
                    "target_surface": target,
                    "source_surface": source_surface,
                    "item": dict(prepared),
                    "inclusion_reasons": list(normalized_reasons),
                },
            )

        module = str(posture.get("active_module", "chartroom")) or "chartroom"
        section = str(posture.get("section", target)) or target
        bounded_items = self._bounded_workspace_items(opened_items, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)["items"]
        bounded_active_item = self._compact_workspace_item(active_item)
        return {
            "workspace": updated_workspace_payload,
            "action": {
                "type": "workspace_restore",
                "target": "deck",
                "module": module,
                "section": section,
                "workspace": updated_workspace_payload,
                "items": bounded_items,
                "active_item_id": str(bounded_active_item.get("itemId", "")) if bounded_active_item else "",
            },
            "already_linked": already_linked,
        }

    def clear_workspace(self, *, session_id: str) -> dict[str, Any]:
        posture = self.session_state.get_active_posture(session_id)
        workspace = self._workspace_from_posture(session_id, posture)
        if workspace is None:
            return {"summary": "No active workspace.", "workspace": {}}

        if posture:
            self._save_snapshot_from_posture(session_id=session_id, workspace=workspace, posture=posture)
        self.repository.record_activity(
            workspace_id=workspace.workspace_id,
            session_id=session_id,
            activity_type="clear",
            description=f"Cleared active workspace {workspace.name}.",
            payload={},
        )
        self.session_state.set_active_workspace_id(session_id, None)
        self.session_state.clear_active_posture(session_id)
        summary = self.persona.confirmation("Cleared active workspace.")
        return {
            "summary": summary,
            "workspace": self._workspace_view_payload(workspace),
            "action": {
                "type": "workspace_clear",
                "workspace_id": workspace.workspace_id,
            },
        }

    def save_workspace(self, *, session_id: str, compact: bool = False) -> dict[str, Any]:
        subspans = _empty_workspace_subspans()
        state_started = perf_counter()
        posture = self.session_state.get_active_posture(session_id)
        workspace = self._workspace_from_posture(session_id, posture)
        if workspace is None:
            workspace = self._ensure_workspace("current work")
            posture = {
                "workspace": workspace.to_dict(),
                "active_goal": workspace.summary or "Hold the current mission state.",
                "opened_items": [],
                "active_item": {},
                "pending_next_steps": [],
            }
            self.session_state.set_active_workspace_id(session_id, workspace.workspace_id)
            self.session_state.set_active_posture(session_id, posture)
        _add_workspace_subspan(subspans, "workspace_state_load_ms", state_started)
        save_started = perf_counter()
        snapshot = self._save_snapshot_from_posture(session_id=session_id, workspace=workspace, posture=posture)
        _add_workspace_subspan(subspans, "workspace_save_write_ms", save_started)
        db_started = perf_counter()
        workspace = self.repository.get_workspace(workspace.workspace_id) or workspace
        _add_workspace_subspan(subspans, "workspace_db_query_ms", db_started)
        event_started = perf_counter()
        self.repository.record_activity(
            workspace_id=workspace.workspace_id,
            session_id=session_id,
            activity_type="save",
            description=f"Saved workspace {workspace.name}.",
            payload={"snapshot_id": snapshot.snapshot_id},
        )
        _add_workspace_subspan(subspans, "workspace_event_emit_ms", event_started)
        dto_started = perf_counter()
        summary = self.persona.confirmation(
            f"Saved {workspace.name} and secured the current bearing, opened items, and next steps."
        )
        snapshot_payload = snapshot.to_dict()
        snapshot_payload["payload"] = (
            {
                "workspaceId": workspace.workspace_id,
                "workspaceName": workspace.name,
                "detailLoadDeferred": True,
                "openedItemsSummary": self._bounded_workspace_items(posture.get("opened_items"), limit=0)["summary"],
            }
            if compact
            else self._compact_snapshot_payload(snapshot.payload)
        )
        response = {
            "summary": summary,
            "workspace": self._compact_workspace_payload(workspace, limit=0) if compact else self._workspace_view_payload(workspace),
            "snapshot": snapshot_payload,
            "detail_load_deferred": bool(compact),
        }
        if compact:
            response["workspace"]["detailLoadDeferred"] = True
        _add_workspace_subspan(subspans, "workspace_dto_build_ms", dto_started)
        response["payloadGuardrails"] = self._payload_guardrail_metadata(response)
        response["debug"] = {"route_handler_subspans": subspans}
        return response

    def archive_workspace(self, *, session_id: str, query: str | None = None, compact: bool = False) -> dict[str, Any]:
        selection = self._select_workspace_for_restore(query or "current workspace", session_id=session_id)
        workspace = selection.get("workspace") if isinstance(selection, dict) else None
        if workspace is None:
            return {"summary": self.persona.error("no workspace is currently held on watch"), "workspace": {}}
        posture = self.session_state.get_active_posture(session_id)
        posture_workspace = self._posture_workspace_payload(posture)
        if posture and str(posture_workspace.get("workspaceId", "")).strip() == workspace.workspace_id:
            self._save_snapshot_from_posture(session_id=session_id, workspace=workspace, posture=posture)
        archived = self.repository.set_archived(workspace.workspace_id, True) or workspace
        self.repository.record_activity(
            workspace_id=workspace.workspace_id,
            session_id=session_id,
            activity_type="archive",
            description=f"Archived workspace {workspace.name}.",
            payload={},
        )
        if self.session_state.get_active_workspace_id(session_id) == workspace.workspace_id:
            self.session_state.set_active_workspace_id(session_id, None)
            self.session_state.clear_active_posture(session_id)
        summary = self.persona.confirmation(f"Archived {archived.name} and struck it from the active watch.")
        payload = self._compact_workspace_payload(archived, limit=0) if compact else self._workspace_view_payload(archived)
        if compact:
            payload["detailLoadDeferred"] = True
        return {"summary": summary, "workspace": payload, "detail_load_deferred": bool(compact)}

    def rename_workspace(self, *, session_id: str, new_name: str, compact: bool = False) -> dict[str, Any]:
        subspans = _empty_workspace_subspans()
        state_started = perf_counter()
        workspace = self._workspace_from_posture(session_id, self.session_state.get_active_posture(session_id))
        if workspace is None:
            return {"summary": self.persona.error("no active workspace is available to rename"), "workspace": {}}
        _add_workspace_subspan(subspans, "workspace_state_load_ms", state_started)
        db_started = perf_counter()
        renamed = self.repository.rename_workspace(workspace.workspace_id, new_name) or workspace
        _add_workspace_subspan(subspans, "workspace_db_query_ms", db_started)
        dto_started = perf_counter()
        posture = self.session_state.get_active_posture(session_id)
        if posture:
            posture["workspace"] = self._compact_workspace_payload(renamed, limit=0) if compact else self._workspace_view_payload(renamed)
            if compact and isinstance(posture["workspace"], dict):
                posture["workspace"]["detailLoadDeferred"] = True
            self.session_state.set_active_posture(session_id, posture)
        response = {
            "summary": self.persona.confirmation(f"Renamed the active workspace to {renamed.name}."),
            "workspace": self._compact_workspace_payload(renamed, limit=0) if compact else self._workspace_view_payload(renamed),
            "detail_load_deferred": bool(compact),
        }
        if compact:
            response["workspace"]["detailLoadDeferred"] = True
        _add_workspace_subspan(subspans, "workspace_dto_build_ms", dto_started)
        response["debug"] = {"route_handler_subspans": subspans}
        return response

    def tag_workspace(self, *, session_id: str, tags: list[str], compact: bool = False) -> dict[str, Any]:
        subspans = _empty_workspace_subspans()
        state_started = perf_counter()
        workspace = self._workspace_from_posture(session_id, self.session_state.get_active_posture(session_id))
        if workspace is None:
            return {"summary": self.persona.error("no active workspace is available to tag"), "workspace": {}}
        _add_workspace_subspan(subspans, "workspace_state_load_ms", state_started)
        db_started = perf_counter()
        tagged = self.repository.set_tags(workspace.workspace_id, tags) or workspace
        _add_workspace_subspan(subspans, "workspace_db_query_ms", db_started)
        dto_started = perf_counter()
        posture = self.session_state.get_active_posture(session_id)
        if posture:
            posture["workspace"] = self._compact_workspace_payload(tagged, limit=0) if compact else self._workspace_view_payload(tagged)
            if compact and isinstance(posture["workspace"], dict):
                posture["workspace"]["detailLoadDeferred"] = True
            self.session_state.set_active_posture(session_id, posture)
        response = {
            "summary": self.persona.confirmation(
                f"Tagged {tagged.name} with {', '.join(tagged.tags) if tagged.tags else 'no additional bearings'}."
            ),
            "workspace": self._compact_workspace_payload(tagged, limit=0) if compact else self._workspace_view_payload(tagged),
            "detail_load_deferred": bool(compact),
        }
        if compact:
            response["workspace"]["detailLoadDeferred"] = True
        _add_workspace_subspan(subspans, "workspace_dto_build_ms", dto_started)
        response["debug"] = {"route_handler_subspans": subspans}
        return response

    def list_workspaces(
        self,
        *,
        session_id: str,
        query: str = "",
        include_archived: bool = False,
        archived_only: bool = False,
        limit: int = 8,
        compact: bool = False,
    ) -> dict[str, Any]:
        del session_id
        items = (
            self.repository.search_workspaces(query, limit=limit, include_archived=include_archived, archived_only=archived_only)
            if query.strip()
            else self.repository.list_workspaces(limit=limit, include_archived=include_archived, archived_only=archived_only)
        )
        return {
            "summary": self.persona.report(
                f"Holding {len(items)} {'archived ' if archived_only else ''}workspace bearing{'s' if len(items) != 1 else ''}."
            ),
            "workspaces": [self._compact_workspace_payload(item, limit=0) if compact else item.to_dict() for item in items],
            "detail_load_deferred": bool(compact),
            "workspace_summary_compact": {
                "total_count": len(items),
                "displayed_count": len(items),
                "archived_only": archived_only,
                "include_archived": include_archived,
                "detailLoadDeferred": bool(compact),
            },
        }

    def where_we_left_off(self, *, session_id: str, compact: bool = False) -> dict[str, Any]:
        posture = self.session_state.get_active_posture(session_id)
        workspace = self._workspace_from_posture(session_id, posture)
        if workspace is None:
            return {"summary": self.persona.report("No active workspace bearing is currently secured."), "workspace": {}}
        where_left_off = str(posture.get("where_left_off") or workspace.where_left_off).strip()
        if not where_left_off:
            where_left_off = self._build_where_left_off(
                workspace_name=workspace.name,
                active_goal=str(posture.get("active_goal") or workspace.active_goal),
                last_completed_action=str(posture.get("last_completed_action") or workspace.last_completed_action),
                pending_next_steps=self._normalize_string_list(posture.get("pending_next_steps") or workspace.pending_next_steps),
                active_item=posture.get("active_item") if isinstance(posture.get("active_item"), dict) else {},
            )
        memory_context = {} if compact else self._workspace_memory_context(
            workspace,
            session_id=session_id,
            query=where_left_off,
        )
        workspace_payload = self._compact_workspace_payload(workspace, limit=0) if compact else self._workspace_view_payload(workspace)
        if compact:
            workspace_payload["detailLoadDeferred"] = True
        return {
            "summary": self.persona.report(where_left_off),
            "workspace": workspace_payload,
            "next_steps": self._normalize_string_list(posture.get("pending_next_steps") or workspace.pending_next_steps),
            "memory": memory_context,
            "detail_load_deferred": bool(compact),
        }

    def next_steps(self, *, session_id: str, compact: bool = False) -> dict[str, Any]:
        posture = self.session_state.get_active_posture(session_id)
        workspace = self._workspace_from_posture(session_id, posture)
        if workspace is None:
            return {"summary": self.persona.report("No active workspace bearing is currently secured."), "next_steps": []}
        next_steps = self._normalize_string_list(posture.get("pending_next_steps") or workspace.pending_next_steps)
        if not next_steps:
            next_steps = self._derive_next_steps(
                str(posture.get("current_task_state") or workspace.current_task_state),
                posture.get("active_item") if isinstance(posture.get("active_item"), dict) else {},
                posture.get("opened_items") if isinstance(posture.get("opened_items"), list) else [],
            )
        memory_context = {} if compact else self._workspace_memory_context(
            workspace,
            session_id=session_id,
            query=" ".join(next_steps[:3]) or workspace.where_left_off or workspace.summary,
        )
        workspace_payload = self._compact_workspace_payload(workspace, limit=0) if compact else self._workspace_view_payload(workspace)
        if compact:
            workspace_payload["detailLoadDeferred"] = True
        return {
            "summary": self.persona.report(
                f"Next bearings for {workspace.name}: " + "; ".join(next_steps[:3]) if next_steps else f"{workspace.name} is clear of pending next steps."
            ),
            "workspace": workspace_payload,
            "next_steps": next_steps,
            "memory": memory_context,
            "detail_load_deferred": bool(compact),
        }

    def link_note_to_active_workspace(self, *, session_id: str, note_id: str, workspace_id: str = "") -> None:
        workspace_id = workspace_id.strip() or (self.session_state.get_active_workspace_id(session_id) or "")
        if workspace_id:
            self.repository.link_note(workspace_id, note_id)

    def _ensure_workspace(self, topic: str):
        matches = self.repository.search_workspaces(topic, limit=1, include_archived=True)
        if matches:
            return matches[0]
        name = " ".join(part.capitalize() for part in topic.split()) or "Recovered Workspace"
        return self.repository.upsert_workspace(name=name, topic=topic, summary=f"Workspace for {topic}.")

    def _resolve_or_create_workspace(
        self,
        *,
        session_id: str,
        prompt: str,
        workspace_data: dict[str, Any],
    ) -> WorkspaceRecord | None:
        workspace_id = str(workspace_data.get("workspaceId", "")).strip()
        if workspace_id:
            existing = self.repository.get_workspace(workspace_id)
            if existing is not None:
                return existing
        active_id = self.session_state.get_active_workspace_id(session_id)
        if active_id:
            existing = self.repository.get_workspace(active_id)
            if existing is not None:
                return existing
        name = str(workspace_data.get("name", "")).strip()
        topic = str(workspace_data.get("topic", "")).strip()
        summary = str(workspace_data.get("summary", "")).strip()
        if name or topic:
            return self.repository.upsert_workspace(
                workspace_id=workspace_id or None,
                name=name or "Recovered Workspace",
                topic=topic or self._extract_topic(prompt),
                summary=summary or f"Workspace for {topic or name or 'current work'}.",
            )
        if prompt.strip():
            return self._ensure_workspace(self._extract_topic(prompt))
        return None

    def _workspace_from_posture(self, session_id: str, posture: dict[str, Any]) -> WorkspaceRecord | None:
        workspace_payload = self._posture_workspace_payload(posture)
        workspace_id = str(workspace_payload.get("workspaceId", "")).strip()
        if not workspace_id:
            workspace_id = self.session_state.get_active_workspace_id(session_id) or ""
        if not workspace_id:
            return None
        return self.repository.get_workspace(workspace_id)

    def _select_workspace_for_restore(self, query: str, *, session_id: str) -> dict[str, Any]:
        lower = query.lower()
        if "where we left off" in lower or "continue" in lower or "current workspace" in lower or "this workspace" in lower:
            active_id = self.session_state.get_active_workspace_id(session_id)
            if active_id:
                active_workspace = self.repository.get_workspace(active_id)
                if active_workspace is not None:
                    return {"workspace": active_workspace, "basis": "the active watch"}
        topic = self._extract_topic(query)
        alias_match = self.session_state.resolve_alias("workspace", topic or query)
        candidates = self.repository.search_workspaces(topic, limit=8, include_archived=True)
        if not candidates:
            candidates = self.repository.list_workspaces(limit=12, include_archived=True)
        if not candidates:
            return {"workspace": None, "basis": ""}
        seen: set[str] = set()
        scored: list[tuple[float, WorkspaceRecord, list[str]]] = []
        if isinstance(alias_match, dict):
            workspace_id = str(alias_match.get("workspaceId", "")).strip()
            if workspace_id:
                alias_workspace = self.repository.get_workspace(workspace_id)
                if alias_workspace is not None:
                    candidates = [alias_workspace, *candidates]
        for candidate in candidates:
            if candidate.workspace_id in seen:
                continue
            seen.add(candidate.workspace_id)
            score, reasons = self._workspace_match_score(candidate, topic, query=query, alias_match=alias_match)
            scored.append((score, candidate, reasons))
        scored.sort(key=lambda item: item[0], reverse=True)
        top_score, top_workspace, top_reasons = scored[0]
        if top_score < 1.35:
            return {"workspace": None, "basis": ""}
        if len(scored) > 1:
            second_score, second_workspace, _ = scored[1]
            if self._needs_restore_clarification(top_score, second_score):
                return {
                    "workspace": None,
                    "basis": "",
                    "ambiguous": [
                        {"workspaceId": top_workspace.workspace_id, "name": top_workspace.name},
                        {"workspaceId": second_workspace.workspace_id, "name": second_workspace.name},
                    ],
                }
        return {"workspace": top_workspace, "basis": self._workspace_basis(top_reasons)}

    def _workspace_memory_context(
        self,
        workspace: WorkspaceRecord,
        *,
        session_id: str,
        query: str,
    ) -> dict[str, Any]:
        result = self.memory.retrieve(
            MemoryQuery(
                query_id=str(uuid4()),
                retrieval_intent=MemoryRetrievalIntent.WORKSPACE_RESTORE.value,
                semantic_query_text=query,
                scope_constraints={
                    "workspace_id": workspace.workspace_id,
                    "session_id": session_id,
                },
                caller_subsystem="workspace",
            )
        )
        return self._compact_context_payload(result.to_dict())

    def _workspace_match_score(
        self,
        workspace: WorkspaceRecord,
        topic: str,
        *,
        query: str,
        alias_match: dict[str, object] | None,
    ) -> tuple[float, list[str]]:
        normalized_topic = normalize_lookup_phrase(topic or query)
        name = normalize_lookup_phrase(workspace.name)
        topic_name = normalize_lookup_phrase(workspace.topic)
        summary = normalize_lookup_phrase(workspace.summary)
        score = 0.0
        reasons: list[str] = []
        if isinstance(alias_match, dict) and str(alias_match.get("workspaceId", "")).strip() == workspace.workspace_id:
            score += 8.0
            reasons.append("learned alias memory")
        if normalized_topic and normalized_topic in {name, topic_name}:
            score += 5.0
            reasons.append("exact topic bearings")
        goal = normalize_lookup_phrase(workspace.active_goal)
        left_off = normalize_lookup_phrase(workspace.where_left_off)
        tags = normalize_lookup_phrase(" ".join(workspace.tags))
        pending = normalize_lookup_phrase(" ".join(workspace.pending_next_steps))
        similarity = max(
            fuzzy_ratio(normalized_topic, name),
            fuzzy_ratio(normalized_topic, topic_name),
            fuzzy_ratio(normalized_topic, summary),
            fuzzy_ratio(normalized_topic, goal),
            fuzzy_ratio(normalized_topic, left_off),
            fuzzy_ratio(normalized_topic, tags),
        )
        if similarity:
            score += similarity * 4.0
        overlap = max(
            token_overlap(normalized_topic, name),
            token_overlap(normalized_topic, topic_name),
            token_overlap(normalized_topic, summary),
            token_overlap(normalized_topic, goal),
            token_overlap(normalized_topic, left_off),
            token_overlap(normalized_topic, tags),
            token_overlap(normalized_topic, pending),
        )
        if overlap:
            score += overlap * 3.0
        combined = " ".join(
            value
            for value in [
                name,
                topic_name,
                summary,
                goal,
                left_off,
                tags,
                pending,
            ]
            if value
        )
        if normalized_topic and normalized_topic in combined:
            score += 1.5
        if normalized_topic and goal and normalized_topic in goal:
            score += 1.75
            reasons.append("active goal overlap")
        if normalized_topic and left_off and normalized_topic in left_off:
            score += 1.25
            reasons.append("where-left-off overlap")
        if normalized_topic and tags and normalized_topic in tags:
            score += 1.0
            reasons.append("tag match")
        if workspace.last_opened_at:
            score += 0.75
            reasons.append("recent activity")
        if workspace.archived:
            score -= 0.2
        return score, reasons

    def _normalize_surface_content(self, surface_content: object) -> dict[str, dict[str, Any]]:
        if not isinstance(surface_content, dict) or not surface_content:
            return {}
        raw = surface_content
        normalized: dict[str, dict[str, Any]] = {}
        for surface, purpose in _SURFACE_PURPOSES.items():
            cluster = raw.get(surface, {})
            if not isinstance(cluster, dict):
                cluster = {}
            items = cluster.get("items", [])
            normalized_items = [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
            bounded_items = self._bounded_workspace_items(normalized_items, limit=WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT)
            debug_reasons = cluster.get("debugReasons", [])
            normalized[surface] = {
                "surface": surface,
                "title": str(cluster.get("title") or _SURFACE_TITLES[surface]).strip() or _SURFACE_TITLES[surface],
                "purpose": str(cluster.get("purpose") or purpose).strip() or purpose,
                "presentationKind": str(cluster.get("presentationKind") or _SURFACE_PRESENTATION_KINDS[surface]).strip()
                or _SURFACE_PRESENTATION_KINDS[surface],
                "items": bounded_items["items"],
                "itemsSummary": bounded_items["summary"],
                "debugReasons": [
                    str(reason).strip()
                    for reason in debug_reasons
                    if str(reason).strip()
                ]
                if isinstance(debug_reasons, list)
                else [],
            }
        return normalized

    def _cluster_items(self, surface_content: object, surface: str) -> list[dict[str, Any]]:
        normalized = self._normalize_surface_content(surface_content)
        cluster = normalized.get(surface, {})
        items = cluster.get("items", [])
        return [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def _workspace_capabilities(self, *, restore_saved_posture: bool) -> dict[str, Any]:
        return {
            "apply_workspace_templates": True,
            "restore_saved_posture": restore_saved_posture,
            "restore_layout_posture": restore_saved_posture,
            "restore_recent_materials": True,
            "show_inclusion_reasons": True,
            "distinct_surface_roles": True,
            "workspace_clustering": True,
            "reference_clustering": True,
            "browser_tab_restore": False,
        }

    def _continuity_from_posture(
        self,
        workspace: WorkspaceRecord,
        posture: dict[str, Any],
        opened_items: list[dict[str, Any]],
        active_item: dict[str, Any],
    ) -> WorkspaceContinuitySnapshot:
        continuity_payload = posture.get("continuity", {})
        if not isinstance(continuity_payload, dict):
            continuity_payload = {}
        pending_next_steps = self._normalize_string_list(
            posture.get("pending_next_steps")
            or continuity_payload.get("pendingNextSteps")
            or workspace.pending_next_steps
        )
        active_goal = str(posture.get("active_goal") or continuity_payload.get("activeGoal") or workspace.active_goal).strip()
        current_task_state = str(
            posture.get("current_task_state")
            or continuity_payload.get("currentTaskState")
            or workspace.current_task_state
        ).strip()
        last_completed_action = str(
            posture.get("last_completed_action")
            or continuity_payload.get("lastCompletedAction")
            or workspace.last_completed_action
        ).strip()
        problem_domain = str(
            posture.get("problem_domain")
            or continuity_payload.get("problemDomain")
            or workspace.problem_domain
        ).strip()
        references = self._normalize_item_list(
            posture.get("references")
            or continuity_payload.get("references")
            or workspace.references
        )
        findings = self._normalize_item_list(
            posture.get("findings")
            or continuity_payload.get("findings")
            or workspace.findings
        )
        session_notes = self._normalize_item_list(
            posture.get("session_notes")
            or continuity_payload.get("sessionNotes")
            or workspace.session_notes
            or self._workspace_notes(workspace.workspace_id)
        )
        where_left_off = str(
            posture.get("where_left_off")
            or continuity_payload.get("whereLeftOff")
            or workspace.where_left_off
        ).strip()
        if not where_left_off:
            where_left_off = self._build_where_left_off(
                workspace_name=workspace.name,
                active_goal=active_goal,
                last_completed_action=last_completed_action,
                pending_next_steps=pending_next_steps,
                active_item=active_item,
            )
        return WorkspaceContinuitySnapshot(
            active_goal=active_goal,
            current_task_state=current_task_state,
            last_completed_action=last_completed_action,
            pending_next_steps=pending_next_steps,
            where_left_off=where_left_off,
            problem_domain=problem_domain,
            active_item=dict(active_item) if active_item else (opened_items[0] if opened_items else {}),
            opened_items=[dict(item) for item in opened_items],
            references=references,
            findings=findings,
            session_notes=session_notes,
        )

    def _session_posture_from_posture(self, workspace: WorkspaceRecord, posture: dict[str, Any]) -> WorkspaceSessionPosture:
        posture_payload = posture.get("session_posture", {})
        if not isinstance(posture_payload, dict):
            posture_payload = {}
        template_key = str(posture.get("template_key") or workspace.template_key).strip().lower()
        template = self.templates.get(template_key) if template_key else None
        surface_mode = str(
            posture_payload.get("surfaceMode")
            or posture.get("surface_mode")
            or workspace.last_surface_mode
            or "deck"
        ).strip().lower() or "deck"
        active_module = str(
            posture_payload.get("activeModule")
            or posture.get("active_module")
            or workspace.last_active_module
            or (template.default_module if template is not None else "chartroom")
        ).strip().lower() or "chartroom"
        active_section = str(
            posture_payload.get("activeSection")
            or posture.get("section")
            or workspace.last_active_section
            or (template.default_section if template is not None else "overview")
        ).strip().lower() or "overview"
        emphasis = self._normalize_string_list(posture_payload.get("emphasis"))
        if not emphasis and template is not None:
            emphasis = list(template.emphasis)
        return WorkspaceSessionPosture(
            surface_mode=surface_mode,
            active_module=active_module,
            active_section=active_section,
            emphasis=emphasis,
            restored_from_saved_posture=bool(
                posture_payload.get("restoredFromSavedPosture")
                or workspace.last_snapshot_at
            ),
        )

    def _resolve_template(
        self,
        *,
        query: str,
        topic: str,
        workspace: WorkspaceRecord | None,
        active_context: dict[str, Any] | None,
        allow_generic: bool,
    ) -> tuple[WorkspaceTemplateDefinition, str, float, list[str]]:
        normalized_query = normalize_phrase(query)
        normalized_topic = normalize_phrase(topic)
        active_text = ""
        if isinstance(active_context, dict):
            active_text = normalize_phrase(
                " ".join(
                    str(value)
                    for value in active_context.values()
                    if isinstance(value, str)
                )
            )

        best_template = self.templates["project"]
        best_score = -1.0
        best_reasons: list[str] = []
        best_source = "default"

        for template in self.templates.values():
            score = 0.2 if allow_generic else 0.0
            reasons: list[str] = []
            aliases = {
                normalize_phrase(value)
                for value in [template.key, template.title, *template.aliases]
                if str(value).strip()
            }
            keywords = {
                normalize_phrase(value)
                for value in template.search_keywords
                if str(value).strip()
            }
            explicit_match = any(alias and alias in normalized_query for alias in aliases)
            if explicit_match:
                score += 6.0
                reasons.append("explicit workspace wording")
            if workspace is not None and workspace.template_key == template.key:
                score += 5.0
                reasons.append("saved template posture")
            if workspace is not None and normalize_phrase(workspace.category) in aliases:
                score += 2.0
                reasons.append("workspace category alignment")
            if workspace is not None and normalize_phrase(workspace.problem_domain) in keywords:
                score += 1.75
                reasons.append("problem-domain alignment")
            if normalized_topic:
                alias_overlap = max((token_overlap(normalized_topic, alias) for alias in aliases), default=0.0)
                if alias_overlap:
                    score += alias_overlap * 3.5
                    reasons.append("topic-template overlap")
                keyword_overlap = max((token_overlap(normalized_topic, keyword) for keyword in keywords), default=0.0)
                if keyword_overlap:
                    score += keyword_overlap * 2.5
                    reasons.append("topic keyword overlap")
            if normalized_query:
                keyword_overlap = max((token_overlap(normalized_query, keyword) for keyword in keywords), default=0.0)
                if keyword_overlap:
                    score += keyword_overlap * 2.0
                    reasons.append("query keyword overlap")
            if active_text:
                keyword_overlap = max((token_overlap(active_text, keyword) for keyword in keywords), default=0.0)
                if keyword_overlap:
                    score += keyword_overlap * 1.5
                    reasons.append("active-context overlap")
            if template.key == "troubleshooting" and any(token in normalized_query for token in {"troubleshoot", "issue", "debug", "fix"}):
                score += 1.5
                reasons.append("diagnostic intent")
            if template.key == "research" and any(token in normalized_query for token in {"research", "study", "reference"}):
                score += 1.5
                reasons.append("research intent")
            if template.key == "writing" and any(token in normalized_query for token in {"write", "draft", "essay", "article"}):
                score += 1.5
                reasons.append("writing intent")
            if score > best_score:
                best_template = template
                best_score = score
                best_reasons = reasons
                if explicit_match:
                    best_source = "explicit"
                elif workspace is not None and workspace.template_key == template.key:
                    best_source = "saved"
                elif reasons:
                    best_source = "inferred"
                else:
                    best_source = "default"

        return best_template, best_source, round(max(best_score, 0.0), 3), best_reasons

    def _resume_context_from_restore(
        self,
        *,
        workspace: WorkspaceRecord,
        snapshot_payload: dict[str, Any],
        basis: str,
    ) -> WorkspaceResumeContext:
        payload = snapshot_payload if isinstance(snapshot_payload, dict) else {}
        restored_fields: list[str] = []
        if payload.get("surface_mode"):
            restored_fields.append("surface_mode")
        if payload.get("active_module"):
            restored_fields.append("active_module")
        if payload.get("section"):
            restored_fields.append("active_section")
        if payload.get("opened_items"):
            restored_fields.append("opened_items")
        if payload.get("pending_next_steps"):
            restored_fields.append("pending_next_steps")
        if payload.get("surface_content"):
            restored_fields.append("surface_content")
        if payload:
            return WorkspaceResumeContext(
                source="saved_snapshot",
                basis=basis or "saved workspace posture",
                used_saved_posture=True,
                used_template_defaults=False,
                restored_fields=restored_fields,
                limitations=[],
            )
        limitations = []
        if not workspace.last_snapshot_at:
            limitations.append("This workspace has no saved posture yet, so template defaults were used.")
        return WorkspaceResumeContext(
            source="workspace_memory",
            basis=basis or "retained workspace memory",
            used_saved_posture=False,
            used_template_defaults=True,
            restored_fields=[],
            limitations=limitations,
        )

    def _item_identity(self, item: dict[str, Any]) -> str:
        return str(item.get("itemId") or item.get("url") or item.get("path") or item.get("title") or "").strip()

    def _workspace_topic_from_query(
        self,
        *,
        query: str,
        template: WorkspaceTemplateDefinition,
        workspace: WorkspaceRecord,
    ) -> str:
        normalized = normalize_phrase(query)
        alias_tokens: set[str] = set()
        for value in [template.key, template.title, *template.aliases]:
            for token in normalize_phrase(value).split():
                alias_tokens.add(token)
                for source, normalized_token in _TOPIC_TOKEN_NORMALIZATIONS.items():
                    if normalized_token == token:
                        alias_tokens.add(source)
        tokens = [
            _TOPIC_TOKEN_NORMALIZATIONS.get(token, token)
            for token in normalized.split()
            if token
            and token not in _WORKSPACE_COMMAND_TOKENS
            and token not in alias_tokens
            and token not in _VAGUE_TOPIC_TOKENS
        ]
        derived = " ".join(tokens).strip()
        if derived and not self._is_vague_topic(derived):
            return derived
        existing = normalize_lookup_phrase(workspace.topic or workspace.name)
        if existing and existing != "current work":
            return existing
        return normalize_lookup_phrase(template.key.replace("-", " ")) or "current work"

    def _workspace_display_name(self, topic: str, workspace: WorkspaceRecord) -> str:
        normalized_topic = normalize_lookup_phrase(topic)
        existing_topic = normalize_lookup_phrase(workspace.topic)
        if workspace.name and existing_topic == normalized_topic and normalized_topic != "current work":
            return workspace.name
        return " ".join(part.capitalize() for part in topic.split()) or workspace.name or "Recovered Workspace"

    def _build_workspace_plan(
        self,
        *,
        query: str,
        session_id: str,
        workspace: WorkspaceRecord,
        template: WorkspaceTemplateDefinition,
        template_source: str,
        template_confidence: float,
        template_reasons: list[str],
        resume_context: WorkspaceResumeContext,
        snapshot_payload: dict[str, Any] | None = None,
    ) -> WorkspaceAssemblyPlan:
        payload = snapshot_payload if isinstance(snapshot_payload, dict) else {}
        derived_topic = self._workspace_topic_from_query(query=query, template=template, workspace=workspace)
        workspace_name = self._workspace_display_name(derived_topic, workspace)
        search_query = self._assembly_search_query(query=query, topic=derived_topic, workspace=workspace)

        snapshot_items = self._normalize_item_list(payload.get("opened_items"))
        repo_items = [item.to_action_item() for item in self.repository.list_items(workspace.workspace_id, limit=10)]
        indexed_items = self.indexer.search_files(search_query, limit=8)
        note_matches = [] if self._is_vague_topic(derived_topic) else self._matching_notes(derived_topic, limit=4)
        retained_references = self._normalize_item_list(payload.get("references") or workspace.references)
        retained_findings = self._normalize_item_list(payload.get("findings") or workspace.findings)
        retained_notes = self._normalize_item_list(
            payload.get("session_notes")
            or payload.get("sessionNotes")
            or workspace.session_notes
            or self._workspace_notes(workspace.workspace_id)
        )

        candidate_items: list[dict[str, Any]] = []
        for group in (indexed_items, note_matches, retained_references, repo_items, snapshot_items):
            candidate_items = self._merge_items(candidate_items, self._normalize_item_list(group))

        snapshot_keys = {self._item_identity(item) for item in snapshot_items}
        repo_keys = {self._item_identity(item) for item in repo_items}
        indexed_keys = {self._item_identity(item) for item in indexed_items}
        note_keys = {self._item_identity(item) for item in note_matches}
        reference_keys = {self._item_identity(item) for item in retained_references}
        normalized_topic = normalize_phrase(derived_topic)
        normalized_query = normalize_phrase(search_query)

        scored_candidates: list[tuple[float, dict[str, Any], list[WorkspaceInclusionReason]]] = []
        excluded_items: list[dict[str, Any]] = []
        for item in candidate_items:
            prepared = self._prepare_item(item, default_module=template.default_module)
            item_id = self._item_identity(prepared)
            title = normalize_phrase(str(prepared.get("title", "")))
            subtitle = normalize_phrase(str(prepared.get("subtitle", "")))
            detail = normalize_phrase(
                " ".join(
                    value
                    for value in [
                        str(prepared.get("summary", "")),
                        str(prepared.get("path", "")),
                        str(prepared.get("url", "")),
                        str(prepared.get("content", ""))[:240],
                    ]
                    if value
                )
            )
            combined = " ".join(part for part in [title, subtitle, detail] if part)
            reasons: list[WorkspaceInclusionReason] = []
            score = 0.0

            if item_id in snapshot_keys:
                score += 4.0
                reasons.append(
                    WorkspaceInclusionReason(
                        code="restored_snapshot",
                        label="Restored from saved posture",
                        detail="Opened in the last saved workspace posture.",
                        score=4.0,
                        source="snapshot",
                    )
                )
            if item_id in repo_keys:
                score += 2.2
                reasons.append(
                    WorkspaceInclusionReason(
                        code="recent_workspace_member",
                        label="Recently used in this workspace",
                        detail="Saved as part of recent workspace activity.",
                        score=2.2,
                        source="workspace",
                    )
                )
            if item_id in indexed_keys:
                score += 1.6
                reasons.append(
                    WorkspaceInclusionReason(
                        code="topic_match",
                        label="Matches the workspace topic",
                        detail=str(prepared.get("summary") or "Strong topic overlap from indexed local material."),
                        score=1.6,
                        source="index",
                    )
                )
            if item_id in note_keys:
                score += 1.4
                reasons.append(
                    WorkspaceInclusionReason(
                        code="logbook_match",
                        label="Referenced in Logbook",
                        detail="Matches a retained note tied to this topic.",
                        score=1.4,
                        source="logbook",
                    )
                )
            if item_id in reference_keys:
                score += 1.8
                reasons.append(
                    WorkspaceInclusionReason(
                        code="retained_reference",
                        label="Retained workspace reference",
                        detail="Already saved as supporting material for this workspace.",
                        score=1.8,
                        source="workspace",
                    )
                )

            topic_overlap = max(token_overlap(normalized_topic, combined), token_overlap(normalized_query, combined))
            if topic_overlap:
                score += topic_overlap * 4.2
                reasons.append(
                    WorkspaceInclusionReason(
                        code="topic_overlap",
                        label="Strong topic overlap",
                        detail="The item closely matches the current workspace focus.",
                        score=topic_overlap * 4.2,
                        source="relevance",
                    )
                )
            if title and normalized_topic and normalized_topic in title:
                score += 1.2
            path = str(prepared.get("path", "")).strip()
            if path:
                suffix = Path(path).suffix.lower()
                if suffix in template.preferred_extensions:
                    score += 1.1
                    reasons.append(
                        WorkspaceInclusionReason(
                            code="template_fit",
                            label="Fits the workspace template",
                            detail=f"The file type aligns with the {template.title.lower()} template.",
                            score=1.1,
                            source="template",
                        )
                    )
            if template.key in {"troubleshooting", "systems-diagnostics"} and any(
                token in combined for token in {"diagnostic", "error", "trace", "wifi", "network", "latency", "driver"}
            ):
                score += 1.0
            if template.key == "research" and any(
                token in combined for token in {"reference", "study", "research", "notes", "docs", "paper"}
            ):
                score += 1.0
            if score <= 0:
                excluded_items.append(
                    {
                        "title": str(prepared.get("title", "Untitled")),
                        "reason": "Insufficient relevance score for the current workspace.",
                    }
                )
                continue
            scored_candidates.append((score, prepared, reasons))

        scored_candidates.sort(key=lambda item: item[0], reverse=True)
        scored_map = {self._item_identity(item): (score, reasons) for score, item, reasons in scored_candidates}

        snapshot_active_item = payload.get("active_item", {})
        if not isinstance(snapshot_active_item, dict):
            snapshot_active_item = {}

        opened_items = snapshot_items or repo_items or [dict(item) for _, item, _ in scored_candidates[:3]]
        opened_items = self._normalize_item_list(opened_items)
        if not opened_items and scored_candidates:
            opened_items = [dict(scored_candidates[0][1])]
        active_item = snapshot_active_item if snapshot_active_item else (opened_items[0] if opened_items else {})
        pending_next_steps = self._normalize_string_list(payload.get("pending_next_steps") or workspace.pending_next_steps)
        if not pending_next_steps:
            pending_next_steps = self._derive_next_steps(query, active_item, opened_items)

        active_goal = str(payload.get("active_goal") or workspace.active_goal).strip()
        if not active_goal and derived_topic != "current work":
            active_goal = f"Continue the {derived_topic} work."
        current_task_state = str(payload.get("current_task_state") or workspace.current_task_state or query).strip()
        last_completed_action = str(payload.get("last_completed_action") or workspace.last_completed_action).strip()
        problem_domain = str(payload.get("problem_domain") or workspace.problem_domain).strip()
        if not problem_domain and template.key in {"troubleshooting", "systems-diagnostics"}:
            problem_domain = "diagnostics"
        if not problem_domain and template.key == "research":
            problem_domain = "research"
        where_left_off = str(payload.get("where_left_off") or workspace.where_left_off).strip()
        if not where_left_off:
            where_left_off = self._build_where_left_off(
                workspace_name=workspace_name,
                active_goal=active_goal,
                last_completed_action=last_completed_action,
                pending_next_steps=pending_next_steps,
                active_item=active_item,
            )

        continuity = WorkspaceContinuitySnapshot(
            active_goal=active_goal,
            current_task_state=current_task_state,
            last_completed_action=last_completed_action,
            pending_next_steps=pending_next_steps,
            where_left_off=where_left_off,
            problem_domain=problem_domain,
            active_item=dict(active_item) if active_item else (opened_items[0] if opened_items else {}),
            opened_items=opened_items,
            references=retained_references,
            findings=retained_findings,
            session_notes=retained_notes,
        )

        saved_session_posture = payload.get("session_posture") if isinstance(payload.get("session_posture"), dict) else {}
        session_posture = WorkspaceSessionPosture(
            surface_mode=str(saved_session_posture.get("surfaceMode") or payload.get("surface_mode") or workspace.last_surface_mode or "deck").strip().lower()
            or "deck",
            active_module=str(saved_session_posture.get("activeModule") or payload.get("active_module") or workspace.last_active_module or template.default_module).strip().lower()
            or template.default_module,
            active_section=str(saved_session_posture.get("activeSection") or payload.get("section") or workspace.last_active_section or template.default_section).strip().lower()
            or template.default_section,
            emphasis=self._normalize_string_list(saved_session_posture.get("emphasis")) or list(template.emphasis),
            restored_from_saved_posture=resume_context.used_saved_posture,
        )

        likely_next = self._likely_next_bearing(
            pending_next_steps=pending_next_steps,
            active_item=active_item,
            opened_items=opened_items,
        )
        capabilities = self._workspace_capabilities(
            restore_saved_posture=bool(resume_context.used_saved_posture or workspace.last_snapshot_at)
        )

        persisted_workspace = self.repository.upsert_workspace(
            workspace_id=workspace.workspace_id,
            name=workspace_name,
            topic=derived_topic,
            summary=where_left_off or workspace.summary or f"{template.title} workspace for {derived_topic}.",
            title=workspace_name,
            status=f"{session_posture.surface_mode}:{session_posture.active_module}",
            category=workspace.category or template.key,
            template_key=template.key,
            template_source=template_source,
            problem_domain=continuity.problem_domain,
            active_goal=continuity.active_goal,
            current_task_state=continuity.current_task_state,
            last_completed_action=continuity.last_completed_action,
            last_surface_mode=session_posture.surface_mode,
            last_active_module=session_posture.active_module,
            last_active_section=session_posture.active_section,
            pending_next_steps=continuity.pending_next_steps,
            references=continuity.references,
            findings=continuity.findings,
            session_notes=continuity.session_notes,
            where_left_off=continuity.where_left_off,
            pinned=workspace.pinned,
            archived=workspace.archived,
            archived_at=workspace.archived_at,
            last_snapshot_at=workspace.last_snapshot_at,
            tags=workspace.tags,
        )

        def candidate_reasons(item: dict[str, Any]) -> list[dict[str, Any]]:
            _, reasons = scored_map.get(self._item_identity(item), (0.0, []))
            return [reason.to_dict() for reason in reasons]

        def collection_item(item: dict[str, Any], *, badge: str, fallback_role: str, subtitle: str = "") -> dict[str, Any]:
            prepared = self._prepare_item(item, default_module=session_posture.active_module)
            detail = str(prepared.get("url") or prepared.get("path") or prepared.get("summary", "")).strip()
            payload_item = {
                "itemId": str(prepared.get("itemId") or ""),
                "title": str(prepared.get("title", "Untitled")),
                "subtitle": str(prepared.get("subtitle") or subtitle or str(prepared.get("viewer", prepared.get("kind", "item"))).title()),
                "detail": detail,
                "badge": badge,
                "role": str(prepared.get("summary") or fallback_role).strip() or fallback_role,
                "viewer": str(prepared.get("viewer", "")),
                "kind": str(prepared.get("kind", "")),
                "module": str(prepared.get("module", "")),
                "section": str(prepared.get("section", "")),
                "whyIncluded": candidate_reasons(prepared),
            }
            if prepared.get("path"):
                payload_item["path"] = str(prepared.get("path"))
            if prepared.get("url"):
                payload_item["url"] = str(prepared.get("url"))
            return payload_item

        reference_items = retained_references or [dict(item) for _, item, _ in scored_candidates[:4]]
        file_items = [
            dict(item)
            for _, item, _ in scored_candidates
            if str(item.get("path", "")).strip()
        ][:4]
        if not file_items:
            file_items = [item for item in opened_items if str(item.get("path", "")).strip()][:4]

        findings_items = retained_findings[:4]
        if not findings_items:
            findings_items = [
                {
                    "title": continuity.last_completed_action or f"{template.title} posture prepared",
                    "summary": continuity.where_left_off,
                    "source": "Workspace Memory" if resume_context.used_saved_posture else "Template Guidance",
                }
            ]

        logbook_items = retained_notes[:4]
        if not logbook_items and continuity.where_left_off:
            logbook_items = [
                {
                    "title": f"{persisted_workspace.name} handoff note",
                    "subtitle": "Logbook",
                    "detail": continuity.where_left_off,
                    "summary": continuity.where_left_off,
                }
            ]

        session_panels = [
            {
                "title": "Current Bearing",
                "summary": persisted_workspace.name,
                "detail": continuity.current_task_state or persisted_workspace.summary,
                "entries": [
                    {"label": "Topic", "value": persisted_workspace.topic},
                    {"label": "Template", "value": template.title},
                ],
            },
            {
                "title": "Workspace Continuity",
                "summary": "Saved posture restored" if resume_context.used_saved_posture else "Template defaults applied",
                "detail": continuity.where_left_off,
                "entries": [
                    {"label": "Last Completed", "value": continuity.last_completed_action or "No recorded completion yet"},
                    {"label": "Likely Next", "value": likely_next or "Hold current course"},
                ],
            },
            {
                "title": "Resume Basis",
                "summary": resume_context.basis or "Workspace staging",
                "detail": "; ".join(resume_context.limitations) if resume_context.limitations else template.purpose_summary,
                "entries": [
                    {"label": "Module", "value": session_posture.active_module},
                    {"label": "Section", "value": session_posture.active_section},
                ],
            },
        ]

        task_entries = [
            {
                "title": step,
                "status": "priority" if index == 0 else "ready",
                "detail": continuity.current_task_state or continuity.where_left_off,
            }
            for index, step in enumerate(continuity.pending_next_steps[:4])
        ]
        if not task_entries and likely_next:
            task_entries.append(
                {
                    "title": likely_next,
                    "status": "priority",
                    "detail": continuity.where_left_off,
                }
            )

        opened_item_keys = {self._item_identity(item) for item in opened_items}
        clusters = [
            WorkspaceRoleCluster(
                surface="opened-items",
                title=_SURFACE_TITLES["opened-items"],
                purpose=_SURFACE_PURPOSES["opened-items"],
                presentation_kind=_SURFACE_PRESENTATION_KINDS["opened-items"],
                items=[
                    collection_item(
                        item,
                        badge="Active" if self._item_identity(item) == self._item_identity(active_item) else "Held",
                        fallback_role="Actively staged for the current work session.",
                    )
                    for item in opened_items[:4]
                ],
                debug_reasons=["Items actively held in the current workspace posture."],
            ),
            WorkspaceRoleCluster(
                surface="references",
                title=_SURFACE_TITLES["references"],
                purpose=_SURFACE_PURPOSES["references"],
                presentation_kind=_SURFACE_PRESENTATION_KINDS["references"],
                items=[
                    collection_item(
                        item,
                        badge="Support",
                        fallback_role="Supporting material for the current workspace.",
                        subtitle="Research" if template.key == "research" else "",
                    )
                    for item in reference_items[:4]
                ],
                debug_reasons=["Support material was ranked separately from actively opened items."],
            ),
            WorkspaceRoleCluster(
                surface="findings",
                title=_SURFACE_TITLES["findings"],
                purpose=_SURFACE_PURPOSES["findings"],
                presentation_kind=_SURFACE_PRESENTATION_KINDS["findings"],
                items=[
                    {
                        "title": str(item.get("title") or item.get("summary") or "Workspace finding"),
                        "summary": str(item.get("summary") or item.get("detail") or continuity.where_left_off),
                        "source": str(item.get("source") or "Workspace"),
                    }
                    for item in findings_items
                ],
                debug_reasons=["Findings summarize learned or retained takeaways instead of raw references."],
            ),
            WorkspaceRoleCluster(
                surface="session",
                title=_SURFACE_TITLES["session"],
                purpose=_SURFACE_PURPOSES["session"],
                presentation_kind=_SURFACE_PRESENTATION_KINDS["session"],
                items=session_panels,
                debug_reasons=["Session panels summarize posture, continuity, and resume basis."],
            ),
            WorkspaceRoleCluster(
                surface="tasks",
                title=_SURFACE_TITLES["tasks"],
                purpose=_SURFACE_PURPOSES["tasks"],
                presentation_kind=_SURFACE_PRESENTATION_KINDS["tasks"],
                items=[
                    {
                        "title": "Next Bearings",
                        "entries": task_entries or [
                            {
                                "title": "Review the current workspace posture.",
                                "status": "ready",
                                "detail": "No concrete next steps were recorded yet.",
                            }
                        ],
                    }
                ],
                debug_reasons=["Tasks are built from pending next steps and likely-next continuity."],
            ),
            WorkspaceRoleCluster(
                surface="files",
                title=_SURFACE_TITLES["files"],
                purpose=_SURFACE_PURPOSES["files"],
                presentation_kind=_SURFACE_PRESENTATION_KINDS["files"],
                items=[
                    collection_item(
                        item,
                        badge="Held" if self._item_identity(item) in opened_item_keys else "Relevant",
                        fallback_role="Concrete file asset relevant to the current workspace.",
                        subtitle="Files",
                    )
                    for item in file_items
                ],
                debug_reasons=["Files emphasize concrete path-based assets instead of broader support material."],
            ),
            WorkspaceRoleCluster(
                surface="logbook",
                title=_SURFACE_TITLES["logbook"],
                purpose=_SURFACE_PURPOSES["logbook"],
                presentation_kind=_SURFACE_PRESENTATION_KINDS["logbook"],
                items=[
                    {
                        "title": str(item.get("title", "Workspace note")),
                        "subtitle": str(item.get("subtitle") or "Logbook"),
                        "detail": str(item.get("detail") or item.get("content") or item.get("summary", ""))[:200],
                        "badge": "Retained",
                        "role": str(item.get("summary") or "Retained workspace context.").strip() or "Retained workspace context.",
                    }
                    for item in logbook_items
                ],
                debug_reasons=["Logbook retains remembered notes and carryover instead of active files."],
            ),
        ]

        for item in opened_items[:4]:
            score = scored_map.get(self._item_identity(item), (0.0, []))[0]
            self.repository.upsert_item(
                persisted_workspace.workspace_id,
                self._prepare_item(item, default_module=session_posture.active_module),
                score=score,
            )

        return WorkspaceAssemblyPlan(
            workspace=persisted_workspace,
            template=template,
            template_confidence=template_confidence,
            template_reasons=template_reasons,
            opened_items=opened_items,
            active_item_id=self._item_identity(active_item),
            clusters=clusters,
            continuity=continuity,
            session_posture=session_posture,
            resume_context=resume_context,
            capabilities=capabilities,
            likely_next=likely_next,
            debug={
                "template": {
                    "key": template.key,
                    "source": template_source,
                    "confidence": template_confidence,
                    "reasons": list(template_reasons),
                },
                "assembly": {
                    "topic": derived_topic,
                    "searchQuery": search_query,
                    "included": [
                        {
                            "title": str(item.get("title", "Untitled")),
                            "score": round(score, 3),
                            "whyIncluded": [reason.to_dict() for reason in reasons],
                        }
                        for score, item, reasons in scored_candidates[:8]
                    ],
                    "excluded": excluded_items[:8],
                    "resumeContext": resume_context.to_dict(),
                },
                "surfaces": {
                    cluster.surface: {
                        "presentationKind": cluster.presentation_kind,
                        "count": len(cluster.items),
                    }
                    for cluster in clusters
                },
            },
        )

    def _surface_content_from_workspace_state(
        self,
        *,
        workspace: WorkspaceRecord,
        continuity: WorkspaceContinuitySnapshot,
        session_posture: WorkspaceSessionPosture,
        opened_items: list[dict[str, Any]],
        active_item: dict[str, Any],
        likely_next: str,
    ) -> dict[str, dict[str, Any]]:
        active_item_id = self._item_identity(active_item)

        def collection_item(item: dict[str, Any], *, badge: str, fallback_role: str, subtitle: str = "") -> dict[str, Any]:
            prepared = self._prepare_item(item, default_module=session_posture.active_module)
            payload_item = {
                "itemId": str(prepared.get("itemId") or ""),
                "title": str(prepared.get("title", "Untitled")),
                "subtitle": str(prepared.get("subtitle") or subtitle or str(prepared.get("viewer", prepared.get("kind", "item"))).title()),
                "detail": str(prepared.get("url") or prepared.get("path") or prepared.get("summary", "")).strip(),
                "badge": badge,
                "role": str(prepared.get("summary") or fallback_role).strip() or fallback_role,
                "whyIncluded": [],
            }
            if prepared.get("path"):
                payload_item["path"] = str(prepared.get("path"))
            if prepared.get("url"):
                payload_item["url"] = str(prepared.get("url"))
            return payload_item

        findings_items = continuity.findings[:4] or [
            {
                "title": continuity.last_completed_action or f"{workspace.name} posture retained",
                "summary": continuity.where_left_off,
                "source": "Workspace",
            }
        ]
        logbook_items = continuity.session_notes[:4] or [
            {
                "title": f"{workspace.name} handoff note",
                "subtitle": "Logbook",
                "detail": continuity.where_left_off,
                "summary": continuity.where_left_off,
            }
        ]
        surface_content = {
            "opened-items": {
                "title": _SURFACE_TITLES["opened-items"],
                "purpose": _SURFACE_PURPOSES["opened-items"],
                "presentationKind": _SURFACE_PRESENTATION_KINDS["opened-items"],
                "items": [
                    collection_item(
                        item,
                        badge="Active" if self._item_identity(item) == active_item_id else "Held",
                        fallback_role="Actively staged for the current workspace.",
                    )
                    for item in opened_items[:4]
                ],
                "debugReasons": ["Restored from the current workspace posture."],
            },
            "references": {
                "title": _SURFACE_TITLES["references"],
                "purpose": _SURFACE_PURPOSES["references"],
                "presentationKind": _SURFACE_PRESENTATION_KINDS["references"],
                "items": [
                    collection_item(
                        item,
                        badge="Support",
                        fallback_role="Supporting material for the current workspace.",
                    )
                    for item in continuity.references[:4]
                ],
                "debugReasons": ["References remain separate from currently opened items."],
            },
            "findings": {
                "title": _SURFACE_TITLES["findings"],
                "purpose": _SURFACE_PURPOSES["findings"],
                "presentationKind": _SURFACE_PRESENTATION_KINDS["findings"],
                "items": [
                    {
                        "title": str(item.get("title") or item.get("summary") or "Workspace finding"),
                        "summary": str(item.get("summary") or item.get("detail") or continuity.where_left_off),
                        "source": str(item.get("source") or "Workspace"),
                    }
                    for item in findings_items
                ],
                "debugReasons": ["Findings summarize learned outcomes instead of source material."],
            },
            "session": {
                "title": _SURFACE_TITLES["session"],
                "purpose": _SURFACE_PURPOSES["session"],
                "presentationKind": _SURFACE_PRESENTATION_KINDS["session"],
                "items": [
                    {
                        "title": "Current Bearing",
                        "summary": workspace.name,
                        "detail": continuity.current_task_state or continuity.where_left_off,
                        "entries": [
                            {"label": "Topic", "value": workspace.topic},
                            {"label": "Module", "value": session_posture.active_module},
                        ],
                    }
                ],
                "debugReasons": ["Session summarizes the current posture instead of repeating file lists."],
            },
            "tasks": {
                "title": _SURFACE_TITLES["tasks"],
                "purpose": _SURFACE_PURPOSES["tasks"],
                "presentationKind": _SURFACE_PRESENTATION_KINDS["tasks"],
                "items": [
                    {
                        "title": "Next Bearings",
                        "entries": [
                            {
                                "title": step,
                                "status": "priority" if index == 0 else "ready",
                                "detail": continuity.current_task_state or continuity.where_left_off,
                            }
                            for index, step in enumerate(continuity.pending_next_steps[:4] or ([likely_next] if likely_next else []))
                        ]
                        or [
                            {
                                "title": "Review the current workspace posture.",
                                "status": "ready",
                                "detail": "No pending next steps were retained yet.",
                            }
                        ],
                    }
                ],
                "debugReasons": ["Tasks draw from pending next steps and likely-next continuity."],
            },
            "files": {
                "title": _SURFACE_TITLES["files"],
                "purpose": _SURFACE_PURPOSES["files"],
                "presentationKind": _SURFACE_PRESENTATION_KINDS["files"],
                "items": [
                    collection_item(
                        item,
                        badge="Held",
                        fallback_role="Concrete file asset relevant to the current workspace.",
                        subtitle="Files",
                    )
                    for item in [item for item in opened_items if str(item.get("path", "")).strip()][:4]
                ],
                "debugReasons": ["Files emphasize concrete path-based material."],
            },
            "logbook": {
                "title": _SURFACE_TITLES["logbook"],
                "purpose": _SURFACE_PURPOSES["logbook"],
                "presentationKind": _SURFACE_PRESENTATION_KINDS["logbook"],
                "items": [
                    {
                        "title": str(item.get("title", "Workspace note")),
                        "subtitle": str(item.get("subtitle") or "Logbook"),
                        "detail": str(item.get("detail") or item.get("content") or item.get("summary", ""))[:200],
                        "badge": "Retained",
                        "role": str(item.get("summary") or "Retained workspace context.").strip() or "Retained workspace context.",
                    }
                    for item in logbook_items
                ],
                "debugReasons": ["Logbook retains memory and carryover instead of active session material."],
            },
        }
        return self._normalize_surface_content(surface_content)

    def _finalize_workspace_plan(
        self,
        *,
        plan: WorkspaceAssemblyPlan,
        query: str,
        session_id: str,
        activity_type: str,
        description: str,
        bearing_title: str,
        summary: str,
        route_handler_subspans: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        subspans = dict(route_handler_subspans or _empty_workspace_subspans())
        payload_started = perf_counter()
        surface_content = self._normalize_surface_content(plan.surface_content())
        workspace_payload = self._workspace_view_payload(
            plan.workspace,
            likely_next=plan.likely_next,
            where_left_off=plan.continuity.where_left_off,
            pending_next_steps=plan.continuity.pending_next_steps,
            continuity=plan.continuity,
            session_posture=plan.session_posture,
            capabilities=plan.capabilities,
            surface_content=surface_content,
            resume_context=plan.resume_context,
        )
        workspace_payload["templateTitle"] = plan.template.title
        workspace_payload["templateConfidence"] = round(float(plan.template_confidence), 3)
        workspace_payload["templateReasons"] = list(plan.template_reasons)
        _add_workspace_subspan(subspans, "workspace_payload_build_ms", payload_started)
        db_started = perf_counter()
        self.memory.sync_workspace_memory(
            plan.workspace,
            continuity=plan.continuity,
            session_posture=plan.session_posture,
            opened_items=plan.opened_items,
            source_surface=f"workspace_{activity_type}",
        )
        _add_workspace_subspan(subspans, "workspace_db_query_ms", db_started)
        db_started = perf_counter()
        memory_context = self._workspace_memory_context(
            plan.workspace,
            session_id=session_id,
            query=query,
        )
        _add_workspace_subspan(subspans, "workspace_db_query_ms", db_started)
        workspace_payload["memoryContext"] = memory_context
        workspace_payload["payloadGuardrails"] = self._payload_guardrail_metadata(workspace_payload)

        active_item = next(
            (item for item in plan.opened_items if self._item_identity(item) == plan.active_item_id),
            plan.opened_items[0] if plan.opened_items else {},
        )
        bounded_opened_items = self._bounded_workspace_items(
            plan.opened_items,
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_references = self._bounded_workspace_items(
            plan.continuity.references,
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_findings = self._bounded_workspace_items(
            plan.continuity.findings,
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_session_notes = self._bounded_workspace_items(
            plan.continuity.session_notes,
            limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT,
        )["items"]
        bounded_active_item = self._compact_workspace_item(active_item)
        dto_started = perf_counter()
        self.session_state.set_active_workspace_id(session_id, plan.workspace.workspace_id)
        self.session_state.set_active_posture(
            session_id,
            {
                "workspace": workspace_payload,
                "surface_mode": plan.session_posture.surface_mode,
                "active_module": plan.session_posture.active_module,
                "section": plan.session_posture.active_section,
                "opened_items": bounded_opened_items,
                "active_item": bounded_active_item,
                "active_goal": plan.continuity.active_goal,
                "current_task_state": plan.continuity.current_task_state,
                "last_completed_action": plan.continuity.last_completed_action,
                "pending_next_steps": list(plan.continuity.pending_next_steps),
                "where_left_off": plan.continuity.where_left_off,
                "likely_next": plan.likely_next,
                "references": bounded_references,
                "findings": bounded_findings,
                "session_notes": bounded_session_notes,
                "template_key": plan.template.key,
                "template_source": plan.workspace.template_source,
                "problem_domain": plan.continuity.problem_domain,
                "continuity": self._compact_continuity_payload(plan.continuity, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT),
                "session_posture": plan.session_posture.to_dict(),
                "capabilities": dict(plan.capabilities),
                "surface_content": surface_content,
                "memory_context": memory_context,
                "resume_context": plan.resume_context.to_dict(),
            },
        )
        _add_workspace_subspan(subspans, "workspace_dto_build_ms", dto_started)
        event_started = perf_counter()
        self.repository.record_activity(
            workspace_id=plan.workspace.workspace_id,
            session_id=session_id,
            activity_type=activity_type,
            description=description,
            payload={
                "query": query,
                "template_key": plan.template.key,
                "template_source": plan.workspace.template_source,
                "resume_context": plan.resume_context.to_dict(),
            },
        )
        _add_workspace_subspan(subspans, "workspace_event_emit_ms", event_started)
        if activity_type == "restore":
            self._remember_workspace_alias(query, plan.workspace)
        return {
            "summary": summary,
            "workspace": workspace_payload,
            "items": bounded_opened_items,
            "memory": memory_context,
            "debug": {**dict(plan.debug), "route_handler_subspans": subspans},
            "action": {
                "type": "workspace_restore",
                "module": plan.session_posture.active_module,
                "section": plan.session_posture.active_section,
                "workspace": workspace_payload,
                "items": bounded_opened_items,
                "active_item_id": plan.active_item_id,
                "bearing_title": bearing_title,
                "micro_response": self._workspace_micro_response(activity_type, plan.template, query),
                "full_response": summary,
            },
        }

    def _finalize_workspace_fast_summary(
        self,
        *,
        workspace: WorkspaceRecord,
        query: str,
        session_id: str,
        activity_type: str,
        summary: str,
        route_handler_subspans: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        subspans = dict(route_handler_subspans or _empty_workspace_subspans())
        dto_started = perf_counter()
        pending_next_steps = self._normalize_string_list(workspace.pending_next_steps)
        where_left_off = workspace.where_left_off or workspace.summary or query
        active_goal = workspace.active_goal or workspace.summary or query
        active_item: dict[str, Any] = {}
        workspace_payload = self._compact_workspace_payload(workspace, limit=0)
        workspace_payload["likelyNext"] = pending_next_steps[0] if pending_next_steps else ""
        workspace_payload["whereLeftOff"] = where_left_off
        workspace_payload["pendingNextSteps"] = pending_next_steps
        workspace_payload["capabilities"] = self._workspace_capabilities(
            restore_saved_posture=bool(workspace.last_snapshot_at)
        )
        workspace_payload["payloadGuardrails"] = self._payload_guardrail_metadata(workspace_payload)
        posture = {
            "workspace": workspace_payload,
            "surface_mode": "ghost",
            "active_module": workspace.last_active_module or "chartroom",
            "section": workspace.last_active_section or "overview",
            "opened_items": [],
            "active_item": active_item,
            "active_goal": active_goal,
            "current_task_state": workspace.current_task_state or query,
            "last_completed_action": f"{activity_type.capitalize()} compact workspace summary.",
            "pending_next_steps": pending_next_steps,
            "where_left_off": where_left_off,
            "likely_next": pending_next_steps[0] if pending_next_steps else "",
            "references": [],
            "findings": [],
            "session_notes": [],
            "detail_load_deferred": True,
        }
        self.session_state.set_active_workspace_id(session_id, workspace.workspace_id)
        self.session_state.set_active_posture(session_id, posture)
        compact_summary = self.active_workspace_summary_compact(session_id)
        _add_workspace_subspan(subspans, "workspace_dto_build_ms", dto_started)
        event_started = perf_counter()
        self.repository.record_activity(
            workspace_id=workspace.workspace_id,
            session_id=session_id,
            activity_type=activity_type,
            description=f"{activity_type.capitalize()} compact workspace summary for {workspace.name}.",
            payload={"query": query, "detail_load_deferred": True},
        )
        _add_workspace_subspan(subspans, "workspace_event_emit_ms", event_started)
        workspace_payload = compact_summary.get("workspace") if isinstance(compact_summary.get("workspace"), dict) else {}
        items = compact_summary.get("opened_items") if isinstance(compact_summary.get("opened_items"), list) else []
        action = compact_summary.get("action") if isinstance(compact_summary.get("action"), dict) else {}
        action = {
            **action,
            "bearing_title": "Workspace summary ready",
            "micro_response": "Prepared the compact workspace summary.",
            "full_response": summary,
            "detail_load_deferred": True,
        }
        return {
            "summary": summary,
            "workspace": workspace_payload,
            "workspace_summary_compact": compact_summary.get("workspace_summary_compact", {}),
            "items": items,
            "detail_load_deferred": True,
            "debug": {"route_handler_subspans": subspans},
            "action": action,
        }

    def _workspace_bearing_title(
        self,
        activity_type: str,
        *,
        template: WorkspaceTemplateDefinition,
        query: str,
        workspace: WorkspaceRecord,
    ) -> str:
        del workspace
        lower = normalize_phrase(query)
        if activity_type == "assemble":
            return f"{template.title} workspace created"
        if "where we left off" in lower or "continue" in lower:
            return "Workspace context restored"
        if template.key == "troubleshooting":
            return "Troubleshooting workspace opened"
        return f"{template.title} workspace opened"

    def _workspace_micro_response(self, activity_type: str, template: WorkspaceTemplateDefinition, query: str) -> str:
        lower = normalize_phrase(query)
        if activity_type == "assemble":
            return f"Created the {template.title.lower()} workspace."
        if "where we left off" in lower or "continue" in lower:
            return "Restored your recent workspace context."
        return f"Opened the {template.title.lower()} workspace."

    def _workspace_summary(
        self,
        activity_type: str,
        *,
        query: str,
        plan: WorkspaceAssemblyPlan,
    ) -> str:
        lower = normalize_phrase(query)
        topic = plan.workspace.topic or plan.workspace.name
        if activity_type == "assemble":
            return self.persona.report(
                f"Started a {plan.template.title.lower()} workspace for {topic} with {plan.template.purpose_summary}."
            )
        if "where we left off" in lower or "continue" in lower:
            return self.persona.report(
                "Used your recent workspace posture, relevant files, and pending context to restore where you left off."
            )
        if plan.template.key == "troubleshooting":
            return self.persona.report(
                "Staged the current diagnostic surfaces and the most relevant recent materials for the active issue."
            )
        detail = f"Restored the {plan.workspace.name} workspace with the most relevant materials for the current work"
        if plan.likely_next:
            detail += f". Likely next bearing: {plan.likely_next.rstrip('.')}"
        return self.persona.report(detail)

    def _save_snapshot_from_posture(
        self,
        *,
        session_id: str,
        workspace: WorkspaceRecord,
        posture: dict[str, Any],
    ):
        workspace_payload = self._posture_workspace_payload(posture)
        opened_items = self._normalize_item_list(posture.get("opened_items"))
        active_item = posture.get("active_item") if isinstance(posture.get("active_item"), dict) else {}
        pending_next_steps = self._normalize_string_list(posture.get("pending_next_steps") or workspace.pending_next_steps)
        likely_next = str(posture.get("likely_next") or self._likely_next_bearing(
            pending_next_steps=pending_next_steps,
            active_item=active_item,
            opened_items=opened_items,
        ))
        continuity = self._continuity_from_posture(workspace, posture, opened_items, active_item)
        session_posture = self._session_posture_from_posture(workspace, posture)
        where_left_off = str(posture.get("where_left_off") or workspace.where_left_off).strip()
        if not where_left_off:
            where_left_off = self._build_where_left_off(
                workspace_name=workspace.name,
                active_goal=str(posture.get("active_goal") or workspace.active_goal),
                last_completed_action=str(posture.get("last_completed_action") or workspace.last_completed_action),
                pending_next_steps=pending_next_steps,
                active_item=active_item,
            )
        refreshed_workspace = self.repository.upsert_workspace(
            workspace_id=workspace.workspace_id,
            name=workspace.name,
            topic=workspace.topic,
            summary=workspace.summary,
            title=workspace.title or workspace.name,
            status=str(workspace_payload.get("status", workspace.status)),
            category=workspace.category or workspace.topic,
            template_key=str(posture.get("template_key") or workspace.template_key),
            template_source=str(posture.get("template_source") or workspace.template_source),
            problem_domain=str(posture.get("problem_domain") or workspace.problem_domain),
            active_goal=str(posture.get("active_goal") or workspace.active_goal),
            current_task_state=str(posture.get("current_task_state") or workspace.current_task_state),
            last_completed_action=str(posture.get("last_completed_action") or workspace.last_completed_action),
            last_surface_mode=session_posture.surface_mode,
            last_active_module=session_posture.active_module,
            last_active_section=session_posture.active_section,
            pending_next_steps=pending_next_steps,
            references=self._normalize_item_list(posture.get("references") or workspace.references),
            findings=self._normalize_item_list(posture.get("findings") or workspace.findings),
            session_notes=self._normalize_item_list(posture.get("session_notes") or workspace.session_notes or self._workspace_notes(workspace.workspace_id)),
            where_left_off=where_left_off,
            pinned=workspace.pinned,
            archived=workspace.archived,
            archived_at=workspace.archived_at,
            last_snapshot_at=workspace.last_snapshot_at,
            tags=workspace.tags,
        )
        snapshot = self.repository.save_snapshot(
            workspace_id=refreshed_workspace.workspace_id,
            session_id=session_id,
            summary=refreshed_workspace.where_left_off or refreshed_workspace.summary,
            payload={
                "workspace": self._compact_workspace_payload(refreshed_workspace, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT),
                "surface_mode": session_posture.surface_mode,
                "active_module": session_posture.active_module,
                "section": session_posture.active_section,
                "active_goal": refreshed_workspace.active_goal,
                "current_task_state": refreshed_workspace.current_task_state,
                "last_completed_action": refreshed_workspace.last_completed_action,
                "pending_next_steps": refreshed_workspace.pending_next_steps,
                "opened_items": self._bounded_workspace_items(opened_items, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)["items"],
                "active_item": self._compact_workspace_item(active_item),
                "references": self._bounded_workspace_items(refreshed_workspace.references, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)["items"],
                "findings": self._bounded_workspace_items(refreshed_workspace.findings, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)["items"],
                "session_notes": self._bounded_workspace_items(refreshed_workspace.session_notes, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)["items"],
                "where_left_off": refreshed_workspace.where_left_off,
                "problem_domain": refreshed_workspace.problem_domain,
                "template_key": refreshed_workspace.template_key,
                "template_source": refreshed_workspace.template_source,
                "continuity": self._compact_continuity_payload(continuity, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT),
                "session_posture": session_posture.to_dict(),
                "surface_content": self._normalize_surface_content(posture.get("surface_content"))
                or self._surface_content_from_workspace_state(
                    workspace=refreshed_workspace,
                    continuity=continuity,
                    session_posture=session_posture,
                    opened_items=opened_items,
                    active_item=active_item,
                    likely_next=likely_next,
                ),
            },
        )
        self.memory.sync_workspace_memory(
            refreshed_workspace,
            continuity=continuity,
            session_posture=session_posture,
            opened_items=opened_items,
            source_surface="workspace_save_snapshot",
        )
        surface_content = self._normalize_surface_content(posture.get("surface_content")) or self._normalize_surface_content(
            snapshot.payload.get("surface_content")
        )
        capabilities = dict(posture.get("capabilities")) if isinstance(posture.get("capabilities"), dict) else self._workspace_capabilities(
            restore_saved_posture=True
        )
        bounded_opened_items = self._bounded_workspace_items(opened_items, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)["items"]
        bounded_references = self._bounded_workspace_items(refreshed_workspace.references, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)["items"]
        bounded_findings = self._bounded_workspace_items(refreshed_workspace.findings, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)["items"]
        bounded_session_notes = self._bounded_workspace_items(refreshed_workspace.session_notes, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT)["items"]
        bounded_surface_content = self._normalize_surface_content(surface_content)
        self.session_state.set_active_workspace_id(session_id, refreshed_workspace.workspace_id)
        self.session_state.set_active_posture(
            session_id,
            {
                **posture,
                "workspace": self._workspace_view_payload(
                    refreshed_workspace,
                    likely_next=likely_next,
                    where_left_off=refreshed_workspace.where_left_off,
                    pending_next_steps=refreshed_workspace.pending_next_steps,
                    continuity=continuity,
                    session_posture=session_posture,
                    capabilities=capabilities,
                    surface_content=bounded_surface_content,
                ),
                "pending_next_steps": refreshed_workspace.pending_next_steps,
                "opened_items": bounded_opened_items,
                "active_item": self._compact_workspace_item(active_item),
                "references": bounded_references,
                "findings": bounded_findings,
                "session_notes": bounded_session_notes,
                "where_left_off": refreshed_workspace.where_left_off,
                "likely_next": likely_next,
                "template_key": refreshed_workspace.template_key,
                "template_source": refreshed_workspace.template_source,
                "problem_domain": refreshed_workspace.problem_domain,
                "continuity": self._compact_continuity_payload(continuity, limit=WORKSPACE_ACTIVE_CONTEXT_ITEM_LIMIT),
                "session_posture": session_posture.to_dict(),
                "capabilities": capabilities,
                "surface_content": bounded_surface_content,
            },
        )
        return snapshot

    def _posture_workspace_payload(self, posture: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(posture, dict):
            return {}
        workspace_payload = posture.get("workspace")
        if isinstance(workspace_payload, dict):
            return dict(workspace_payload)
        return {}

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
                    "summary": f"Relevant because it matches {topic} bearings in the Logbook.",
                    "content": note.content,
                }
            )
            if len(matches) >= limit:
                break
        return matches

    def _workspace_notes(self, workspace_id: str) -> list[dict[str, Any]]:
        note_ids = set(self.repository.list_linked_notes(workspace_id))
        if not note_ids:
            return []
        notes: list[dict[str, Any]] = []
        for note in self.notes.list_notes(limit=50):
            if note.note_id not in note_ids:
                continue
            notes.append(
                {
                    "noteId": note.note_id,
                    "title": note.title,
                    "content": note.content,
                    "createdAt": note.created_at,
                    "updatedAt": note.updated_at,
                }
            )
        return notes

    def _prepare_item(self, item: dict[str, Any], *, default_module: str) -> dict[str, Any]:
        prepared = dict(item)
        prepared.setdefault("kind", "text")
        prepared.setdefault("viewer", prepared.get("kind", "text"))
        prepared.setdefault("title", "Untitled")
        prepared.setdefault("subtitle", "")
        prepared.setdefault("module", default_module)
        prepared.setdefault("section", "opened-items")
        return prepared

    def _normalize_item_list(self, items: object) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            return []
        return [dict(item) for item in items if isinstance(item, dict)]

    def _normalize_workspace_link_reasons(
        self,
        reasons: list[WorkspaceInclusionReason] | list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for reason in reasons or []:
            if isinstance(reason, WorkspaceInclusionReason):
                normalized.append(reason.to_dict())
                continue
            if not isinstance(reason, dict):
                continue
            payload = {
                "code": str(reason.get("code") or "").strip(),
                "label": str(reason.get("label") or "").strip(),
                "detail": str(reason.get("detail") or "").strip(),
                "score": round(float(reason.get("score", 0.0) or 0.0), 3),
                "source": str(reason.get("source") or "").strip(),
            }
            if payload["code"] and payload["label"] and payload["detail"]:
                normalized.append(payload)
        return normalized

    def _normalize_string_list(self, values: object) -> list[str]:
        if not isinstance(values, list):
            return []
        return [str(value).strip() for value in values if str(value).strip()]

    def _merge_items(self, existing: list[dict[str, Any]], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in [*additions, *existing]:
            item_id = str(item.get("itemId") or item.get("url") or item.get("path") or item.get("title") or "")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            merged.append(dict(item))
        return merged

    def _derive_next_steps(self, prompt: str, active_item: dict[str, Any], opened_items: list[dict[str, Any]]) -> list[str]:
        active_title = str(active_item.get("title", "")).strip()
        steps: list[str] = []
        if active_title:
            steps.append(f"Continue with {active_title}.")
        else:
            topic = self._extract_topic(prompt)
            if topic:
                steps.append(f"Resume the {topic} bearing.")
        if len(opened_items) > 1:
            support_title = str(opened_items[1].get("title", "")).strip()
            if support_title:
                steps.append(f"Cross-check the supporting bearing: {support_title}.")
        if prompt.strip():
            steps.append(self.persona.assumption(prompt.strip()).rstrip("."))
        return steps[:3]

    def _build_where_left_off(
        self,
        *,
        workspace_name: str,
        active_goal: str,
        last_completed_action: str,
        pending_next_steps: list[str],
        active_item: dict[str, Any],
    ) -> str:
        pieces = [f"{workspace_name} is holding"]
        if active_goal:
            pieces.append(active_goal.rstrip("."))
        if last_completed_action:
            pieces.append(f"Last completed action: {last_completed_action.rstrip('.')}")
        active_title = str(active_item.get("title", "")).strip()
        if active_title:
            pieces.append(f"Active item: {active_title}")
        if pending_next_steps:
            pieces.append(f"Likely next step: {pending_next_steps[0].rstrip('.')}")
        return ". ".join(piece for piece in pieces if piece).strip() + "."

    def _extract_topic(self, query: str) -> str:
        topic = normalize_lookup_phrase(query)
        if not topic:
            return "current work"
        filtered_tokens = [
            _TOPIC_TOKEN_NORMALIZATIONS.get(token, token)
            for token in topic.split()
            if token not in _VAGUE_TOPIC_TOKENS and token not in _WORKSPACE_COMMAND_TOKENS
        ]
        filtered = " ".join(filtered_tokens).strip()
        if not filtered or self._is_vague_topic(filtered):
            return "current work"
        return filtered

    def _workspace_view_payload(
        self,
        workspace: WorkspaceRecord,
        *,
        likely_next: str = "",
        where_left_off: str = "",
        pending_next_steps: list[str] | None = None,
        continuity: WorkspaceContinuitySnapshot | None = None,
        session_posture: WorkspaceSessionPosture | None = None,
        capabilities: dict[str, Any] | None = None,
        surface_content: dict[str, Any] | None = None,
        resume_context: WorkspaceResumeContext | None = None,
    ) -> dict[str, Any]:
        payload = self._compact_workspace_payload(workspace)
        if pending_next_steps is not None:
            payload["pendingNextSteps"] = list(pending_next_steps)
        if where_left_off:
            payload["whereLeftOff"] = where_left_off
            payload["summary"] = where_left_off
        if likely_next:
            payload["likelyNext"] = likely_next
        if continuity is not None:
            payload["continuity"] = self._compact_continuity_payload(continuity)
            if continuity.problem_domain:
                payload["problemDomain"] = continuity.problem_domain
        if session_posture is not None:
            payload["sessionPosture"] = session_posture.to_dict()
        if capabilities is not None:
            payload["capabilities"] = dict(capabilities)
        if surface_content is not None:
            payload["surfaceContent"] = self._normalize_surface_content(surface_content)
        if resume_context is not None:
            payload["resumeContext"] = resume_context.to_dict()
        payload["payloadGuardrails"] = self._payload_guardrail_metadata(payload)
        return payload

    def _likely_next_bearing(
        self,
        *,
        pending_next_steps: list[str],
        active_item: dict[str, Any],
        opened_items: list[dict[str, Any]],
    ) -> str:
        if pending_next_steps:
            return str(pending_next_steps[0]).strip()
        active_title = str(active_item.get("title", "")).strip()
        if active_title:
            return f"Continue with {active_title}."
        if opened_items:
            title = str(opened_items[0].get("title", "")).strip()
            if title:
                return f"Reopen {title}."
        return ""

    def _remember_workspace_alias(self, query: str, workspace: WorkspaceRecord) -> None:
        alias = self._extract_topic(query)
        if not alias or alias == "current work":
            return
        self.session_state.remember_alias(
            "workspace",
            alias,
            target={
                "workspaceId": workspace.workspace_id,
                "name": workspace.name,
                "topic": workspace.topic,
            },
        )

    def _needs_restore_clarification(self, top_score: float, second_score: float) -> bool:
        return second_score >= 3.0 and abs(top_score - second_score) <= 0.5

    def _workspace_basis(self, reasons: list[str]) -> str:
        if not reasons:
            return "retained workspace memory"
        primary = reasons[0]
        if primary == "learned alias memory":
            return "learned alias memory"
        if primary == "exact topic bearings":
            return "direct project bearings"
        if primary == "active goal overlap":
            return "active goal bearings"
        if primary == "where-left-off overlap":
            return "where-we-left-off memory"
        if primary == "tag match":
            return "workspace tag bearings"
        if primary == "recent activity":
            return "recent workspace activity"
        return "retained workspace memory"

    def _resolve_assembly_focus(self, *, session_id: str, query: str) -> dict[str, Any]:
        alias_match = self.session_state.resolve_alias("workspace", query)
        if isinstance(alias_match, dict):
            workspace_id = str(alias_match.get("workspaceId", "")).strip()
            if workspace_id:
                workspace = self.repository.get_workspace(workspace_id)
                if workspace is not None:
                    return {"topic": workspace.topic, "workspace": workspace, "basis": "learned alias memory"}
        topic = self._extract_topic(query)
        posture = self.session_state.get_active_posture(session_id)
        active_workspace = self._workspace_from_posture(session_id, posture)
        if topic == "current work" and active_workspace is not None:
            return {"topic": active_workspace.topic or active_workspace.name, "workspace": active_workspace, "basis": "active posture"}
        return {"topic": topic, "workspace": active_workspace if active_workspace and topic == normalize_lookup_phrase(active_workspace.topic) else None}

    def _assembly_search_query(self, *, query: str, topic: str, workspace: WorkspaceRecord | None) -> str:
        terms: list[str] = []
        for candidate in [
            topic,
            query,
            workspace.active_goal if workspace is not None else "",
            workspace.where_left_off if workspace is not None else "",
            " ".join(workspace.tags) if workspace is not None else "",
        ]:
            normalized = normalize_lookup_phrase(candidate)
            if not normalized:
                continue
            for token in normalized.split():
                if token in _VAGUE_TOPIC_TOKENS or len(token) <= 1:
                    continue
                if token not in terms:
                    terms.append(token)
        return " ".join(terms) or topic

    def _is_vague_topic(self, topic: str) -> bool:
        tokens = [token for token in topic.split() if token and token not in _VAGUE_TOPIC_TOKENS]
        if not tokens:
            return True
        return len(tokens) == 1 and tokens[0] in {"current", "work"}
