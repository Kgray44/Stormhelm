from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DiagnosticEvidenceBundle:
    metrics: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics": dict(self.metrics),
            "limitations": list(self.limitations),
        }


@dataclass(slots=True)
class DiagnosticFinding:
    kind: str
    headline: str
    summary: str
    severity: str = "steady"
    confidence: str = "moderate"
    label: str = ""
    evidence: DiagnosticEvidenceBundle = field(default_factory=DiagnosticEvidenceBundle)
    next_checks: list[str] = field(default_factory=list)

    def to_dict(self, *, key: str | None = None, label: str | None = None) -> dict[str, Any]:
        return {
            "key": key or self.kind,
            "label": label or self.label or self.headline,
            "kind": self.kind,
            "headline": self.headline,
            "summary": self.summary,
            "severity": self.severity,
            "confidence": self.confidence,
            "evidence": self.evidence.to_dict(),
            "next_checks": list(self.next_checks),
        }


@dataclass(slots=True)
class OperationalSignal:
    title: str
    detail: str
    severity: str = "steady"
    category: str = "operations"
    source: str = "systems"
    meta: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "detail": self.detail,
            "severity": self.severity,
            "category": self.category,
            "source": self.source,
            "meta": self.meta,
        }


@dataclass(slots=True)
class TaskProgressSnapshot:
    title: str
    status: str
    detail: str
    severity: str = "steady"
    meta: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "severity": self.severity,
            "meta": self.meta,
        }


@dataclass(slots=True)
class WatchStateSnapshot:
    active_jobs: int
    queued_jobs: int
    recent_failures: int
    completed_recently: int
    worker_capacity: int
    default_timeout_seconds: float
    tasks: list[TaskProgressSnapshot] = field(default_factory=list)
    headline: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_jobs": self.active_jobs,
            "queued_jobs": self.queued_jobs,
            "recent_failures": self.recent_failures,
            "completed_recently": self.completed_recently,
            "worker_capacity": self.worker_capacity,
            "default_timeout_seconds": self.default_timeout_seconds,
            "headline": self.headline,
            "tasks": [task.to_dict() for task in self.tasks],
        }


@dataclass(slots=True)
class SystemsInterpretationSnapshot:
    headline: str
    summary: str
    domains: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "summary": self.summary,
            "domains": [dict(domain) for domain in self.domains],
        }
