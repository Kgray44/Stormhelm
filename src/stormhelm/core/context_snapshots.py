from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
from time import time
from typing import Any
from uuid import uuid4


class ContextSnapshotFamily(StrEnum):
    ACTIVE_REQUEST_STATE = "active_request_state"
    PENDING_TRUST = "pending_trust"
    ACTIVE_WORKSPACE = "active_workspace"
    ACTIVE_TASK = "active_task"
    RECENT_TOOL_RESULTS = "recent_tool_results"
    RECENT_RESOLUTIONS = "recent_resolutions"
    SCREEN_CONTEXT = "screen_context"
    CLIPBOARD_HINT = "clipboard_hint"
    SELECTION_HINT = "selection_hint"
    SOFTWARE_CATALOG = "software_catalog"
    SOFTWARE_VERIFICATION_CACHE = "software_verification_cache"
    DISCORD_ALIASES = "discord_aliases"
    DISCORD_RECENT_PREVIEW = "discord_recent_preview"
    VOICE_READINESS = "voice_readiness"
    VOICE_PLAYBACK_READINESS = "voice_playback_readiness"
    PROVIDER_READINESS = "provider_readiness"
    SYSTEM_STATUS = "system_status"
    NETWORK_STATUS = "network_status"
    HARDWARE_TELEMETRY = "hardware_telemetry"
    SEMANTIC_MEMORY_INDEX = "semantic_memory_index"
    ROUTE_FAMILY_STATUS = "route_family_status"


class ContextSnapshotFreshness(StrEnum):
    FRESH = "fresh"
    USABLE_STALE = "usable_stale"
    STALE = "stale"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    UNAVAILABLE = "unavailable"


class ContextSnapshotSource(StrEnum):
    RUNTIME = "runtime"
    SESSION_STATE = "session_state"
    WORKSPACE = "workspace"
    TRUST = "trust"
    SOFTWARE = "software"
    DISCORD = "discord"
    VOICE = "voice"
    PROVIDER = "provider"
    SCREEN = "screen"
    CLIPBOARD = "clipboard"
    SYSTEM = "system"
    MEMORY = "memory"
    UNKNOWN = "unknown"


SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "secret",
    "token",
    "password",
    "credential",
    "raw_audio",
    "generated_audio",
    "audio_bytes",
    "audio_chunk",
    "pcm",
    "wav_bytes",
    "mp3_bytes",
)


@dataclass(frozen=True, slots=True)
class ContextSnapshotPolicy:
    ttl_ms: int = 5_000
    refresh_triggers: tuple[str, ...] = ()
    invalidation_triggers: tuple[str, ...] = ()
    allow_stale_use: bool = False
    supports_user_claims: bool = False
    supports_routing: bool = True
    supports_deictic_binding: bool = False
    supports_verification: bool = False
    max_payload_bytes: int = 4096
    redact_sensitive: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["refresh_triggers"] = list(self.refresh_triggers)
        payload["invalidation_triggers"] = list(self.invalidation_triggers)
        return payload

    @classmethod
    def for_family(cls, family: ContextSnapshotFamily | str) -> "ContextSnapshotPolicy":
        return SNAPSHOT_POLICIES.get(_family_value(family), SNAPSHOT_POLICIES["route_family_status"])


@dataclass(frozen=True, slots=True)
class ContextSnapshotInvalidation:
    reason: str
    invalidated_at_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "invalidated_at_ms": round(float(self.invalidated_at_ms or 0.0), 3)}


