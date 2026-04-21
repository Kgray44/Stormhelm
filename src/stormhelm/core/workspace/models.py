from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkspaceRecord:
    workspace_id: str
    name: str
    topic: str
    summary: str
    title: str = ""
    status: str = ""
    category: str = ""
    template_key: str = ""
    template_source: str = ""
    problem_domain: str = ""
    active_goal: str = ""
    current_task_state: str = ""
    last_completed_action: str = ""
    last_surface_mode: str = ""
    last_active_module: str = ""
    last_active_section: str = ""
    pending_next_steps: list[str] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    session_notes: list[dict[str, Any]] = field(default_factory=list)
    where_left_off: str = ""
    pinned: bool = False
    archived: bool = False
    archived_at: str = ""
    last_snapshot_at: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    last_opened_at: str = ""

    @property
    def current_status(self) -> str:
        return self.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspaceId": self.workspace_id,
            "name": self.name,
            "topic": self.topic,
            "summary": self.summary,
            "title": self.title,
            "status": self.status,
            "category": self.category,
            "templateKey": self.template_key,
            "templateSource": self.template_source,
            "problemDomain": self.problem_domain,
            "activeGoal": self.active_goal,
            "currentTaskState": self.current_task_state,
            "lastCompletedAction": self.last_completed_action,
            "lastSurfaceMode": self.last_surface_mode,
            "lastActiveModule": self.last_active_module,
            "lastActiveSection": self.last_active_section,
            "pendingNextSteps": list(self.pending_next_steps),
            "references": list(self.references),
            "findings": list(self.findings),
            "sessionNotes": list(self.session_notes),
            "whereLeftOff": self.where_left_off,
            "pinned": self.pinned,
            "archived": self.archived,
            "archivedAt": self.archived_at,
            "lastSnapshotAt": self.last_snapshot_at,
            "tags": list(self.tags),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "lastOpenedAt": self.last_opened_at,
        }


@dataclass(slots=True)
class WorkspaceItemRecord:
    item_id: str
    workspace_id: str
    item_key: str
    kind: str
    viewer: str
    title: str
    subtitle: str
    module_key: str
    section_key: str
    url: str
    path: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    opened_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    last_opened_at: str = ""

    def to_action_item(self) -> dict[str, Any]:
        payload = dict(self.metadata)
        payload.setdefault("itemId", self.item_id)
        payload.setdefault("kind", self.kind)
        payload.setdefault("viewer", self.viewer)
        payload.setdefault("title", self.title)
        payload.setdefault("subtitle", self.subtitle)
        payload.setdefault("module", self.module_key)
        if self.url:
            payload.setdefault("url", self.url)
        if self.path:
            payload.setdefault("path", self.path)
        if self.summary:
            payload.setdefault("summary", self.summary)
        return payload


@dataclass(slots=True)
class WorkspaceSnapshotRecord:
    snapshot_id: str
    workspace_id: str
    session_id: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshotId": self.snapshot_id,
            "workspaceId": self.workspace_id,
            "sessionId": self.session_id,
            "summary": self.summary,
            "payload": dict(self.payload),
            "createdAt": self.created_at,
        }


@dataclass(slots=True)
class WorkspaceTemplateDefinition:
    key: str
    title: str
    description: str
    aliases: list[str] = field(default_factory=list)
    default_module: str = "chartroom"
    default_section: str = "overview"
    emphasis: list[str] = field(default_factory=list)
    search_keywords: list[str] = field(default_factory=list)
    preferred_extensions: list[str] = field(default_factory=list)
    surface_weights: dict[str, float] = field(default_factory=dict)
    purpose_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "aliases": list(self.aliases),
            "defaultModule": self.default_module,
            "defaultSection": self.default_section,
            "emphasis": list(self.emphasis),
            "searchKeywords": list(self.search_keywords),
            "preferredExtensions": list(self.preferred_extensions),
            "surfaceWeights": dict(self.surface_weights),
            "purposeSummary": self.purpose_summary,
        }


