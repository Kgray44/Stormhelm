from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class SearchResult:
    domain: str
    title: str
    subtitle: str
    score: float
    target: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    kind: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "title": self.title,
            "subtitle": self.subtitle,
            "score": round(float(self.score), 3),
            "target": dict(self.target),
            "reasons": list(self.reasons),
            "kind": self.kind,
            "metadata": dict(self.metadata),
        }


class AccessFailureReason(str, Enum):
    UNRESOLVED_FOLDER = "unresolved_folder"
    FOLDER_INACCESSIBLE = "folder_inaccessible"
    NO_STRONG_MATCH = "no_strong_folder_match"
    MULTIPLE_STRONG_MATCHES = "multiple_strong_folder_matches"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"


@dataclass(slots=True)
class KnownFolderResolution:
    requested: str
    key: str
    label: str
    path: str | None
    source: str = "known_folder"
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "key": self.key,
            "label": self.label,
            "path": self.path,
            "source": self.source,
            "aliases": list(self.aliases),
        }


@dataclass(slots=True)
class FolderAccessStatus:
    state: str
    path: str | None
    allowed: bool
    reason: str
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "path": self.path,
            "allowed": self.allowed,
            "reason": self.reason,
            "failure_reason": self.failure_reason,
        }


@dataclass(slots=True)
class FileSearchScope:
    root_path: str
    query: str
    folder_hint: str
    prefer_folders: bool
    latest_only: bool
    requested_extensions: list[str] = field(default_factory=list)
    max_depth: int = 3
    max_entries: int = 300

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_path": self.root_path,
            "query": self.query,
            "folder_hint": self.folder_hint,
            "prefer_folders": self.prefer_folders,
            "latest_only": self.latest_only,
            "requested_extensions": list(self.requested_extensions),
            "max_depth": self.max_depth,
            "max_entries": self.max_entries,
        }


@dataclass(slots=True)
class FuzzyMatchScore:
    total: float
    phrase: float = 0.0
    coverage: float = 0.0
    overlap: float = 0.0
    fuzzy: float = 0.0
    keyword_bonus: float = 0.0
    type_bonus: float = 0.0
    folder_bonus: float = 0.0
    recency_bonus: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": round(float(self.total), 3),
            "phrase": round(float(self.phrase), 3),
            "coverage": round(float(self.coverage), 3),
            "overlap": round(float(self.overlap), 3),
            "fuzzy": round(float(self.fuzzy), 3),
            "keyword_bonus": round(float(self.keyword_bonus), 3),
            "type_bonus": round(float(self.type_bonus), 3),
            "folder_bonus": round(float(self.folder_bonus), 3),
            "recency_bonus": round(float(self.recency_bonus), 3),
        }


@dataclass(slots=True)
class FuzzyFileCandidate:
    title: str
    path: str
    is_dir: bool
    score: FuzzyMatchScore
    reasons: list[str] = field(default_factory=list)
    extension: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "path": self.path,
            "is_dir": self.is_dir,
            "score": self.score.to_dict(),
            "reasons": list(self.reasons),
            "extension": self.extension,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class FileResolutionDecision:
    state: str
    chosen_candidate: FuzzyFileCandidate | None = None
    candidates: list[FuzzyFileCandidate] = field(default_factory=list)
    clarification_required: bool = False
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "chosen_candidate": self.chosen_candidate.to_dict() if self.chosen_candidate is not None else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "clarification_required": self.clarification_required,
            "failure_reason": self.failure_reason,
        }


@dataclass(slots=True)
class SearchWithinFolderPlan:
    known_folder: KnownFolderResolution | None
    access_status: FolderAccessStatus
    scope: FileSearchScope | None
    decision: FileResolutionDecision

    def to_dict(self) -> dict[str, Any]:
        return {
            "known_folder": self.known_folder.to_dict() if self.known_folder is not None else None,
            "access_status": self.access_status.to_dict(),
            "scope": self.scope.to_dict() if self.scope is not None else None,
            "decision": self.decision.to_dict(),
        }


@dataclass(slots=True)
class WorkflowStep:
    title: str
    kind: str
    parameters: dict[str, Any] = field(default_factory=dict)
    required: bool = False
    step_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "pending"
    summary: str = ""
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stepId": self.step_id,
            "title": self.title,
            "kind": self.kind,
            "parameters": dict(self.parameters),
            "required": self.required,
            "status": self.status,
            "summary": self.summary,
            "error": self.error,
            "data": dict(self.data),
        }


@dataclass(slots=True)
class ActionChain:
    title: str
    kind: str
    steps: list[WorkflowStep]
    chain_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "pending"
    current_step_index: int = -1
    partial: bool = False
    summary: str = ""

    def progress_payload(self) -> dict[str, Any]:
        return {
            "chainId": self.chain_id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "current_step_index": self.current_step_index,
            "completed_steps": sum(1 for step in self.steps if step.status == "completed"),
            "total_steps": len(self.steps),
            "partial": self.partial,
            "summary": self.summary,
            "steps": [step.to_dict() for step in self.steps],
        }