@dataclass(frozen=True, slots=True)
class ContextSnapshotFreshnessReport:
    state: ContextSnapshotFreshness
    age_ms: float
    expired: bool
    usable_for_claims: bool
    usable_for_deictic_binding: bool
    usable_for_verification: bool
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "age_ms": round(float(self.age_ms or 0.0), 3),
            "expired": self.expired,
            "usable_for_claims": self.usable_for_claims,
            "usable_for_deictic_binding": self.usable_for_deictic_binding,
            "usable_for_verification": self.usable_for_verification,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    snapshot_id: str
    family: ContextSnapshotFamily
    source: ContextSnapshotSource
    created_at_ms: float
    refreshed_at_ms: float
    ttl_ms: int
    session_id: str | None = None
    task_id: str | None = None
    route_family: str | None = None
    expires_at_ms: float | None = None
    confidence: float = 1.0
    version: str = "1"
    fingerprint: str = ""
    invalidation_reasons: tuple[str, ...] = ()
    invalidations: tuple[ContextSnapshotInvalidation, ...] = ()
    limitations: tuple[str, ...] = ()
    payload_summary: dict[str, Any] = field(default_factory=dict)
    payload_ref: str | None = None
    safe_for_hot_path: bool = True
    safe_for_user_claims: bool = False
    safe_for_deictic_binding: bool = False
    safe_for_verification: bool = False
    contains_sensitive_data: bool = False
    redaction_applied: bool = True
    debug: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        family: ContextSnapshotFamily | str,
        source: ContextSnapshotSource | str = ContextSnapshotSource.RUNTIME,
        created_at_ms: float | None = None,
        ttl_ms: int | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        route_family: str | None = None,
        payload_summary: dict[str, Any] | None = None,
        max_payload_bytes: int | None = None,
        safe_for_hot_path: bool = True,
        safe_for_user_claims: bool | None = None,
        safe_for_deictic_binding: bool | None = None,
        safe_for_verification: bool | None = None,
        confidence: float = 1.0,
        fingerprint: str = "",
        limitations: tuple[str, ...] | list[str] = (),
        debug: dict[str, Any] | None = None,
    ) -> "ContextSnapshot":
        family_value = ContextSnapshotFamily(_family_value(family))
        source_value = ContextSnapshotSource(str(source))
        policy = ContextSnapshotPolicy.for_family(family_value)
        now_ms = float(created_at_ms if created_at_ms is not None else time() * 1000.0)
        ttl = int(ttl_ms if ttl_ms is not None else policy.ttl_ms)
        bounded, contains_sensitive, redaction_applied = safe_snapshot_payload(
            payload_summary or {},
            max_payload_bytes=max_payload_bytes if max_payload_bytes is not None else policy.max_payload_bytes,
            redact_sensitive=policy.redact_sensitive,
        )
        return cls(
            snapshot_id=f"snapshot-{uuid4().hex}",
            family=family_value,
            source=source_value,
            created_at_ms=now_ms,
            refreshed_at_ms=now_ms,
            expires_at_ms=now_ms + ttl if ttl > 0 else None,
            ttl_ms=ttl,
            session_id=session_id,
            task_id=task_id,
            route_family=route_family,
            confidence=max(0.0, min(1.0, float(confidence or 0.0))),
            fingerprint=fingerprint,
            limitations=tuple(str(item) for item in limitations if str(item or "").strip()),
            payload_summary=bounded,
            safe_for_hot_path=safe_for_hot_path,
            safe_for_user_claims=policy.supports_user_claims if safe_for_user_claims is None else bool(safe_for_user_claims),
            safe_for_deictic_binding=(
                policy.supports_deictic_binding
                if safe_for_deictic_binding is None
                else bool(safe_for_deictic_binding)
            ),
            safe_for_verification=policy.supports_verification if safe_for_verification is None else bool(safe_for_verification),
            contains_sensitive_data=contains_sensitive,
            redaction_applied=redaction_applied,
            debug=safe_snapshot_payload(debug or {}, max_payload_bytes=1024)[0],
        )

    def freshness(self, *, now_ms: float | None = None, policy: ContextSnapshotPolicy | None = None) -> ContextSnapshotFreshnessReport:
        now = float(now_ms if now_ms is not None else time() * 1000.0)
        policy = policy or ContextSnapshotPolicy.for_family(self.family)
        age = max(0.0, now - float(self.refreshed_at_ms or self.created_at_ms or now))
        if self.invalidation_reasons or self.invalidations:
            return ContextSnapshotFreshnessReport(
                state=ContextSnapshotFreshness.INVALIDATED,
                age_ms=age,
                expired=True,
                usable_for_claims=False,
                usable_for_deictic_binding=False,
                usable_for_verification=False,
                limitations=tuple(self.limitations) + tuple(self.invalidation_reasons),
            )
        expired = bool(self.ttl_ms >= 0 and age > self.ttl_ms)
        if expired and policy.allow_stale_use:
            state = ContextSnapshotFreshness.USABLE_STALE
        elif expired:
            state = ContextSnapshotFreshness.EXPIRED
        else:
            state = ContextSnapshotFreshness.FRESH
        claimable = state == ContextSnapshotFreshness.FRESH and self.safe_for_user_claims and policy.supports_user_claims
        deictic = state == ContextSnapshotFreshness.FRESH and self.safe_for_deictic_binding and policy.supports_deictic_binding
        verification = state == ContextSnapshotFreshness.FRESH and self.safe_for_verification and policy.supports_verification
        return ContextSnapshotFreshnessReport(
            state=state,
            age_ms=age,
            expired=expired,
            usable_for_claims=claimable,
            usable_for_deictic_binding=deictic,
            usable_for_verification=verification,
            limitations=self.limitations,
        )

    def invalidate(self, reason: str, *, now_ms: float | None = None) -> "ContextSnapshot":
        invalidation = ContextSnapshotInvalidation(
            reason=str(reason or "invalidated"),
            invalidated_at_ms=float(now_ms if now_ms is not None else time() * 1000.0),
        )
        return ContextSnapshot(
            **{
                **asdict(self),
                "family": self.family,
                "source": self.source,
                "invalidation_reasons": tuple(dict.fromkeys((*self.invalidation_reasons, invalidation.reason))),
                "invalidations": (*self.invalidations, invalidation),
                "safe_for_user_claims": False,
                "safe_for_deictic_binding": False,
                "safe_for_verification": False,
            }
        )

    def to_dict(self, *, now_ms: float | None = None) -> dict[str, Any]:
        freshness = self.freshness(now_ms=now_ms)
        return {
            "snapshot_id": self.snapshot_id,
            "family": self.family.value,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "route_family": self.route_family,
            "source": self.source.value,
            "created_at_ms": round(float(self.created_at_ms or 0.0), 3),
            "refreshed_at_ms": round(float(self.refreshed_at_ms or 0.0), 3),
            "expires_at_ms": round(float(self.expires_at_ms), 3) if self.expires_at_ms is not None else None,
            "ttl_ms": self.ttl_ms,
            "freshness_state": freshness.state.value,
            "age_ms": freshness.age_ms,
            "confidence": round(float(self.confidence or 0.0), 3),
            "version": self.version,
            "fingerprint": self.fingerprint,
            "invalidation_reasons": list(self.invalidation_reasons),
            "limitations": list(self.limitations),
            "payload_summary": self.payload_summary,
            "payload_ref": self.payload_ref,
            "safe_for_hot_path": self.safe_for_hot_path,
            "safe_for_user_claims": freshness.usable_for_claims,
            "safe_for_deictic_binding": freshness.usable_for_deictic_binding,
            "safe_for_verification": freshness.usable_for_verification,
            "contains_sensitive_data": self.contains_sensitive_data,
            "redaction_applied": self.redaction_applied,
            "debug": self.debug,
        }


