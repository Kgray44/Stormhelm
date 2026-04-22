from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    title: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class ChatMessageRecord:
    message_id: str
    session_id: str
    role: str
    content: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class NoteRecord:
    note_id: str
    title: str
    content: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class MemoryFamily(str, Enum):
    SESSION = "session"
    TASK = "task"
    WORKSPACE = "workspace"
    PREFERENCE = "preference"
    ENVIRONMENT = "environment"
    SEMANTIC_RECALL = "semantic_recall"


class MemorySourceClass(str, Enum):
    OPERATOR_PROVIDED = "operator_provided"
    SYSTEM_OBSERVED = "system_observed"
    TASK_DERIVED = "task_derived"
    WORKSPACE_DERIVED = "workspace_derived"
    VERIFICATION_BACKED = "verification_backed"
    ARTIFACT_DERIVED = "artifact_derived"
    IMPORTED = "imported"
    INFERRED = "inferred"


class MemoryFreshnessState(str, Enum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    EXPIRED = "expired"
    HISTORICAL = "historical"


class MemoryRetrievalIntent(str, Enum):
    SESSION_CONTINUITY = "session_continuity"
    TASK_RESUME = "task_resume"
    WORKSPACE_RESTORE = "workspace_restore"
    PREFERENCE_LOOKUP = "preference_lookup"
    ENVIRONMENT_LOOKUP = "environment_lookup"
    SEMANTIC_RECALL = "semantic_recall"
    MEMORY_CANDIDATE_REVIEW = "memory_candidate_review"
    FUTURE_PROACTIVE_PREFETCH_HOOK = "future_proactive_prefetch_hook"


@dataclass(slots=True)
class MemoryProvenance:
    origin_subsystem: str = ""
    origin_surface: str = ""
    operator_provided: bool = False
    inferred: bool = False
    verification_state: str = "unverified"
    source_artifact_refs: list[str] = field(default_factory=list)
    source_event_refs: list[str] = field(default_factory=list)
    source_task_ref: str = ""
    source_workspace_ref: str = ""
    source_session_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "originSubsystem": self.origin_subsystem,
            "originSurface": self.origin_surface,
            "operatorProvided": self.operator_provided,
            "inferred": self.inferred,
            "verificationState": self.verification_state,
            "sourceArtifactRefs": list(self.source_artifact_refs),
            "sourceEventRefs": list(self.source_event_refs),
            "sourceTaskRef": self.source_task_ref,
            "sourceWorkspaceRef": self.source_workspace_ref,
            "sourceSessionRef": self.source_session_ref,
        }


@dataclass(slots=True)
class MemoryRecord:
    memory_id: str
    memory_family: str
    source_class: str
    title: str = ""
    summary: str = ""
    normalized_content: str = ""
    structured_fields: dict[str, Any] = field(default_factory=dict)
    provenance: MemoryProvenance = field(default_factory=MemoryProvenance)
    confidence: float = 0.0
    freshness_state: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_validated_at: str = ""
    retention_policy: str = ""
    sensitivity_level: str = "normal"
    related_session_id: str = ""
    related_task_ids: list[str] = field(default_factory=list)
    related_workspace_ids: list[str] = field(default_factory=list)
    related_artifact_refs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    dedupe_key: str = ""
    semantic_tokens: list[str] = field(default_factory=list)
    last_accessed_at: str = ""
    access_count: int = 0
    archived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "memoryId": self.memory_id,
            "memoryFamily": self.memory_family,
            "sourceClass": self.source_class,
            "title": self.title,
            "summary": self.summary,
            "normalizedContent": self.normalized_content,
            "structuredFields": dict(self.structured_fields),
            "provenance": self.provenance.to_dict(),
            "confidence": round(float(self.confidence), 3),
            "freshnessState": self.freshness_state,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "lastValidatedAt": self.last_validated_at,
            "retentionPolicy": self.retention_policy,
            "sensitivityLevel": self.sensitivity_level,
            "relatedSessionId": self.related_session_id,
            "relatedTaskIds": list(self.related_task_ids),
            "relatedWorkspaceIds": list(self.related_workspace_ids),
            "relatedArtifactRefs": list(self.related_artifact_refs),
            "tags": list(self.tags),
            "dedupeKey": self.dedupe_key,
            "semanticTokens": list(self.semantic_tokens),
            "lastAccessedAt": self.last_accessed_at,
            "accessCount": self.access_count,
            "archived": self.archived,
        }


