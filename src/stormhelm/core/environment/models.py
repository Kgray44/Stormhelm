from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AttentionPriority(str, Enum):
    INTERRUPT = "interrupt"
    SUMMARY = "summary"
    BACKGROUND = "background"


@dataclass(slots=True)
class SurfaceLinkReason:
    code: str
    label: str
    detail: str
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "detail": self.detail,
            "score": round(float(self.score), 3),
        }


@dataclass(slots=True)
class BrowserContextItem:
    context_id: str
    title: str
    url: str = ""
    domain: str = ""
    process_name: str = ""
    window_handle: int = 0
    pid: int = 0
    source: str = ""
    role: str = ""
    summary: str = ""
    active: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contextId": self.context_id,
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "processName": self.process_name,
            "windowHandle": self.window_handle,
            "pid": self.pid,
            "source": self.source,
            "role": self.role,
            "summary": self.summary,
            "active": self.active,
            "metadata": dict(self.metadata),
        }

    def to_workspace_item(self) -> dict[str, Any]:
        subtitle_parts = [part for part in [self.domain, self.summary or self.process_name] if part]
        item = {
            "itemId": self.context_id,
            "kind": "browser",
            "viewer": "browser",
            "title": self.title,
            "subtitle": " | ".join(subtitle_parts),
            "url": self.url,
            "summary": self.summary,
            "module": "browser",
            "section": "references",
            **dict(self.metadata),
        }
        if not item.get("subtitle"):
            item["subtitle"] = "Browser context"
        return item


@dataclass(slots=True)
class BrowserReferenceCandidate:
    item: BrowserContextItem
    score: float = 0.0
    reasons: list[SurfaceLinkReason] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item.to_dict(),
            "score": round(float(self.score), 3),
            "reasons": [reason.to_dict() for reason in self.reasons],
        }


@dataclass(slots=True)
class BrowserReuseDecision:
    reused_existing: bool
    chosen: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    duplicate_candidates: list[dict[str, Any]] = field(default_factory=list)
    capability_limits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reusedExisting": self.reused_existing,
            "chosen": dict(self.chosen),
            "reasons": list(self.reasons),
            "duplicateCandidates": [dict(item) for item in self.duplicate_candidates],
            "capabilityLimits": list(self.capability_limits),
        }


@dataclass(slots=True)
class NotificationPolicy:
    high_priority_rules: list[str] = field(default_factory=list)
    summary_rules: list[str] = field(default_factory=list)
    background_rules: list[str] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "highPriorityRules": list(self.high_priority_rules),
            "summaryRules": list(self.summary_rules),
            "backgroundRules": list(self.background_rules),
            "capabilities": dict(self.capabilities),
        }


@dataclass(slots=True)
class MissedActivityWindow:
    lookback_minutes: int
    started_at: str = ""
    ended_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "lookbackMinutes": self.lookback_minutes,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
        }


@dataclass(slots=True)
class CrossSurfaceLink:
    source_surface: str
    target_surface: str
    source_label: str
    target_label: str
    reasons: list[SurfaceLinkReason] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceSurface": self.source_surface,
            "targetSurface": self.target_surface,
            "sourceLabel": self.source_label,
            "targetLabel": self.target_label,
            "reasons": [reason.to_dict() for reason in self.reasons],
        }


@dataclass(slots=True)
class ActivitySummary:
    headline: str
    summary: str
    window: MissedActivityWindow
    high_priority: list[dict[str, Any]] = field(default_factory=list)
    summary_worthy: list[dict[str, Any]] = field(default_factory=list)
    suppressed_count: int = 0
    policy: NotificationPolicy = field(default_factory=NotificationPolicy)
    links: list[CrossSurfaceLink] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "summary": self.summary,
            "window": self.window.to_dict(),
            "highPriority": [dict(item) for item in self.high_priority],
            "summaryWorthy": [dict(item) for item in self.summary_worthy],
            "suppressedCount": self.suppressed_count,
            "policy": self.policy.to_dict(),
            "links": [link.to_dict() for link in self.links],
            "limitations": list(self.limitations),
        }


@dataclass(slots=True)
class EnvironmentContinuitySnapshot:
    workspace: dict[str, Any] = field(default_factory=dict)
    browser_context: list[dict[str, Any]] = field(default_factory=list)
    operational_signals: list[dict[str, Any]] = field(default_factory=list)
    links: list[CrossSurfaceLink] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": dict(self.workspace),
            "browserContext": [dict(item) for item in self.browser_context],
            "operationalSignals": [dict(item) for item in self.operational_signals],
            "links": [link.to_dict() for link in self.links],
            "capabilities": dict(self.capabilities),
            "limitations": list(self.limitations),
        }