@dataclass(frozen=True, slots=True)
class ContextSnapshotLookup:
    snapshot: ContextSnapshot
    refreshed: bool = False
    hot_path_hit: bool = False
    miss_reason: str = ""
    stale_used_cautiously: bool = False


@dataclass(frozen=True, slots=True)
class ContextSnapshotSummary:
    snapshots_checked: tuple[str, ...] = ()
    snapshots_used: tuple[str, ...] = ()
    snapshots_refreshed: tuple[str, ...] = ()
    snapshots_invalidated: tuple[str, ...] = ()
    snapshot_freshness: dict[str, str] = field(default_factory=dict)
    snapshot_age_ms: dict[str, float] = field(default_factory=dict)
    snapshot_hot_path_hit: bool = False
    snapshot_miss_reason: dict[str, str] = field(default_factory=dict)
    heavy_context_avoided_by_snapshot: bool = False
    stale_snapshot_used_cautiously: bool = False
    invalidation_count: int = 0
    freshness_warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshots_checked": list(self.snapshots_checked),
            "snapshots_used": list(self.snapshots_used),
            "snapshots_refreshed": list(self.snapshots_refreshed),
            "snapshots_invalidated": list(self.snapshots_invalidated),
            "snapshot_freshness": dict(self.snapshot_freshness),
            "snapshot_age_ms": {key: round(float(value or 0.0), 3) for key, value in self.snapshot_age_ms.items()},
            "snapshot_hot_path_hit": self.snapshot_hot_path_hit,
            "snapshot_miss_reason": dict(self.snapshot_miss_reason),
            "heavy_context_avoided_by_snapshot": self.heavy_context_avoided_by_snapshot,
            "stale_snapshot_used_cautiously": self.stale_snapshot_used_cautiously,
            "invalidation_count": self.invalidation_count,
            "freshness_warnings": list(self.freshness_warnings),
        }


