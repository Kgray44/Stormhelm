from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from stormhelm.core.intelligence.language import fuzzy_ratio, normalize_lookup_phrase, normalize_phrase, token_overlap
from stormhelm.core.memory.models import (
    MemoryFamily,
    MemoryFreshnessState,
    MemoryMatch,
    MemoryProvenance,
    MemoryQuery,
    MemoryRecord,
    MemoryResult,
    MemoryRetrievalIntent,
    MemorySourceClass,
)
from stormhelm.core.memory.repositories import SemanticMemoryRepository
from stormhelm.core.tasks.models import TaskRecord
from stormhelm.core.workspace.models import WorkspaceContinuitySnapshot, WorkspaceRecord, WorkspaceSessionPosture
from stormhelm.shared.time import utc_now_iso


_FAMILY_THRESHOLDS: dict[str, tuple[timedelta, timedelta, timedelta]] = {
    MemoryFamily.SESSION.value: (timedelta(minutes=30), timedelta(hours=6), timedelta(hours=24)),
    MemoryFamily.TASK.value: (timedelta(days=1), timedelta(days=7), timedelta(days=30)),
    MemoryFamily.WORKSPACE.value: (timedelta(days=1), timedelta(days=14), timedelta(days=90)),
    MemoryFamily.PREFERENCE.value: (timedelta(days=30), timedelta(days=180), timedelta(days=365)),
    MemoryFamily.ENVIRONMENT.value: (timedelta(days=1), timedelta(days=30), timedelta(days=120)),
    MemoryFamily.SEMANTIC_RECALL.value: (timedelta(days=14), timedelta(days=180), timedelta(days=540)),
}

_SOURCE_WEIGHTS: dict[str, float] = {
    MemorySourceClass.OPERATOR_PROVIDED.value: 1.0,
    MemorySourceClass.VERIFICATION_BACKED.value: 0.95,
    MemorySourceClass.SYSTEM_OBSERVED.value: 0.9,
    MemorySourceClass.TASK_DERIVED.value: 0.82,
    MemorySourceClass.WORKSPACE_DERIVED.value: 0.78,
    MemorySourceClass.ARTIFACT_DERIVED.value: 0.75,
    MemorySourceClass.IMPORTED.value: 0.62,
    MemorySourceClass.INFERRED.value: 0.45,
}

_FRESHNESS_WEIGHTS: dict[str, float] = {
    MemoryFreshnessState.FRESH.value: 1.0,
    MemoryFreshnessState.AGING.value: 0.72,
    MemoryFreshnessState.STALE.value: 0.42,
    MemoryFreshnessState.EXPIRED.value: 0.18,
    MemoryFreshnessState.HISTORICAL.value: 0.3,
}

_INTENT_FAMILY_PRIORITY: dict[str, dict[str, float]] = {
    MemoryRetrievalIntent.SESSION_CONTINUITY.value: {
        MemoryFamily.SESSION.value: 1.0,
        MemoryFamily.TASK.value: 0.7,
        MemoryFamily.WORKSPACE.value: 0.5,
    },
    MemoryRetrievalIntent.TASK_RESUME.value: {
        MemoryFamily.TASK.value: 1.0,
        MemoryFamily.WORKSPACE.value: 0.75,
        MemoryFamily.SEMANTIC_RECALL.value: 0.55,
        MemoryFamily.SESSION.value: 0.35,
    },
    MemoryRetrievalIntent.WORKSPACE_RESTORE.value: {
        MemoryFamily.WORKSPACE.value: 1.0,
        MemoryFamily.TASK.value: 0.65,
        MemoryFamily.SEMANTIC_RECALL.value: 0.45,
        MemoryFamily.SESSION.value: 0.3,
    },
    MemoryRetrievalIntent.PREFERENCE_LOOKUP.value: {
        MemoryFamily.PREFERENCE.value: 1.0,
    },
    MemoryRetrievalIntent.ENVIRONMENT_LOOKUP.value: {
        MemoryFamily.ENVIRONMENT.value: 1.0,
        MemoryFamily.SEMANTIC_RECALL.value: 0.55,
    },
    MemoryRetrievalIntent.SEMANTIC_RECALL.value: {
        MemoryFamily.SEMANTIC_RECALL.value: 1.0,
        MemoryFamily.TASK.value: 0.5,
        MemoryFamily.WORKSPACE.value: 0.4,
    },
    MemoryRetrievalIntent.MEMORY_CANDIDATE_REVIEW.value: {
        family.value: 0.75 for family in MemoryFamily
    },
    MemoryRetrievalIntent.FUTURE_PROACTIVE_PREFETCH_HOOK.value: {
        MemoryFamily.TASK.value: 0.8,
        MemoryFamily.WORKSPACE.value: 0.75,
        MemoryFamily.PREFERENCE.value: 0.65,
        MemoryFamily.ENVIRONMENT.value: 0.6,
        MemoryFamily.SEMANTIC_RECALL.value: 0.6,
    },
}

_GENERIC_NOISE = {
    "",
    "done",
    "ok",
    "okay",
    "queued",
    "completed",
    "running",
    "success",
    "finished",
    "all set",
    "standing by",
}

_SESSION_RETENTION_WINDOW = timedelta(hours=48)
_SESSION_RECORD_LIMIT = 64
_QUERY_LOG_RETENTION_WINDOW = timedelta(days=14)
_QUERY_LOG_LIMIT = 64
_SUPPRESSED_PREVIEW_LIMIT = 12