@dataclass(slots=True)
class WorkspaceInclusionReason:
    code: str
    label: str
    detail: str
    score: float = 0.0
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "detail": self.detail,
            "score": round(float(self.score), 3),
            "source": self.source,
        }


@dataclass(slots=True)
class WorkspaceRoleCluster:
    surface: str
    title: str
    purpose: str
    presentation_kind: str
    items: list[dict[str, Any]] = field(default_factory=list)
    debug_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "title": self.title,
            "purpose": self.purpose,
            "presentationKind": self.presentation_kind,
            "items": list(self.items),
            "debugReasons": list(self.debug_reasons),
        }


@dataclass(slots=True)
class WorkspaceContinuitySnapshot:
    active_goal: str = ""
    current_task_state: str = ""
    last_completed_action: str = ""
    pending_next_steps: list[str] = field(default_factory=list)
    where_left_off: str = ""
    problem_domain: str = ""
    active_item: dict[str, Any] = field(default_factory=dict)
    opened_items: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    session_notes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activeGoal": self.active_goal,
            "currentTaskState": self.current_task_state,
            "lastCompletedAction": self.last_completed_action,
            "pendingNextSteps": list(self.pending_next_steps),
            "whereLeftOff": self.where_left_off,
            "problemDomain": self.problem_domain,
            "activeItem": dict(self.active_item),
            "openedItems": list(self.opened_items),
            "references": list(self.references),
            "findings": list(self.findings),
            "sessionNotes": list(self.session_notes),
        }


@dataclass(slots=True)
class WorkspaceSessionPosture:
    surface_mode: str = "deck"
    active_module: str = "chartroom"
    active_section: str = "overview"
    emphasis: list[str] = field(default_factory=list)
    restored_from_saved_posture: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "surfaceMode": self.surface_mode,
            "activeModule": self.active_module,
            "activeSection": self.active_section,
            "emphasis": list(self.emphasis),
            "restoredFromSavedPosture": self.restored_from_saved_posture,
        }


@dataclass(slots=True)
class WorkspaceResumeContext:
    source: str = "template_defaults"
    basis: str = ""
    used_saved_posture: bool = False
    used_template_defaults: bool = True
    restored_fields: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "basis": self.basis,
            "usedSavedPosture": self.used_saved_posture,
            "usedTemplateDefaults": self.used_template_defaults,
            "restoredFields": list(self.restored_fields),
            "limitations": list(self.limitations),
        }


@dataclass(slots=True)
class WorkspaceAssemblyPlan:
    workspace: WorkspaceRecord
    template: WorkspaceTemplateDefinition
    template_confidence: float
    template_reasons: list[str]
    opened_items: list[dict[str, Any]]
    active_item_id: str
    clusters: list[WorkspaceRoleCluster]
    continuity: WorkspaceContinuitySnapshot
    session_posture: WorkspaceSessionPosture
    resume_context: WorkspaceResumeContext
    capabilities: dict[str, Any]
    likely_next: str = ""
    debug: dict[str, Any] = field(default_factory=dict)

    def surface_content(self) -> dict[str, Any]:
        return {cluster.surface: cluster.to_dict() for cluster in self.clusters}

    def to_workspace_payload(self) -> dict[str, Any]:
        payload = self.workspace.to_dict()
        payload.update(
            {
                "templateKey": self.template.key,
                "templateTitle": self.template.title,
                "templateSource": self.workspace.template_source or "",
                "templateConfidence": round(float(self.template_confidence), 3),
                "templateReasons": list(self.template_reasons),
                "continuity": self.continuity.to_dict(),
                "sessionPosture": self.session_posture.to_dict(),
                "resumeContext": self.resume_context.to_dict(),
                "capabilities": dict(self.capabilities),
                "surfaceContent": self.surface_content(),
                "likelyNext": self.likely_next,
            }
        )
        return payload