class ContextSnapshotStore:
    def __init__(self, *, clock_ms: Any | None = None) -> None:
        self._clock_ms = clock_ms or (lambda: time() * 1000.0)
        self._snapshots: dict[tuple[str, str, str, str], ContextSnapshot] = {}
        self._invalidation_count = 0

    def get_snapshot(
        self,
        family: ContextSnapshotFamily | str,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        route_family: str | None = None,
        allow_usable_stale: bool = False,
        require_current: bool = True,
    ) -> ContextSnapshot | None:
        snapshot = self._snapshots.get(self._key(family, session_id=session_id, task_id=task_id, route_family=route_family))
        if snapshot is None:
            return None
        policy = ContextSnapshotPolicy.for_family(family)
        freshness = snapshot.freshness(now_ms=self.now_ms(), policy=policy)
        if freshness.state == ContextSnapshotFreshness.FRESH:
            return snapshot
        if allow_usable_stale and not require_current and freshness.state == ContextSnapshotFreshness.USABLE_STALE:
            return snapshot
        return None

    def set_snapshot(self, snapshot: ContextSnapshot) -> ContextSnapshot:
        self._snapshots[
            self._key(
                snapshot.family,
                session_id=snapshot.session_id,
                task_id=snapshot.task_id,
                route_family=snapshot.route_family,
            )
        ] = snapshot
        return snapshot

    def get_or_refresh(
        self,
        family: ContextSnapshotFamily | str,
        *,
        refresh_fn: Any,
        policy: ContextSnapshotPolicy | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        route_family: str | None = None,
        source: ContextSnapshotSource | str = ContextSnapshotSource.RUNTIME,
        allow_usable_stale: bool | None = None,
    ) -> ContextSnapshotLookup:
        policy = policy or ContextSnapshotPolicy.for_family(family)
        stale_allowed = policy.allow_stale_use if allow_usable_stale is None else bool(allow_usable_stale)
        existing = self._snapshots.get(self._key(family, session_id=session_id, task_id=task_id, route_family=route_family))
        if existing is not None:
            freshness = existing.freshness(now_ms=self.now_ms(), policy=policy)
            if freshness.state == ContextSnapshotFreshness.FRESH:
                return ContextSnapshotLookup(snapshot=existing, hot_path_hit=True)
            if stale_allowed and freshness.state == ContextSnapshotFreshness.USABLE_STALE:
                return ContextSnapshotLookup(snapshot=existing, hot_path_hit=True, stale_used_cautiously=True)

        payload = refresh_fn()
        snapshot = payload if isinstance(payload, ContextSnapshot) else ContextSnapshot.create(
            family=family,
            source=source,
            created_at_ms=self.now_ms(),
            ttl_ms=policy.ttl_ms,
            session_id=session_id,
            task_id=task_id,
            route_family=route_family,
            payload_summary=payload if isinstance(payload, dict) else {"value": payload},
            max_payload_bytes=policy.max_payload_bytes,
        )
        self.set_snapshot(snapshot)
        miss_reason = "missing" if existing is None else existing.freshness(now_ms=self.now_ms(), policy=policy).state.value
        return ContextSnapshotLookup(snapshot=snapshot, refreshed=True, miss_reason=miss_reason)

    def invalidate(
        self,
        *,
        family: ContextSnapshotFamily | str | None = None,
        session_id: str | None = None,
        reason: str = "invalidated",
    ) -> int:
        keys = [
            key
            for key, snapshot in self._snapshots.items()
            if (family is None or key[0] == _family_value(family))
            and (session_id is None or snapshot.session_id == session_id)
        ]
        for key in keys:
            self._snapshots.pop(key, None)
        self._invalidation_count += len(keys)
        return len(keys)

    def mark_stale(
        self,
        *,
        family: ContextSnapshotFamily | str | None = None,
        session_id: str | None = None,
        reason: str = "marked_stale",
    ) -> int:
        keys = [
            key
            for key, snapshot in self._snapshots.items()
            if (family is None or key[0] == _family_value(family))
            and (session_id is None or snapshot.session_id == session_id)
        ]
        for key in keys:
            self._snapshots[key] = self._snapshots[key].invalidate(reason, now_ms=self.now_ms())
        self._invalidation_count += len(keys)
        return len(keys)

    def prune_expired(self) -> int:
        keys = [
            key
            for key, snapshot in self._snapshots.items()
            if snapshot.freshness(now_ms=self.now_ms()).state in {ContextSnapshotFreshness.EXPIRED, ContextSnapshotFreshness.INVALIDATED}
        ]
        for key in keys:
            self._snapshots.pop(key, None)
        return len(keys)

    def snapshot_summary(self) -> dict[str, Any]:
        now_ms = self.now_ms()
        return {
            "count": len(self._snapshots),
            "families": sorted({snapshot.family.value for snapshot in self._snapshots.values()}),
            "invalidation_count": self._invalidation_count,
            "freshness": {
                snapshot.family.value: snapshot.freshness(now_ms=now_ms).state.value
                for snapshot in self._snapshots.values()
            },
        }

    def safe_debug_payload(self) -> dict[str, Any]:
        now_ms = self.now_ms()
        return {
            "snapshots": [snapshot.to_dict(now_ms=now_ms) for snapshot in self._snapshots.values()],
            "summary": self.snapshot_summary(),
        }

    def now_ms(self) -> float:
        return float(self._clock_ms())

    def _key(
        self,
        family: ContextSnapshotFamily | str,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        route_family: str | None = None,
    ) -> tuple[str, str, str, str]:
        return (_family_value(family), session_id or "", task_id or "", route_family or "")