class SemanticMemoryService:
    def __init__(self, repository: SemanticMemoryRepository) -> None:
        self.repository = repository
        self._last_retention_cleanup: dict[str, int] = {
            "sessionRecordsPruned": 0,
            "queryLogPruned": 0,
        }

    def remember_session_tool_result(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_family: str,
        arguments: dict[str, object],
        result: dict[str, object] | None,
        captured_at: str | None,
    ) -> MemoryRecord | None:
        timestamp = captured_at or utc_now_iso()
        summary = str((result or {}).get("summary") or "").strip()
        data = dict((result or {}).get("data") or {}) if isinstance((result or {}).get("data"), dict) else {}
        if self._reject_noisy_summary(summary) and not data:
            return None
        record = MemoryRecord(
            memory_id=str(uuid4()),
            dedupe_key="",
            memory_family=MemoryFamily.SESSION.value,
            source_class=MemorySourceClass.SYSTEM_OBSERVED.value,
            title=f"{tool_name.replace('_', ' ').title()} result",
            summary=summary or f"Recent {tool_name.replace('_', ' ')} result.",
            normalized_content=self._normalized_content(
                summary,
                tool_name,
                tool_family,
                " ".join(f"{key} {value}" for key, value in arguments.items()),
                " ".join(f"{key} {value}" for key, value in data.items() if not isinstance(value, (dict, list))),
            ),
            structured_fields={
                "kind": "recent_tool_result",
                "tool_name": tool_name,
                "tool_family": tool_family,
                "arguments": dict(arguments),
                "result": dict(result or {}),
                "captured_at": timestamp,
            },
            provenance=MemoryProvenance(
                origin_subsystem="session_state",
                origin_surface="tool_result",
                verification_state="observed",
                source_session_ref=session_id,
            ),
            confidence=0.82 if summary else 0.68,
            created_at=timestamp,
            updated_at=timestamp,
            last_validated_at=timestamp,
            retention_policy="session_window",
            related_session_id=session_id,
            tags=["recent_tool_result", tool_name, tool_family],
            semantic_tokens=self._semantic_tokens(summary, tool_name, tool_family),
        )
        saved = self.repository.save_record(self._with_freshness(record))
        self._prune_session_records()
        return saved

    def list_recent_session_tool_results(
        self,
        session_id: str,
        *,
        max_age_seconds: float | None = None,
    ) -> list[dict[str, object]]:
        records = self.repository.list_records(
            families=[MemoryFamily.SESSION.value],
            related_session_id=session_id,
            limit=64,
        )
        entries: list[dict[str, object]] = []
        threshold = None
        if max_age_seconds is not None:
            threshold = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        for record in records:
            if record.structured_fields.get("kind") != "recent_tool_result":
                continue
            captured_at = str(record.structured_fields.get("captured_at") or record.updated_at)
            if threshold is not None:
                parsed = self._parse_timestamp(captured_at)
                if parsed is None or parsed < threshold:
                    continue
            entry = {
                "tool_name": str(record.structured_fields.get("tool_name") or ""),
                "family": str(record.structured_fields.get("tool_family") or ""),
                "arguments": dict(record.structured_fields.get("arguments") or {})
                if isinstance(record.structured_fields.get("arguments"), dict)
                else {},
                "result": dict(record.structured_fields.get("result") or {})
                if isinstance(record.structured_fields.get("result"), dict)
                else {},
                "captured_at": captured_at,
            }
            entries.append(entry)
            if len(entries) >= 12:
                break
        return entries

    def remember_context_resolution(self, session_id: str, resolution: dict[str, object]) -> MemoryRecord | None:
        summary = str(resolution.get("summary") or resolution.get("detail") or "").strip()
        if self._reject_noisy_summary(summary) and not resolution:
            return None
        timestamp = utc_now_iso()
        record = MemoryRecord(
            memory_id=str(uuid4()),
            memory_family=MemoryFamily.SESSION.value,
            source_class=MemorySourceClass.SYSTEM_OBSERVED.value,
            title="Context resolution",
            summary=summary or "Stored recent context resolution.",
            normalized_content=self._normalized_content(summary, " ".join(f"{key} {value}" for key, value in resolution.items())),
            structured_fields={
                "kind": "context_resolution",
                "resolution": dict(resolution),
                "captured_at": timestamp,
            },
            provenance=MemoryProvenance(
                origin_subsystem="session_state",
                origin_surface="context_resolution",
                verification_state="observed",
                source_session_ref=session_id,
            ),
            confidence=0.75,
            created_at=timestamp,
            updated_at=timestamp,
            last_validated_at=timestamp,
            retention_policy="session_window",
            related_session_id=session_id,
            tags=["context_resolution"],
            semantic_tokens=self._semantic_tokens(summary),
        )
        saved = self.repository.save_record(self._with_freshness(record))
        self._prune_session_records()
        return saved

    def list_recent_context_resolutions(self, session_id: str) -> list[dict[str, object]]:
        records = self.repository.list_records(
            families=[MemoryFamily.SESSION.value],
            related_session_id=session_id,
            limit=24,
        )
        results: list[dict[str, object]] = []
        for record in records:
            if record.structured_fields.get("kind") != "context_resolution":
                continue
            resolution = dict(record.structured_fields.get("resolution") or {})
            resolution["captured_at"] = str(record.structured_fields.get("captured_at") or record.updated_at)
            results.append(resolution)
            if len(results) >= 8:
                break
        return results

    def remember_alias(self, category: str, alias: str, *, target: dict[str, object]) -> MemoryRecord | None:
        normalized_alias = normalize_lookup_phrase(alias) or normalize_phrase(alias)
        if not normalized_alias:
            return None
        existing = self.repository.get_by_dedupe_key(f"alias:{category}:{normalized_alias}")
        previous_target = dict(existing.structured_fields.get("target") or {}) if existing is not None else {}
        count = int((existing.structured_fields.get("count") if existing is not None else 0) or 0) + 1
        record = MemoryRecord(
            memory_id=existing.memory_id if existing is not None else str(uuid4()),
            dedupe_key=f"alias:{category}:{normalized_alias}",
            memory_family=MemoryFamily.PREFERENCE.value,
            source_class=MemorySourceClass.INFERRED.value,
            title=f"{category.replace('_', ' ').title()} alias",
            summary=f"Alias '{normalized_alias}' points to remembered {category.replace('_', ' ')} context.",
            normalized_content=self._normalized_content(
                normalized_alias,
                str(target.get("name") or ""),
                str(target.get("topic") or ""),
                str(target.get("workspaceId") or target.get("taskId") or ""),
            ),
            structured_fields={
                "kind": "alias",
                "category": category,
                "alias": normalized_alias,
                "target": {**previous_target, **dict(target)},
                "count": count,
                "last_used_at": utc_now_iso(),
            },
            provenance=MemoryProvenance(
                origin_subsystem="session_state",
                origin_surface="alias_learning",
                inferred=True,
                verification_state="observed",
            ),
            confidence=min(0.4 + (0.1 * count), 0.85),
            created_at=existing.created_at if existing is not None else utc_now_iso(),
            updated_at=utc_now_iso(),
            retention_policy="durable_preference",
            related_workspace_ids=[
                str(target.get("workspaceId")).strip()
                for _ in [0]
                if str(target.get("workspaceId") or "").strip()
            ],
            related_task_ids=[
                str(target.get("taskId")).strip()
                for _ in [0]
                if str(target.get("taskId") or "").strip()
            ],
            tags=["alias", category],
            semantic_tokens=self._semantic_tokens(normalized_alias, str(target.get("name") or ""), str(target.get("topic") or "")),
        )
        return self.repository.save_record(self._with_freshness(record))

    def list_aliases(self, category: str) -> dict[str, dict[str, object]]:
        records = self.repository.list_records(families=[MemoryFamily.PREFERENCE.value], limit=250)
        aliases: dict[str, dict[str, object]] = {}
        for record in records:
            if record.structured_fields.get("kind") != "alias":
                continue
            if str(record.structured_fields.get("category") or "") != category:
                continue
            alias = str(record.structured_fields.get("alias") or "").strip()
            if not alias:
                continue
            aliases[alias] = {
                **dict(record.structured_fields.get("target") or {}),
                "alias": alias,
                "count": int(record.structured_fields.get("count", 0) or 0),
                "last_used_at": str(record.structured_fields.get("last_used_at") or record.updated_at),
                "source_class": record.source_class,
            }
        return aliases

    def resolve_alias(self, category: str, phrase: str, *, threshold: float = 0.84) -> dict[str, object] | None:
        normalized = normalize_lookup_phrase(phrase) or normalize_phrase(phrase)
        if not normalized:
            return None
        aliases = self.list_aliases(category)
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

    def remember_preference(
        self,
        scope: str,
        key: str,
        value: object,
        *,
        source_class: str = MemorySourceClass.OPERATOR_PROVIDED.value,
        operator_locked: bool = False,
    ) -> MemoryRecord:
        dedupe_key = f"preference:{scope}:{key}"
        existing = self.repository.get_by_dedupe_key(dedupe_key)
        previous_value = existing.structured_fields.get("value") if existing is not None else None
        if existing is not None and previous_value == value:
            count = int(existing.structured_fields.get("count", 0) or 0) + 1
        else:
            count = 1
        timestamp = utc_now_iso()
        record = MemoryRecord(
            memory_id=existing.memory_id if existing is not None else str(uuid4()),
            dedupe_key=dedupe_key,
            memory_family=MemoryFamily.PREFERENCE.value,
            source_class=source_class,
            title=f"{scope.replace('_', ' ').title()} preference",
            summary=f"Saved preference for {scope.replace('_', ' ')}: {key.replace('_', ' ')}.",
            normalized_content=self._normalized_content(scope, key, str(value)),
            structured_fields={
                "kind": "preference",
                "scope": scope,
                "key": key,
                "value": value,
                "count": count,
                "operator_locked": operator_locked,
                "updated_at": timestamp,
            },
            provenance=MemoryProvenance(
                origin_subsystem="session_state",
                origin_surface="preference_learning",
                operator_provided=(source_class == MemorySourceClass.OPERATOR_PROVIDED.value),
                inferred=(source_class == MemorySourceClass.INFERRED.value),
                verification_state="observed",
            ),
            confidence=self._preference_confidence(count=count, source_class=source_class, operator_locked=operator_locked),
            created_at=existing.created_at if existing is not None else timestamp,
            updated_at=timestamp,
            last_validated_at=timestamp,
            retention_policy="durable_preference",
            tags=["preference", scope, key],
            semantic_tokens=self._semantic_tokens(scope, key, str(value)),
        )
        return self.repository.save_record(self._with_freshness(record))

    def get_learned_preferences(self) -> dict[str, dict[str, object]]:
        records = self.repository.list_records(families=[MemoryFamily.PREFERENCE.value], limit=250)
        preferences: dict[str, dict[str, object]] = {}
        for record in records:
            if record.structured_fields.get("kind") != "preference":
                continue
            scope = str(record.structured_fields.get("scope") or "").strip()
            key = str(record.structured_fields.get("key") or "").strip()
            if not scope or not key:
                continue
            preferences.setdefault(scope, {})[key] = {
                "value": record.structured_fields.get("value"),
                "count": int(record.structured_fields.get("count", 0) or 0),
                "updated_at": str(record.structured_fields.get("updated_at") or record.updated_at),
                "confidence": round(float(record.confidence), 3),
                "source_class": record.source_class,
                "operator_locked": bool(record.structured_fields.get("operator_locked", False)),
            }
        return preferences

    def preference_value(self, scope: str, key: str, *, minimum_count: int = 1) -> object | None:
        learned = self.get_learned_preferences().get(scope, {})
        if not isinstance(learned, dict):
            return None
        entry = learned.get(key)
        if not isinstance(entry, dict):
            return None
        if int(entry.get("count", 0) or 0) < minimum_count:
            return None
        return entry.get("value")

    def remember_environment_observation(
        self,
        *,
        environment_key: str,
        machine_scope: str,
        app_scope: str,
        observed_pattern: str,
        confidence: float = 0.72,
        source_class: str = MemorySourceClass.SYSTEM_OBSERVED.value,
        revalidation_needed: bool = False,
        tags: list[str] | None = None,
        related_workspace_ids: list[str] | None = None,
        related_task_ids: list[str] | None = None,
        created_at: str | None = None,
        last_seen_at: str | None = None,
    ) -> MemoryRecord | None:
        if self._reject_noisy_summary(observed_pattern):
            return None
        dedupe_key = f"environment:{machine_scope}:{app_scope}:{environment_key}"
        existing = self.repository.get_by_dedupe_key(dedupe_key)
        timestamp = last_seen_at or utc_now_iso()
        first_seen = created_at or (existing.created_at if existing is not None else timestamp)
        record = MemoryRecord(
            memory_id=existing.memory_id if existing is not None else str(uuid4()),
            dedupe_key=dedupe_key,
            memory_family=MemoryFamily.ENVIRONMENT.value,
            source_class=source_class,
            title=f"{app_scope or machine_scope or 'Environment'} quirk",
            summary=observed_pattern.strip(),
            normalized_content=self._normalized_content(environment_key, machine_scope, app_scope, observed_pattern),
            structured_fields={
                "kind": "environment_observation",
                "environment_key": environment_key,
                "machine_scope": machine_scope,
                "app_scope": app_scope,
                "observed_pattern": observed_pattern.strip(),
                "first_seen_at": first_seen,
                "last_seen_at": timestamp,
                "revalidation_needed": revalidation_needed,
            },
            provenance=MemoryProvenance(
                origin_subsystem="memory",
                origin_surface="environment_observation",
                inferred=(source_class == MemorySourceClass.INFERRED.value),
                verification_state="observed" if source_class != MemorySourceClass.INFERRED.value else "inferred",
            ),
            confidence=confidence,
            created_at=first_seen,
            updated_at=timestamp,
            last_validated_at=timestamp if source_class != MemorySourceClass.INFERRED.value else "",
            retention_policy="environment_revalidation",
            related_workspace_ids=list(related_workspace_ids or []),
            related_task_ids=list(related_task_ids or []),
            tags=["environment", environment_key, *(tags or [])],
            semantic_tokens=self._semantic_tokens(environment_key, machine_scope, app_scope, observed_pattern),
        )
        return self.repository.save_record(self._with_freshness(record))

    def remember_semantic_recall(
        self,
        *,
        summary: str,
        canonical_entities: list[str] | None = None,
        linked_tasks: list[str] | None = None,
        linked_workspaces: list[str] | None = None,
        linked_artifacts: list[str] | None = None,
        source_class: str = MemorySourceClass.VERIFICATION_BACKED.value,
        provenance: MemoryProvenance | None = None,
        dedupe_key: str = "",
        confidence: float = 0.78,
    ) -> MemoryRecord | None:
        if self._reject_noisy_summary(summary):
            return None
        timestamp = utc_now_iso()
        record = MemoryRecord(
            memory_id=str(uuid4()),
            dedupe_key=dedupe_key,
            memory_family=MemoryFamily.SEMANTIC_RECALL.value,
            source_class=source_class,
            title="Semantic recall card",
            summary=summary.strip(),
            normalized_content=self._normalized_content(summary, " ".join(canonical_entities or [])),
            structured_fields={
                "kind": "semantic_recall_card",
                "canonical_entities": list(canonical_entities or []),
            },
            provenance=provenance or MemoryProvenance(
                origin_subsystem="memory",
                origin_surface="semantic_recall",
                inferred=(source_class == MemorySourceClass.INFERRED.value),
                verification_state="verified" if source_class == MemorySourceClass.VERIFICATION_BACKED.value else "derived",
            ),
            confidence=confidence,
            created_at=timestamp,
            updated_at=timestamp,
            last_validated_at=timestamp if source_class == MemorySourceClass.VERIFICATION_BACKED.value else "",
            retention_policy="semantic_recall",
            related_task_ids=list(linked_tasks or []),
            related_workspace_ids=list(linked_workspaces or []),
            related_artifact_refs=list(linked_artifacts or []),
            tags=["semantic_recall", *(canonical_entities or [])[:6]],
            semantic_tokens=self._semantic_tokens(summary, " ".join(canonical_entities or [])),
        )
        return self.repository.save_record(self._with_freshness(record))

    def sync_task_memory(self, task: TaskRecord, *, next_steps: list[str] | None = None) -> MemoryRecord:
        verification_backed = any(entry.kind == "verification" for entry in task.evidence)
        summary = task.where_left_off or task.latest_summary or task.summary
        record = MemoryRecord(
            memory_id=str(uuid4()),
            dedupe_key=f"task:{task.task_id}",
            memory_family=MemoryFamily.TASK.value,
            source_class=MemorySourceClass.TASK_DERIVED.value,
            title=task.title,
            summary=summary,
            normalized_content=self._normalized_content(
                task.title,
                task.goal,
                task.summary,
                task.latest_summary,
                task.evidence_summary,
                task.where_left_off,
                " ".join(step.title for step in task.steps),
                " ".join(blocker.title for blocker in task.blockers),
            ),
            structured_fields={
                "kind": "task_memory",
                "task_id": task.task_id,
                "workspace_id": task.workspace_id,
                "state": task.state,
                "goal": task.goal,
                "latest_summary": task.latest_summary,
                "evidence_summary": task.evidence_summary,
                "where_left_off": task.where_left_off,
                "active_step_id": task.active_step_id,
                "last_completed_step_id": task.last_completed_step_id,
                "steps": [step.to_dict(job_links=task.job_links) for step in task.steps],
                "blockers": [blocker.to_dict() for blocker in task.blockers],
                "checkpoints": [checkpoint.to_dict() for checkpoint in task.checkpoints],
                "artifacts": [artifact.to_dict() for artifact in task.artifacts],
                "evidence": [entry.to_dict() for entry in task.evidence],
                "next_steps": list(next_steps or []),
            },
            provenance=MemoryProvenance(
                origin_subsystem="tasks",
                origin_surface="task_graph",
                verification_state="verified" if verification_backed else "derived",
                source_task_ref=task.task_id,
                source_workspace_ref=task.workspace_id,
                source_session_ref=task.session_id,
            ),
            confidence=0.9 if verification_backed else 0.82,
            created_at=task.created_at or utc_now_iso(),
            updated_at=task.updated_at or utc_now_iso(),
            last_validated_at=task.finished_at if verification_backed else task.updated_at,
            retention_policy="task_resume",
            related_session_id=task.session_id,
            related_task_ids=[task.task_id],
            related_workspace_ids=[task.workspace_id] if task.workspace_id else [],
            related_artifact_refs=[artifact.locator for artifact in task.artifacts if artifact.locator],
            tags=["task", task.state, *(["verification_backed"] if verification_backed else [])],
            semantic_tokens=self._semantic_tokens(task.title, task.goal, task.summary, task.evidence_summary, task.where_left_off),
        )
        saved = self.repository.save_record(self._with_freshness(record))
        if verification_backed and task.evidence_summary.strip():
            self.remember_semantic_recall(
                summary=task.evidence_summary.strip(),
                canonical_entities=[task.title],
                linked_tasks=[task.task_id],
                linked_workspaces=[task.workspace_id] if task.workspace_id else [],
                linked_artifacts=[artifact.locator for artifact in task.artifacts if artifact.locator],
                provenance=MemoryProvenance(
                    origin_subsystem="tasks",
                    origin_surface="verification",
                    verification_state="verified",
                    source_task_ref=task.task_id,
                    source_workspace_ref=task.workspace_id,
                    source_session_ref=task.session_id,
                ),
                dedupe_key=f"semantic_recall:task:{task.task_id}",
                confidence=0.84,
            )
        return saved

    def sync_workspace_memory(
        self,
        workspace: WorkspaceRecord,
        *,
        continuity: WorkspaceContinuitySnapshot | None = None,
        session_posture: WorkspaceSessionPosture | None = None,
        opened_items: list[dict[str, Any]] | None = None,
        source_surface: str = "workspace_context",
    ) -> MemoryRecord:
        continuity = continuity or WorkspaceContinuitySnapshot()
        opened_items = list(opened_items or [])
        record = MemoryRecord(
            memory_id=str(uuid4()),
            dedupe_key=f"workspace:{workspace.workspace_id}",
            memory_family=MemoryFamily.WORKSPACE.value,
            source_class=MemorySourceClass.WORKSPACE_DERIVED.value,
            title=workspace.name,
            summary=workspace.where_left_off or workspace.summary,
            normalized_content=self._normalized_content(
                workspace.name,
                workspace.topic,
                workspace.summary,
                workspace.active_goal,
                workspace.current_task_state,
                workspace.where_left_off,
                " ".join(workspace.pending_next_steps),
                " ".join(item.get("title", "") for item in opened_items if isinstance(item, dict)),
            ),
            structured_fields={
                "kind": "workspace_memory",
                "workspace_id": workspace.workspace_id,
                "topic": workspace.topic,
                "status": workspace.status,
                "category": workspace.category,
                "template_key": workspace.template_key,
                "template_source": workspace.template_source,
                "problem_domain": workspace.problem_domain,
                "active_goal": continuity.active_goal or workspace.active_goal,
                "current_task_state": continuity.current_task_state or workspace.current_task_state,
                "last_completed_action": continuity.last_completed_action or workspace.last_completed_action,
                "pending_next_steps": list(continuity.pending_next_steps or workspace.pending_next_steps),
                "where_left_off": continuity.where_left_off or workspace.where_left_off,
                "references": list(continuity.references or workspace.references),
                "findings": list(continuity.findings or workspace.findings),
                "session_notes": list(continuity.session_notes or workspace.session_notes),
                "opened_items": opened_items,
                "session_posture": session_posture.to_dict() if session_posture is not None else {},
            },
            provenance=MemoryProvenance(
                origin_subsystem="workspace",
                origin_surface=source_surface,
                verification_state="derived",
                source_workspace_ref=workspace.workspace_id,
            ),
            confidence=0.8 if workspace.last_snapshot_at else 0.74,
            created_at=workspace.created_at or utc_now_iso(),
            updated_at=workspace.updated_at or utc_now_iso(),
            last_validated_at=workspace.last_snapshot_at or workspace.updated_at,
            retention_policy="workspace_restore",
            related_workspace_ids=[workspace.workspace_id],
            tags=["workspace", workspace.template_key or workspace.category or workspace.topic],
            semantic_tokens=self._semantic_tokens(
                workspace.name,
                workspace.topic,
                workspace.active_goal,
                workspace.current_task_state,
                workspace.where_left_off,
            ),
        )
        return self.repository.save_record(self._with_freshness(record))

    def retrieve(self, query: MemoryQuery) -> MemoryResult:
        requested_families = list(query.requested_families or self._default_families(query.retrieval_intent))
        candidates = self.repository.list_records(families=requested_families, limit=300)
        filtered_out: Counter[str] = Counter()
        matches: list[MemoryMatch] = []
        suppressed_preview: list[dict[str, Any]] = []
        semantic_query = normalize_lookup_phrase(query.semantic_query_text) or normalize_phrase(query.semantic_query_text)
        for candidate in candidates:
            candidate = self._with_freshness(candidate)
            semantic_alignment = self._semantic_alignment(semantic_query, candidate)
            scope_reasons = self._scope_mismatch_reasons(candidate, query.scope_constraints, semantic_alignment=semantic_alignment)
            if scope_reasons:
                filtered_out["scope_mismatch"] += 1
                self._append_suppressed_preview(
                    suppressed_preview,
                    candidate,
                    reasons=scope_reasons,
                    reason_category="scope",
                    semantic_alignment=semantic_alignment,
                )
                continue
            if self._explicit_filter_mismatch(candidate, query.structured_filters):
                filtered_out["structured_filter"] += 1
                continue
            if candidate.confidence < float(query.confidence_floor or 0.0):
                filtered_out["confidence_floor"] += 1
                continue
            if self._blocked_by_freshness(candidate, query):
                filtered_out["freshness_gate"] += 1
                continue
            score, reasons, conflicts = self._score_record(
                candidate,
                query,
                semantic_query=semantic_query,
                semantic_alignment=semantic_alignment,
            )
            suppression_reasons = self._current_evidence_suppression_reasons(candidate, query, conflicts)
            if suppression_reasons:
                filtered_out["current_evidence_suppressed"] += 1
                self._append_suppressed_preview(
                    suppressed_preview,
                    candidate,
                    reasons=suppression_reasons,
                    reason_category="current_evidence",
                    semantic_alignment=semantic_alignment,
                    current_evidence_conflicts=conflicts,
                )
                continue
            if score <= 0.0:
                filtered_out["relevance_floor"] += 1
                continue
            matches.append(
                MemoryMatch(
                    record=candidate,
                    score=score,
                    ranking_reasons=reasons,
                    current_evidence_conflicts=conflicts,
                )
            )

        family_conflicts = self._apply_family_conflict_hardening(matches, query)
        matches = [match for match in matches if match.score > 0.0]
        matches.sort(key=lambda match: match.score, reverse=True)
        top_matches = matches[:8]
        for match in top_matches:
            self.repository.mark_accessed(match.record.memory_id)

        family_distribution = Counter(match.record.memory_family for match in top_matches)
        freshness_summary = Counter(match.record.freshness_state for match in top_matches)
        confidence_summary = Counter(self._confidence_bucket(match.record.confidence) for match in top_matches)
        result = MemoryResult(
            result_id=str(uuid4()),
            matched_records=top_matches,
            ranking_reasons={match.record.memory_id: list(match.ranking_reasons) for match in top_matches},
            family_distribution=dict(family_distribution),
            filtered_out_counts=dict(filtered_out),
            freshness_summary=dict(freshness_summary),
            confidence_summary=dict(confidence_summary),
            safe_user_visible_summary=self._safe_user_summary(top_matches, suppressed_preview=suppressed_preview),
            retrieval_trace={
                "intent": query.retrieval_intent,
                "familiesSearched": requested_families,
                "queryText": query.semantic_query_text,
                "scopeConstraints": dict(query.scope_constraints),
                "structuredFilters": dict(query.structured_filters),
                "matchedRecordIds": [match.record.memory_id for match in top_matches],
                "rankingPreview": [
                    {
                        "memoryId": match.record.memory_id,
                        "family": match.record.memory_family,
                        "score": round(float(match.score), 3),
                        "reasons": list(match.ranking_reasons),
                        "currentEvidenceConflicts": list(match.current_evidence_conflicts),
                    }
                    for match in top_matches
                ],
                "suppressedPreview": list(suppressed_preview),
                "familyConflicts": family_conflicts,
                "conflictSummary": {
                    "currentEvidenceSuppressions": int(filtered_out.get("current_evidence_suppressed", 0)),
                    "scopeMismatches": int(filtered_out.get("scope_mismatch", 0)),
                    "familyConflictCount": len(family_conflicts),
                    "matchedConflictCount": sum(1 for match in top_matches if match.current_evidence_conflicts),
                },
                "retentionCleanup": {
                    "queryLogPruned": 0,
                },
                "filteredOutCounts": dict(filtered_out),
            },
        )
        self.repository.log_query(query, result)
        query_log_pruned = self._prune_query_logs()
        result.retrieval_trace["retentionCleanup"]["queryLogPruned"] = query_log_pruned
        self.repository.update_query_trace(query.query_id, result.retrieval_trace)
        return result

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "families": self.repository.count_by_family(),
            "recentQueries": self.repository.list_recent_queries(limit=5),
            "retention": {
                "sessionRecordCap": _SESSION_RECORD_LIMIT,
                "queryLogCap": _QUERY_LOG_LIMIT,
                "lastCleanup": dict(self._last_retention_cleanup),
            },
        }

    def _default_families(self, retrieval_intent: str) -> list[str]:
        priorities = _INTENT_FAMILY_PRIORITY.get(retrieval_intent, {})
        if priorities:
            return list(priorities.keys())
        return [family.value for family in MemoryFamily]

    def _score_record(
        self,
        record: MemoryRecord,
        query: MemoryQuery,
        *,
        semantic_query: str,
        semantic_alignment: dict[str, float] | None = None,
    ) -> tuple[float, list[str], list[str]]:
        reasons: list[str] = []
        score = 0.0

        family_weight = _INTENT_FAMILY_PRIORITY.get(query.retrieval_intent, {}).get(record.memory_family, 0.15)
        score += family_weight * 3.2
        reasons.append(f"family:{record.memory_family}")

        source_weight = _SOURCE_WEIGHTS.get(record.source_class, 0.3)
        score += source_weight * 1.8
        reasons.append(f"source:{record.source_class}")

        freshness_weight = _FRESHNESS_WEIGHTS.get(record.freshness_state, 0.3)
        score += freshness_weight * 1.7
        reasons.append(f"freshness:{record.freshness_state or 'unknown'}")

        score += max(0.0, min(float(record.confidence), 1.0)) * 1.6
        reasons.append(f"confidence:{round(float(record.confidence), 2)}")

        score += self._scope_boost(record, query.scope_constraints, reasons)
        score += self._structured_match_boost(record, query.structured_filters, reasons)

        if semantic_query:
            alignment = semantic_alignment or self._semantic_alignment(semantic_query, record)
            overlap = float(alignment.get("overlap", 0.0) or 0.0)
            fuzzy = float(alignment.get("fuzzy", 0.0) or 0.0)
            semantic_score = float(alignment.get("combined", 0.0) or 0.0)
            score += semantic_score
            if overlap:
                reasons.append(f"token_overlap:{round(overlap, 2)}")
            if fuzzy:
                reasons.append(f"fuzzy:{round(fuzzy, 2)}")
        score -= self._semantic_scope_truth_penalty(record, query.scope_constraints, reasons)

        conflicts = self._current_evidence_conflicts(record, query.structured_filters)
        if conflicts:
            score -= 3.25
            reasons.append("current_evidence_conflict")
            if record.freshness_state in {MemoryFreshnessState.STALE.value, MemoryFreshnessState.EXPIRED.value}:
                score -= 0.9
                reasons.append("penalty:stale_conflict")
            if record.freshness_state == MemoryFreshnessState.HISTORICAL.value:
                score -= 0.75
                reasons.append("penalty:historical_conflict")
        if record.memory_family == MemoryFamily.PREFERENCE.value and record.structured_fields.get("kind") == "alias":
            score -= 0.15
        if record.source_class == MemorySourceClass.INFERRED.value and query.retrieval_intent in {
            MemoryRetrievalIntent.PREFERENCE_LOOKUP.value,
            MemoryRetrievalIntent.ENVIRONMENT_LOOKUP.value,
        }:
            score -= 0.8
        if record.freshness_state in {MemoryFreshnessState.EXPIRED.value, MemoryFreshnessState.HISTORICAL.value} and query.retrieval_intent in {
            MemoryRetrievalIntent.TASK_RESUME.value,
            MemoryRetrievalIntent.WORKSPACE_RESTORE.value,
            MemoryRetrievalIntent.ENVIRONMENT_LOOKUP.value,
        }:
            score -= 0.75
        return score, reasons, conflicts

    def _semantic_alignment(self, semantic_query: str, record: MemoryRecord) -> dict[str, float]:
        if not semantic_query:
            return {"overlap": 0.0, "fuzzy": 0.0, "combined": 0.0}
        overlap = token_overlap(semantic_query, record.normalized_content or record.summary or record.title)
        fuzzy = max(
            fuzzy_ratio(semantic_query, record.title or ""),
            fuzzy_ratio(semantic_query, record.summary or ""),
            fuzzy_ratio(semantic_query, record.normalized_content or ""),
        )
        return {
            "overlap": overlap,
            "fuzzy": fuzzy,
            "combined": (overlap * 2.2) + (fuzzy * 1.8),
        }

    def _scope_boost(self, record: MemoryRecord, scope_constraints: dict[str, Any], reasons: list[str]) -> float:
        boost = 0.0
        task_id = str(scope_constraints.get("task_id") or "").strip()
        workspace_id = str(scope_constraints.get("workspace_id") or "").strip()
        session_id = str(scope_constraints.get("session_id") or "").strip()
        if task_id and task_id in record.related_task_ids:
            boost += 3.0
            reasons.append("scope:task")
        if workspace_id and workspace_id in record.related_workspace_ids:
            boost += 2.7
            reasons.append("scope:workspace")
        if session_id and session_id == record.related_session_id:
            boost += 1.5
            reasons.append("scope:session")
        return boost

    def _semantic_scope_truth_penalty(
        self,
        record: MemoryRecord,
        scope_constraints: dict[str, Any],
        reasons: list[str],
    ) -> float:
        if record.memory_family != MemoryFamily.SEMANTIC_RECALL.value:
            return 0.0
        penalty = 0.0
        task_id = str(scope_constraints.get("task_id") or "").strip()
        workspace_id = str(scope_constraints.get("workspace_id") or "").strip()
        if task_id and not record.related_task_ids:
            penalty += 1.05
            reasons.append("scope:task_unanchored")
        if workspace_id and not record.related_workspace_ids:
            penalty += 0.95
            reasons.append("scope:workspace_unanchored")
        return penalty

    def _structured_match_boost(self, record: MemoryRecord, structured_filters: dict[str, Any], reasons: list[str]) -> float:
        boost = 0.0
        preference_key = str(structured_filters.get("preference_key") or "").strip()
        environment_key = str(structured_filters.get("environment_key") or "").strip()
        tags = structured_filters.get("tags")
        source_classes = structured_filters.get("source_classes")
        if preference_key:
            record_key = ""
            if record.structured_fields.get("kind") == "preference":
                record_key = f"{record.structured_fields.get('scope')}.{record.structured_fields.get('key')}"
            if preference_key == record_key:
                boost += 5.0
                reasons.append("structured:preference_key")
        if environment_key and str(record.structured_fields.get("environment_key") or "") == environment_key:
            boost += 5.0
            reasons.append("structured:environment_key")
        if isinstance(tags, list):
            tag_hits = len(set(str(tag).strip() for tag in tags if str(tag).strip()) & set(record.tags))
            if tag_hits:
                boost += min(tag_hits * 0.6, 1.8)
                reasons.append(f"structured:tags:{tag_hits}")
        if isinstance(source_classes, list) and record.source_class in {str(item).strip() for item in source_classes if str(item).strip()}:
            boost += 0.6
            reasons.append("structured:source_class")
        return boost

    def _current_evidence_conflicts(self, record: MemoryRecord, structured_filters: dict[str, Any]) -> list[str]:
        current_values = structured_filters.get("current_values")
        if not isinstance(current_values, dict):
            return []
        conflicts: list[str] = []
        for key, current_value in current_values.items():
            remembered = record.structured_fields.get(key)
            if remembered in (None, "", [], {}):
                continue
            if normalize_phrase(str(remembered)) != normalize_phrase(str(current_value)):
                conflicts.append(str(key))
        return conflicts

    def _scope_mismatch(self, record: MemoryRecord, scope_constraints: dict[str, Any]) -> bool:
        return bool(self._scope_mismatch_reasons(record, scope_constraints))

    def _scope_mismatch_reasons(
        self,
        record: MemoryRecord,
        scope_constraints: dict[str, Any],
        *,
        semantic_alignment: dict[str, float] | None = None,
    ) -> list[str]:
        reasons: list[str] = []
        task_id = str(scope_constraints.get("task_id") or "").strip()
        if task_id and record.related_task_ids and task_id not in record.related_task_ids:
            reasons.append("scope_mismatch")
        workspace_id = str(scope_constraints.get("workspace_id") or "").strip()
        if workspace_id and record.related_workspace_ids and workspace_id not in record.related_workspace_ids:
            reasons.append("scope_mismatch")
        session_id = str(scope_constraints.get("session_id") or "").strip()
        if session_id and record.related_session_id and record.related_session_id != session_id and record.memory_family == MemoryFamily.SESSION.value:
            reasons.append("scope_mismatch")
        if reasons and record.memory_family == MemoryFamily.SEMANTIC_RECALL.value:
            alignment = semantic_alignment or {"combined": 0.0, "fuzzy": 0.0}
            if float(alignment.get("combined", 0.0) or 0.0) > 0.0:
                reasons.append("semantic_scope_truthfulness")
        return reasons

    def _explicit_filter_mismatch(self, record: MemoryRecord, structured_filters: dict[str, Any]) -> bool:
        families = structured_filters.get("families")
        if isinstance(families, list) and record.memory_family not in {str(item).strip() for item in families if str(item).strip()}:
            return True
        source_classes = structured_filters.get("source_classes")
        if isinstance(source_classes, list) and record.source_class not in {str(item).strip() for item in source_classes if str(item).strip()}:
            return True
        record_kind = str(record.structured_fields.get("kind") or "")
        required_kind = str(structured_filters.get("kind") or "").strip()
        if required_kind and record_kind and record_kind != required_kind:
            return True
        return False

    def _blocked_by_freshness(self, record: MemoryRecord, query: MemoryQuery) -> bool:
        mode = str(query.freshness_requirements.get("mode") or "").strip().lower()
        if not mode:
            return False
        if mode == "fresh_only":
            return record.freshness_state not in {
                MemoryFreshnessState.FRESH.value,
                MemoryFreshnessState.AGING.value,
            }
        if mode == "no_expired":
            return record.freshness_state == MemoryFreshnessState.EXPIRED.value
        return False

    def _safe_user_summary(
        self,
        matches: list[MemoryMatch],
        *,
        suppressed_preview: list[dict[str, Any]] | None = None,
    ) -> str:
        if not matches:
            suppressed_preview = list(suppressed_preview or [])
            if suppressed_preview:
                first = suppressed_preview[0]
                reasons = {str(reason) for reason in first.get("reasons", []) if str(reason).strip()}
                if "preference_conflicts_with_current_evidence" in reasons:
                    return "Current evidence outranked an older saved preference."
                if "environment_conflicts_with_runtime_state" in reasons:
                    return "Current runtime state outranked an older environment note."
                if "semantic_scope_truthfulness" in reasons or "scope_mismatch" in reasons:
                    return "I found related prior memory, but it did not match the current scope closely enough to trust."
            return ""
        pieces: list[str] = []
        for match in matches[:3]:
            record = match.record
            label = self._family_label(record.memory_family)
            summary = record.summary.strip() or record.title.strip()
            if not summary:
                continue
            if record.source_class == MemorySourceClass.INFERRED.value:
                pieces.append(f"{label} inference: {summary}")
            elif record.memory_family == MemoryFamily.ENVIRONMENT.value and record.freshness_state in {
                MemoryFreshnessState.STALE.value,
                MemoryFreshnessState.EXPIRED.value,
            }:
                pieces.append(f"{label} note that may be stale: {summary}")
            elif match.current_evidence_conflicts:
                pieces.append(f"{label} memory may conflict with current evidence: {summary}")
            elif record.memory_family == MemoryFamily.PREFERENCE.value:
                pieces.append(f"Saved preference: {summary}")
            elif record.memory_family == MemoryFamily.TASK.value:
                pieces.append(f"Task memory: {summary}")
            elif record.memory_family == MemoryFamily.WORKSPACE.value:
                pieces.append(f"Workspace memory: {summary}")
            elif record.memory_family == MemoryFamily.SESSION.value:
                pieces.append(f"Current session memory: {summary}")
            else:
                pieces.append(f"{label}: {summary}")
        return " | ".join(pieces[:3])

    def _family_label(self, family: str) -> str:
        labels = {
            MemoryFamily.SESSION.value: "session memory",
            MemoryFamily.TASK.value: "task memory",
            MemoryFamily.WORKSPACE.value: "workspace memory",
            MemoryFamily.PREFERENCE.value: "preference memory",
            MemoryFamily.ENVIRONMENT.value: "environment memory",
            MemoryFamily.SEMANTIC_RECALL.value: "prior related recall",
        }
        return labels.get(family, family.replace("_", " "))

    def _confidence_bucket(self, confidence: float) -> str:
        if confidence >= 0.8:
            return "high"
        if confidence >= 0.55:
            return "medium"
        return "low"

    def _preference_confidence(self, *, count: int, source_class: str, operator_locked: bool) -> float:
        base = 0.52 if source_class == MemorySourceClass.OPERATOR_PROVIDED.value else 0.38
        if operator_locked:
            base += 0.2
        return min(base + (0.1 * min(count, 4)), 0.96)

    def _reject_noisy_summary(self, text: str) -> bool:
        normalized = normalize_lookup_phrase(text) or normalize_phrase(text)
        if normalized in _GENERIC_NOISE:
            return True
        return len(normalized.split()) < 2 and len(normalized) < 12

    def _normalized_content(self, *parts: object) -> str:
        text = " ".join(str(part).strip() for part in parts if str(part).strip())
        return normalize_lookup_phrase(text) or normalize_phrase(text)

    def _semantic_tokens(self, *parts: object) -> list[str]:
        normalized = self._normalized_content(*parts)
        if not normalized:
            return []
        tokens = [token for token in normalized.split() if token and token not in {"the", "and", "for", "with", "from"}]
        deduped: list[str] = []
        for token in tokens:
            if token not in deduped:
                deduped.append(token)
        return deduped[:24]

    def _with_freshness(self, record: MemoryRecord) -> MemoryRecord:
        record.freshness_state = self._freshness_state(record)
        return record

    def _freshness_state(self, record: MemoryRecord) -> str:
        thresholds = _FAMILY_THRESHOLDS.get(record.memory_family)
        if thresholds is None:
            return MemoryFreshnessState.HISTORICAL.value
        anchor = record.last_validated_at or record.updated_at or record.created_at
        parsed = self._parse_timestamp(anchor)
        if parsed is None:
            return MemoryFreshnessState.HISTORICAL.value
        age = datetime.now(timezone.utc) - parsed
        fresh, aging, stale = thresholds
        if age <= fresh:
            return MemoryFreshnessState.FRESH.value
        if age <= aging:
            return MemoryFreshnessState.AGING.value
        if age <= stale:
            return MemoryFreshnessState.STALE.value
        if record.memory_family in {MemoryFamily.PREFERENCE.value, MemoryFamily.SEMANTIC_RECALL.value}:
            return MemoryFreshnessState.HISTORICAL.value
        return MemoryFreshnessState.EXPIRED.value

    def _parse_timestamp(self, raw: str) -> datetime | None:
        value = str(raw or "").strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _prune_session_records(self) -> None:
        cutoff = (datetime.now(timezone.utc) - _SESSION_RETENTION_WINDOW).isoformat()
        deleted = self.repository.delete_records_before(family=MemoryFamily.SESSION.value, cutoff=cutoff)
        trimmed = self.repository.trim_records(family=MemoryFamily.SESSION.value, limit=_SESSION_RECORD_LIMIT)
        self._last_retention_cleanup["sessionRecordsPruned"] = deleted + trimmed

    def _prune_query_logs(self) -> int:
        cutoff = (datetime.now(timezone.utc) - _QUERY_LOG_RETENTION_WINDOW).isoformat()
        deleted = self.repository.delete_query_logs_before(cutoff=cutoff)
        trimmed = self.repository.trim_query_log(limit=_QUERY_LOG_LIMIT)
        total = deleted + trimmed
        self._last_retention_cleanup["queryLogPruned"] = total
        return total

    def _current_evidence_suppression_reasons(
        self,
        record: MemoryRecord,
        query: MemoryQuery,
        conflicts: list[str],
    ) -> list[str]:
        if not conflicts:
            return []
        reasons: list[str] = []
        freshness_risky = record.freshness_state in {
            MemoryFreshnessState.AGING.value,
            MemoryFreshnessState.STALE.value,
            MemoryFreshnessState.EXPIRED.value,
            MemoryFreshnessState.HISTORICAL.value,
        }
        if (
            record.memory_family == MemoryFamily.PREFERENCE.value
            and query.retrieval_intent == MemoryRetrievalIntent.PREFERENCE_LOOKUP.value
            and "value" in conflicts
            and (
                freshness_risky
                or record.source_class == MemorySourceClass.INFERRED.value
                or not bool(record.structured_fields.get("operator_locked", False))
            )
        ):
            reasons.append("preference_conflicts_with_current_evidence")
        if (
            record.memory_family == MemoryFamily.ENVIRONMENT.value
            and query.retrieval_intent == MemoryRetrievalIntent.ENVIRONMENT_LOOKUP.value
            and conflicts
            and (
                (
                    freshness_risky
                    and str(query.structured_filters.get("environment_key") or "").strip()
                )
                or bool(record.structured_fields.get("revalidation_needed", False))
                or record.source_class == MemorySourceClass.INFERRED.value
            )
        ):
            reasons.append("environment_conflicts_with_runtime_state")
        return reasons

    def _append_suppressed_preview(
        self,
        preview: list[dict[str, Any]],
        record: MemoryRecord,
        *,
        reasons: list[str],
        reason_category: str,
        semantic_alignment: dict[str, float] | None = None,
        current_evidence_conflicts: list[str] | None = None,
    ) -> None:
        if len(preview) >= _SUPPRESSED_PREVIEW_LIMIT:
            return
        preview.append(
            {
                "memoryId": record.memory_id,
                "family": record.memory_family,
                "sourceClass": record.source_class,
                "freshness": record.freshness_state,
                "reasonCategory": reason_category,
                "reasons": list(reasons),
                "currentEvidenceConflicts": list(current_evidence_conflicts or []),
                "semanticAlignment": {
                    "overlap": round(float((semantic_alignment or {}).get("overlap", 0.0) or 0.0), 3),
                    "fuzzy": round(float((semantic_alignment or {}).get("fuzzy", 0.0) or 0.0), 3),
                    "combined": round(float((semantic_alignment or {}).get("combined", 0.0) or 0.0), 3),
                },
            }
        )

    def _apply_family_conflict_hardening(
        self,
        matches: list[MemoryMatch],
        query: MemoryQuery,
    ) -> list[dict[str, Any]]:
        if query.retrieval_intent not in {
            MemoryRetrievalIntent.TASK_RESUME.value,
            MemoryRetrievalIntent.WORKSPACE_RESTORE.value,
        }:
            return []
        task_match = max(
            (match for match in matches if match.record.memory_family == MemoryFamily.TASK.value),
            key=lambda match: match.score,
            default=None,
        )
        workspace_match = max(
            (match for match in matches if match.record.memory_family == MemoryFamily.WORKSPACE.value),
            key=lambda match: match.score,
            default=None,
        )
        if task_match is None or workspace_match is None:
            return []
        shared_scope = self._shared_task_workspace_scope(task_match.record, workspace_match.record, query.scope_constraints)
        if not shared_scope:
            return []
        disagreement_reasons = self._task_workspace_disagreement(task_match.record, workspace_match.record)
        if not disagreement_reasons:
            return []
        if query.retrieval_intent == MemoryRetrievalIntent.TASK_RESUME.value:
            preferred = task_match
            demoted = workspace_match
        else:
            preferred = workspace_match
            demoted = task_match
        demoted.score -= 1.85
        demoted.ranking_reasons.append(f"cross_family_disagreement:{demoted.record.memory_family}")
        preferred.ranking_reasons.append(f"cross_family_anchor:{preferred.record.memory_family}")
        return [
            {
                "preferredFamily": preferred.record.memory_family,
                "preferredMemoryId": preferred.record.memory_id,
                "demotedFamily": demoted.record.memory_family,
                "demotedMemoryId": demoted.record.memory_id,
                "sharedScope": shared_scope,
                "reasons": disagreement_reasons,
            }
        ]

    def _shared_task_workspace_scope(
        self,
        task_record: MemoryRecord,
        workspace_record: MemoryRecord,
        scope_constraints: dict[str, Any],
    ) -> dict[str, str]:
        workspace_id = str(scope_constraints.get("workspace_id") or "").strip()
        task_workspace_id = str(task_record.structured_fields.get("workspace_id") or "").strip()
        workspace_memory_id = str(workspace_record.structured_fields.get("workspace_id") or "").strip()
        if workspace_id and workspace_id == task_workspace_id and workspace_id == workspace_memory_id:
            return {"workspace_id": workspace_id}
        if task_workspace_id and task_workspace_id == workspace_memory_id:
            return {"workspace_id": task_workspace_id}
        return {}

    def _task_workspace_disagreement(
        self,
        task_record: MemoryRecord,
        workspace_record: MemoryRecord,
    ) -> list[str]:
        task_signal = self._normalized_content(
            task_record.summary,
            str(task_record.structured_fields.get("goal") or ""),
            str(task_record.structured_fields.get("latest_summary") or ""),
            str(task_record.structured_fields.get("where_left_off") or ""),
            " ".join(str(value) for value in task_record.structured_fields.get("next_steps", []) or []),
        )
        workspace_signal = self._normalized_content(
            workspace_record.summary,
            str(workspace_record.structured_fields.get("active_goal") or ""),
            str(workspace_record.structured_fields.get("where_left_off") or ""),
            " ".join(str(value) for value in workspace_record.structured_fields.get("pending_next_steps", []) or []),
        )
        if not task_signal or not workspace_signal:
            return []
        disagreement_reasons: list[str] = []
        if fuzzy_ratio(task_signal, workspace_signal) < 0.55 and token_overlap(task_signal, workspace_signal) < 0.35:
            disagreement_reasons.append("continuity_diverged")
        return disagreement_reasons