@dataclass(slots=True)
class MemoryQuery:
    query_id: str
    retrieval_intent: str
    requested_families: list[str] = field(default_factory=list)
    semantic_query_text: str = ""
    structured_filters: dict[str, Any] = field(default_factory=dict)
    freshness_requirements: dict[str, Any] = field(default_factory=dict)
    confidence_floor: float = 0.0
    scope_constraints: dict[str, Any] = field(default_factory=dict)
    caller_subsystem: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "queryId": self.query_id,
            "retrievalIntent": self.retrieval_intent,
            "requestedFamilies": list(self.requested_families),
            "semanticQueryText": self.semantic_query_text,
            "structuredFilters": dict(self.structured_filters),
            "freshnessRequirements": dict(self.freshness_requirements),
            "confidenceFloor": round(float(self.confidence_floor), 3),
            "scopeConstraints": dict(self.scope_constraints),
            "callerSubsystem": self.caller_subsystem,
        }


@dataclass(slots=True)
class MemoryMatch:
    record: MemoryRecord
    score: float
    ranking_reasons: list[str] = field(default_factory=list)
    current_evidence_conflicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.to_dict(),
            "score": round(float(self.score), 3),
            "rankingReasons": list(self.ranking_reasons),
            "currentEvidenceConflicts": list(self.current_evidence_conflicts),
        }


@dataclass(slots=True)
class MemoryResult:
    result_id: str
    matched_records: list[MemoryMatch] = field(default_factory=list)
    ranking_reasons: dict[str, list[str]] = field(default_factory=dict)
    family_distribution: dict[str, int] = field(default_factory=dict)
    filtered_out_counts: dict[str, int] = field(default_factory=dict)
    freshness_summary: dict[str, int] = field(default_factory=dict)
    confidence_summary: dict[str, int] = field(default_factory=dict)
    safe_user_visible_summary: str = ""
    retrieval_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resultId": self.result_id,
            "matchedRecords": [match.to_dict() for match in self.matched_records],
            "rankingReasons": {key: list(value) for key, value in self.ranking_reasons.items()},
            "familyDistribution": dict(self.family_distribution),
            "filteredOutCounts": dict(self.filtered_out_counts),
            "freshnessSummary": dict(self.freshness_summary),
            "confidenceSummary": dict(self.confidence_summary),
            "safeUserVisibleSummary": self.safe_user_visible_summary,
            "retrievalTrace": dict(self.retrieval_trace),
        }


@dataclass(slots=True)
class PreferenceRecord:
    preference_key: str
    value: Any
    confidence: float
    source_class: str
    operator_locked: bool = False
    last_confirmed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "preferenceKey": self.preference_key,
            "value": self.value,
            "confidence": round(float(self.confidence), 3),
            "sourceClass": self.source_class,
            "operatorLocked": self.operator_locked,
            "lastConfirmedAt": self.last_confirmed_at,
        }


@dataclass(slots=True)
class EnvironmentObservationRecord:
    environment_key: str
    machine_scope: str = ""
    app_scope: str = ""
    observed_pattern: str = ""
    confidence: float = 0.0
    first_seen_at: str = ""
    last_seen_at: str = ""
    revalidation_needed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "environmentKey": self.environment_key,
            "machineScope": self.machine_scope,
            "appScope": self.app_scope,
            "observedPattern": self.observed_pattern,
            "confidence": round(float(self.confidence), 3),
            "firstSeenAt": self.first_seen_at,
            "lastSeenAt": self.last_seen_at,
            "revalidationNeeded": self.revalidation_needed,
        }


@dataclass(slots=True)
class SemanticRecallCard:
    card_id: str
    summary: str
    canonical_entities: list[str] = field(default_factory=list)
    semantic_embedding_ref: str = ""
    provenance: MemoryProvenance = field(default_factory=MemoryProvenance)
    freshness: str = ""
    linked_artifacts: list[str] = field(default_factory=list)
    linked_tasks: list[str] = field(default_factory=list)
    linked_workspaces: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cardId": self.card_id,
            "summary": self.summary,
            "canonicalEntities": list(self.canonical_entities),
            "semanticEmbeddingRef": self.semantic_embedding_ref,
            "provenance": self.provenance.to_dict(),
            "freshness": self.freshness,
            "linkedArtifacts": list(self.linked_artifacts),
            "linkedTasks": list(self.linked_tasks),
            "linkedWorkspaces": list(self.linked_workspaces),
        }