SNAPSHOT_POLICIES: dict[str, ContextSnapshotPolicy] = {
    "active_request_state": ContextSnapshotPolicy(
        ttl_ms=500,
        allow_stale_use=False,
        supports_routing=True,
        supports_deictic_binding=True,
        max_payload_bytes=2048,
        invalidation_triggers=("request_completion", "cancellation", "task_switch", "expiry"),
    ),
    "pending_trust": ContextSnapshotPolicy(
        ttl_ms=30_000,
        allow_stale_use=False,
        supports_routing=True,
        supports_deictic_binding=True,
        max_payload_bytes=2048,
        invalidation_triggers=("grant_consumed", "denial", "expiry", "restart_boundary", "payload_mismatch"),
    ),
    "active_workspace": ContextSnapshotPolicy(
        ttl_ms=15_000,
        allow_stale_use=True,
        supports_user_claims=False,
        supports_routing=True,
        max_payload_bytes=4096,
        invalidation_triggers=("workspace_mutation", "session_switch", "restore", "clear", "archive"),
    ),
    "active_task": ContextSnapshotPolicy(ttl_ms=5_000, allow_stale_use=True, supports_routing=True, max_payload_bytes=2048),
    "recent_tool_results": ContextSnapshotPolicy(
        ttl_ms=60_000,
        allow_stale_use=True,
        supports_routing=True,
        supports_deictic_binding=False,
        max_payload_bytes=4096,
    ),
    "recent_resolutions": ContextSnapshotPolicy(ttl_ms=60_000, allow_stale_use=True, supports_routing=True, max_payload_bytes=4096),
    "screen_context": ContextSnapshotPolicy(
        ttl_ms=500,
        allow_stale_use=True,
        supports_user_claims=False,
        supports_routing=True,
        supports_deictic_binding=False,
        supports_verification=False,
        max_payload_bytes=4096,
        invalidation_triggers=("focus_change", "window_change", "screen_observation_change"),
    ),
    "clipboard_hint": ContextSnapshotPolicy(ttl_ms=2_000, allow_stale_use=True, supports_user_claims=False, supports_routing=True, max_payload_bytes=1024),
    "selection_hint": ContextSnapshotPolicy(ttl_ms=2_000, allow_stale_use=True, supports_user_claims=False, supports_routing=True, max_payload_bytes=1024),
    "software_catalog": ContextSnapshotPolicy(ttl_ms=300_000, allow_stale_use=True, supports_routing=True, max_payload_bytes=4096),
    "software_verification_cache": ContextSnapshotPolicy(ttl_ms=5_000, allow_stale_use=True, supports_routing=True, supports_verification=False, max_payload_bytes=2048),
    "discord_aliases": ContextSnapshotPolicy(ttl_ms=300_000, allow_stale_use=True, supports_routing=True, max_payload_bytes=2048),
    "discord_recent_preview": ContextSnapshotPolicy(ttl_ms=60_000, allow_stale_use=False, supports_routing=True, supports_deictic_binding=True, max_payload_bytes=2048),
    "voice_readiness": ContextSnapshotPolicy(ttl_ms=30_000, allow_stale_use=True, supports_routing=True, max_payload_bytes=2048),
    "voice_playback_readiness": ContextSnapshotPolicy(ttl_ms=30_000, allow_stale_use=True, supports_routing=True, max_payload_bytes=2048),
    "provider_readiness": ContextSnapshotPolicy(ttl_ms=30_000, allow_stale_use=True, supports_routing=True, max_payload_bytes=1024),
    "system_status": ContextSnapshotPolicy(ttl_ms=5_000, allow_stale_use=True, supports_user_claims=False, supports_routing=True, max_payload_bytes=2048),
    "network_status": ContextSnapshotPolicy(ttl_ms=5_000, allow_stale_use=True, supports_user_claims=False, supports_routing=True, max_payload_bytes=2048),
    "hardware_telemetry": ContextSnapshotPolicy(ttl_ms=5_000, allow_stale_use=True, supports_user_claims=False, supports_routing=True, max_payload_bytes=2048),
    "semantic_memory_index": ContextSnapshotPolicy(ttl_ms=60_000, allow_stale_use=True, supports_routing=True, max_payload_bytes=2048),
    "route_family_status": ContextSnapshotPolicy(ttl_ms=30_000, allow_stale_use=True, supports_routing=True, max_payload_bytes=2048),
}


def describe_snapshot_freshness(snapshot: ContextSnapshot, *, now_ms: float | None = None) -> str:
    report = snapshot.freshness(now_ms=now_ms)
    age_seconds = max(0.0, report.age_ms / 1000.0)
    if snapshot.family == ContextSnapshotFamily.CLIPBOARD_HINT:
        return "That clipboard value is only a hint, not screen truth."
    if snapshot.family == ContextSnapshotFamily.SCREEN_CONTEXT and report.state != ContextSnapshotFreshness.FRESH:
        return f"Using a prior screen observation from {age_seconds:.0f} seconds ago; it is not current screen truth."
    if snapshot.family == ContextSnapshotFamily.ACTIVE_WORKSPACE and report.state != ContextSnapshotFreshness.FRESH:
        return f"Using the last workspace snapshot from {age_seconds:.0f} seconds ago."
    if snapshot.family == ContextSnapshotFamily.SOFTWARE_CATALOG:
        return "The software catalog snapshot is usable for planning, not verification."
    if snapshot.family == ContextSnapshotFamily.NETWORK_STATUS and report.state != ContextSnapshotFreshness.FRESH:
        return f"This network status is cached from {age_seconds:.0f} seconds ago."
    return f"{snapshot.family.value} snapshot is {report.state.value}."


def safe_snapshot_payload(
    value: Any,
    *,
    max_payload_bytes: int = 4096,
    redact_sensitive: bool = True,
    depth: int = 0,
) -> tuple[dict[str, Any], bool, bool]:
    sanitized, contains_sensitive, redaction_applied = _sanitize_snapshot_value(
        value,
        redact_sensitive=redact_sensitive,
        depth=depth,
    )
    if not isinstance(sanitized, dict):
        sanitized = {"value": sanitized}
    encoded = json.dumps(sanitized, sort_keys=True, default=str)
    if len(encoded.encode("utf-8")) <= max_payload_bytes:
        return sanitized, contains_sensitive, redaction_applied
    bounded: dict[str, Any] = {
        "truncated": True,
        "original_bytes": len(encoded.encode("utf-8")),
        "max_payload_bytes": max_payload_bytes,
    }
    for key, item in sanitized.items():
        if len(json.dumps(bounded, sort_keys=True, default=str).encode("utf-8")) >= max_payload_bytes:
            break
        if isinstance(item, str) and len(item) > 240:
            bounded[key] = item[:240] + "...<truncated>"
        else:
            bounded[key] = item
    return bounded, contains_sensitive, True


def _sanitize_snapshot_value(
    value: Any,
    *,
    redact_sensitive: bool,
    depth: int = 0,
    key_hint: str = "",
) -> tuple[Any, bool, bool]:
    if depth > 5:
        return "<truncated>", False, True
    lowered = key_hint.lower()
    sensitive_key = any(part in lowered for part in SENSITIVE_KEY_PARTS)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "<bytes:redacted>", True, True
    if sensitive_key and redact_sensitive:
        return "<redacted>", True, True
    if isinstance(value, dict):
        contains_sensitive = False
        redaction_applied = False
        payload: dict[str, Any] = {}
        for key, item in list(value.items())[:64]:
            child, sensitive, redacted = _sanitize_snapshot_value(
                item,
                redact_sensitive=redact_sensitive,
                depth=depth + 1,
                key_hint=str(key),
            )
            payload[str(key)] = child
            contains_sensitive = contains_sensitive or sensitive
            redaction_applied = redaction_applied or redacted
        return payload, contains_sensitive, redaction_applied
    if isinstance(value, (list, tuple, set)):
        items = []
        contains_sensitive = False
        redaction_applied = False
        for item in list(value)[:32]:
            child, sensitive, redacted = _sanitize_snapshot_value(
                item,
                redact_sensitive=redact_sensitive,
                depth=depth + 1,
                key_hint=key_hint,
            )
            items.append(child)
            contains_sensitive = contains_sensitive or sensitive
            redaction_applied = redaction_applied or redacted
        return items, contains_sensitive, redaction_applied
    return value, False, False


def _family_value(family: ContextSnapshotFamily | str) -> str:
    return family.value if isinstance(family, ContextSnapshotFamily) else str(family)
