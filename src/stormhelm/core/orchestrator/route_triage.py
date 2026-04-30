from __future__ import annotations

import re
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from time import perf_counter
from typing import Any
from uuid import uuid4

from stormhelm.core.calculations.normalizer import detect_expression_candidate
from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.latency import classify_route_latency_policy


_ALL_NATIVE_ROUTE_FAMILIES = (
    "calculations",
    "web_retrieval",
    "browser_destination",
    "software_control",
    "discord_relay",
    "trust_approvals",
    "voice_control",
    "screen_awareness",
    "task_continuity",
    "workspace_operations",
    "semantic_memory",
    "watch_runtime",
    "network",
    "machine",
    "storage",
    "power",
    "resources",
)
_SEAM_ROUTE_FAMILIES = ("calculations", "software_control", "screen_awareness")
_NATIVE_PROTECTED_FAMILIES = {
    "calculations",
    "web_retrieval",
    "browser_destination",
    "software_control",
    "discord_relay",
    "trust_approvals",
    "voice_control",
    "screen_awareness",
    "task_continuity",
    "workspace_operations",
    "watch_runtime",
}

_URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)
_DOMAIN_RE = re.compile(
    r"(?<!@)\b[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
    r"(?:/[^\s<>]*)?\b",
    re.IGNORECASE,
)
_SOFTWARE_VERBS_RE = re.compile(
    r"\b(?:install|download and install|update|upgrade|uninstall|remove|repair|"
    r"reinstall|check if|verify)\b",
    re.IGNORECASE,
)
_CALC_HELPER_RE = re.compile(
    r"\b(?:power|voltage|current|resistance|ohm'?s law|wattage)\b"
    r".*\b\d+(?:\.\d+)?\s*(?:v|a|w|ohm|ohms|kohm|ma|mv)\b",
    re.IGNORECASE,
)
_CALC_FOLLOW_UP_RE = re.compile(r"\b(?:show the steps|show the formula|formula|breakdown)\b", re.IGNORECASE)
_APP_OPEN_RE = re.compile(r"\b(?:launch|open|start|run)\s+(?:app\s+)?[a-z][\w .+-]{1,64}$", re.IGNORECASE)
_DISCORD_RELAY_RE = re.compile(r"\b(?:send|share|relay|message|dm)\b", re.IGNORECASE)
_TRUST_APPROVALS = {
    "yes",
    "yep",
    "confirm",
    "approve",
    "approve once",
    "proceed",
    "go ahead",
    "do it",
    "no",
    "reject",
    "cancel",
    "deny",
}
_VOICE_RE = re.compile(
    r"\b(?:stop talking|stop speaking|mute voice|unmute voice|start voice capture|"
    r"cancel capture|submit voice|repeat that)\b",
    re.IGNORECASE,
)
_SCREEN_RE = re.compile(
    r"\b(?:screen|visible|button|click that|click this|what changed|compare to before|"
    r"verify it changed|visible error|what should i click|on my screen)\b",
    re.IGNORECASE,
)
_WORKSPACE_RE = re.compile(
    r"\b(?:where did we leave off|continue this|next steps|resume (?:the )?task|"
    r"what were we doing|restore workspace|assemble workspace|save workspace)\b",
    re.IGNORECASE,
)
_SYSTEM_RE = re.compile(
    r"\b(?:battery|power|storage|disk|cpu|ram|memory usage|network|wi-?fi|wifi|"
    r"internet|speed|diagnostics?)\b",
    re.IGNORECASE,
)
_OPEN_ENDED_RE = re.compile(r"\b(?:explain|brainstorm|write|summarize|research|draft)\b", re.IGNORECASE)
_DEICTIC_RE = re.compile(r"\b(?:this|that|it|same one|those|these|do that again|send it|open that)\b", re.IGNORECASE)
_WEB_RETRIEVAL_RE = re.compile(
    r"\b(?:read|summarize|inspect|extract|render|compare|parse|cdp|renderer)\b.*\b(?:https?://|www\.|[a-z0-9-]+\.[a-z]{2,})",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RouteTriageCandidate:
    route_family: str
    confidence: float
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_family": self.route_family,
            "confidence": round(float(self.confidence or 0.0), 3),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class RouteTriageResult:
    triage_id: str
    raw_text_preview: str
    normalized_text_preview: str
    likely_route_families: tuple[str, ...] = ()
    excluded_route_families: tuple[str, ...] = ()
    route_hints: dict[str, Any] = field(default_factory=dict)
    query_shape_hint: str = ""
    needs_deictic_context: bool = False
    needs_active_request_state: bool = False
    needs_workspace_context: bool = False
    needs_recent_tool_results: bool = False
    needs_semantic_memory: bool = False
    needs_screen_context: bool = False
    provider_fallback_eligible: bool = False
    clarification_likely: bool = False
    confidence: float = 0.0
    confidence_label: str = "low"
    reason_codes: tuple[str, ...] = ()
    elapsed_ms: float = 0.0
    safe_to_short_circuit: bool = False
    short_circuit_route_family: str | None = None
    budget_label: str = ""
    execution_mode: str = ""
    debug: dict[str, Any] = field(default_factory=dict)

    @property
    def skipped_route_families(self) -> tuple[str, ...]:
        return self.excluded_route_families

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["likely_route_families"] = list(self.likely_route_families)
        payload["excluded_route_families"] = list(self.excluded_route_families)
        payload["skipped_route_families"] = list(self.skipped_route_families)
        payload["reason_codes"] = list(self.reason_codes)
        payload["elapsed_ms"] = round(float(self.elapsed_ms or 0.0), 3)
        payload["confidence"] = round(float(self.confidence or 0.0), 3)
        return payload


class FastRouteClassifier:
    def classify(
        self,
        raw_text: str,
        *,
        active_request_state: dict[str, Any] | None = None,
        provider_enabled: bool = False,
        provider_configured: bool = False,
        surface_mode: str = "ghost",
        active_module: str = "chartroom",
    ) -> RouteTriageResult:
        started = perf_counter()
        raw = str(raw_text or "").strip()
        normalized = normalize_phrase(raw)
        active_state = active_request_state if isinstance(active_request_state, dict) else {}

        route_hints: dict[str, Any] = {}
        likely: list[str] = []
        reason_codes: list[str] = []
        confidence = 0.0
        query_shape_hint = ""
        needs_deictic = bool(_DEICTIC_RE.search(normalized))
        needs_active_state = False
        needs_workspace = False
        needs_recent = False
        needs_semantic = False
        needs_screen = False
        clarification_likely = False
        provider_eligible = False

        trust_phrase = normalized in _TRUST_APPROVALS
        if trust_phrase:
            if _has_pending_approval(active_state):
                likely = ["trust_approvals"]
                reason_codes.append("pending_approval_phrase")
                confidence = 0.98
                query_shape_hint = "approval_follow_up"
                needs_active_state = True
            else:
                reason_codes.append("approval_without_pending_state")
                clarification_likely = True
                confidence = 0.25
                query_shape_hint = "approval_without_pending_state"

        if not likely and _VOICE_RE.search(normalized):
            likely = ["voice_control"]
            reason_codes.append("voice_control_phrase")
            confidence = 0.96
            query_shape_hint = "voice_control"

        if not likely:
            calc_candidate = detect_expression_candidate(raw, normalized)
            if calc_candidate.candidate:
                likely = ["calculations"]
                reason_codes.append("calculation_expression")
                reason_codes.extend(str(reason).replace(" ", "_") for reason in calc_candidate.reasons[:3])
                confidence = max(0.95, float(calc_candidate.route_confidence or 0.0))
                query_shape_hint = "calculation_request"

        if not likely and _CALC_HELPER_RE.search(normalized):
            likely = ["calculations"]
            reason_codes.append("calculation_helper_phrase")
            confidence = 0.94
            query_shape_hint = "calculation_helper"

        if not likely and _CALC_FOLLOW_UP_RE.search(normalized):
            likely = ["calculations"]
            reason_codes.append("calculation_follow_up_phrase")
            confidence = 0.86
            query_shape_hint = "calculation_follow_up"
            needs_recent = True
            needs_active_state = True

        if not likely and _is_web_retrieval(raw, normalized):
            likely = ["web_retrieval"]
            reason_codes.append("web_retrieval_public_url")
            confidence = 0.94
            query_shape_hint = "web_retrieval_request"
            route_hints["destination_kind"] = "public_url"

        if not likely and _is_browser_destination(raw, normalized):
            likely = ["browser_destination"]
            reason_codes.append("browser_destination")
            confidence = 0.95
            query_shape_hint = "browser_destination"
            route_hints["destination_kind"] = "url_or_domain"

        if not likely and _looks_like_software_control(normalized):
            likely = ["software_control"]
            reason_codes.append("software_lifecycle_verb")
            confidence = 0.92
            query_shape_hint = "software_control_request"
            route_hints["operation_hint"] = _software_operation_hint(normalized)

        if not likely and _DISCORD_RELAY_RE.search(normalized):
            likely = ["discord_relay"]
            reason_codes.append("relay_phrase")
            confidence = 0.9
            query_shape_hint = "discord_relay"
            needs_deictic = needs_deictic or any(alias in normalized for alias in ("baby", "this", "that", "it"))
            needs_active_state = needs_deictic or "send it" in normalized or "confirm" in normalized
            needs_workspace = needs_deictic
            needs_recent = needs_deictic

        if not likely and _SCREEN_RE.search(normalized):
            likely = ["screen_awareness"]
            reason_codes.append("screen_awareness_phrase")
            confidence = 0.9
            query_shape_hint = "screen_awareness"
            needs_screen = True
            needs_deictic = needs_deictic or any(token in normalized for token in ("that", "this", "it", "changed"))
            needs_workspace = True

        if not likely and _WORKSPACE_RE.search(normalized):
            family = "workspace_operations" if "workspace" in normalized else "task_continuity"
            likely = [family]
            reason_codes.append("workspace_continuity_phrase")
            confidence = 0.88
            query_shape_hint = family
            needs_workspace = True
            needs_recent = True
            needs_active_state = "continue" in normalized or "resume" in normalized
            needs_deictic = needs_deictic or "continue this" in normalized

        if not likely and _SYSTEM_RE.search(normalized):
            lane = _system_lane(normalized)
            likely = ["watch_runtime" if lane in {"network", "machine"} else lane]
            reason_codes.append("system_status_phrase")
            confidence = 0.84
            query_shape_hint = "system_status"
            route_hints["system_lane"] = lane

        if not likely and _OPEN_ENDED_RE.search(normalized):
            likely = ["generic_provider"]
            reason_codes.append("open_ended_provider_shape")
            confidence = 0.65
            query_shape_hint = "provider_fallback"
            provider_eligible = bool(provider_enabled and provider_configured)
            needs_semantic = "summarize" in normalized and needs_deictic
            needs_workspace = needs_semantic

        if not likely:
            reason_codes.append("unresolved_shape")
            query_shape_hint = "unknown"
            confidence = max(confidence, 0.1)

        provider_eligible = provider_eligible or (
            likely == ["generic_provider"] and bool(provider_enabled and provider_configured)
        )
        if likely and likely[0] in _NATIVE_PROTECTED_FAMILIES:
            provider_eligible = False

        policy = classify_route_latency_policy(
            route_family=likely[0] if likely else None,
            request_kind=query_shape_hint,
            surface_mode=surface_mode,
            active_module=active_module,
        )
        safe_to_short_circuit = _safe_to_short_circuit(
            likely=likely,
            confidence=confidence,
            needs_deictic_context=needs_deictic,
            needs_workspace_context=needs_workspace,
            needs_recent_tool_results=needs_recent,
            needs_semantic_memory=needs_semantic,
            needs_screen_context=needs_screen,
            clarification_likely=clarification_likely,
        )
        excluded = _excluded_families(likely, confidence, safe_to_short_circuit)
        if not safe_to_short_circuit and likely and likely[0] in {"discord_relay", "screen_awareness", "task_continuity", "workspace_operations"}:
            excluded = tuple(family for family in excluded if family not in {"screen_awareness"})

        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        return RouteTriageResult(
            triage_id=f"triage-{uuid4().hex}",
            raw_text_preview=raw[:160],
            normalized_text_preview=normalized[:160],
            likely_route_families=tuple(likely),
            excluded_route_families=excluded,
            route_hints=route_hints,
            query_shape_hint=query_shape_hint,
            needs_deictic_context=needs_deictic,
            needs_active_request_state=needs_active_state,
            needs_workspace_context=needs_workspace,
            needs_recent_tool_results=needs_recent,
            needs_semantic_memory=needs_semantic,
            needs_screen_context=needs_screen,
            provider_fallback_eligible=provider_eligible,
            clarification_likely=clarification_likely,
            confidence=confidence,
            confidence_label=_confidence_label(confidence),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            elapsed_ms=elapsed_ms,
            safe_to_short_circuit=safe_to_short_circuit,
            short_circuit_route_family=likely[0] if safe_to_short_circuit and likely else None,
            budget_label=policy.budget.label,
            execution_mode=policy.execution_mode.value,
            debug={
                "provider_enabled": bool(provider_enabled),
                "provider_configured": bool(provider_configured),
                "native_route_protected": bool(likely and likely[0] in _NATIVE_PROTECTED_FAMILIES),
            },
        )


def route_triage_from_dict(value: dict[str, Any] | RouteTriageResult | None) -> RouteTriageResult | None:
    if isinstance(value, RouteTriageResult):
        return value
    if not isinstance(value, dict):
        return None
    return RouteTriageResult(
        triage_id=str(value.get("triage_id") or ""),
        raw_text_preview=str(value.get("raw_text_preview") or "")[:160],
        normalized_text_preview=str(value.get("normalized_text_preview") or "")[:160],
        likely_route_families=tuple(str(item) for item in value.get("likely_route_families", []) if item),
        excluded_route_families=tuple(str(item) for item in value.get("excluded_route_families", []) if item),
        route_hints=dict(value.get("route_hints") or {}) if isinstance(value.get("route_hints"), dict) else {},
        query_shape_hint=str(value.get("query_shape_hint") or ""),
        needs_deictic_context=bool(value.get("needs_deictic_context")),
        needs_active_request_state=bool(value.get("needs_active_request_state")),
        needs_workspace_context=bool(value.get("needs_workspace_context")),
        needs_recent_tool_results=bool(value.get("needs_recent_tool_results")),
        needs_semantic_memory=bool(value.get("needs_semantic_memory")),
        needs_screen_context=bool(value.get("needs_screen_context")),
        provider_fallback_eligible=bool(value.get("provider_fallback_eligible")),
        clarification_likely=bool(value.get("clarification_likely")),
        confidence=float(value.get("confidence") or 0.0),
        confidence_label=str(value.get("confidence_label") or "low"),
        reason_codes=tuple(str(item) for item in value.get("reason_codes", []) if item),
        elapsed_ms=float(value.get("elapsed_ms") or 0.0),
        safe_to_short_circuit=bool(value.get("safe_to_short_circuit")),
        short_circuit_route_family=(
            str(value.get("short_circuit_route_family"))
            if value.get("short_circuit_route_family")
            else None
        ),
        budget_label=str(value.get("budget_label") or ""),
        execution_mode=str(value.get("execution_mode") or ""),
        debug=dict(value.get("debug") or {}) if isinstance(value.get("debug"), dict) else {},
    )


def _has_pending_approval(active_request_state: dict[str, Any]) -> bool:
    if not active_request_state:
        return False
    family = str(active_request_state.get("family") or "").strip().lower()
    trust = active_request_state.get("trust") if isinstance(active_request_state.get("trust"), dict) else {}
    return bool(
        family in {"software_control", "discord_relay", "trust_approvals"}
        and (
            trust
            or active_request_state.get("trust_prompt_id")
            or active_request_state.get("pending_approval")
            or str(active_request_state.get("request_stage") or "").strip().lower() in {"confirm_execution", "approval_required"}
        )
    )


def _is_browser_destination(raw: str, normalized: str) -> bool:
    if _is_web_retrieval(raw, normalized):
        return False
    if _URL_RE.search(normalized) or _DOMAIN_RE.search(normalized):
        return True
    return normalized.startswith(("open ", "bring up ", "go to ", "search for ", "search "))


def _is_web_retrieval(raw: str, normalized: str) -> bool:
    if not (_URL_RE.search(raw) or _DOMAIN_RE.search(raw) or _URL_RE.search(normalized) or _DOMAIN_RE.search(normalized)):
        return False
    if re.search(r"\b(?:open|launch|go to|navigate|bring up|pull up)\b", normalized) and not re.search(
        r"\b(?:read|summarize|inspect|extract|render|compare|text|links?|html|source|content)\b",
        normalized,
    ):
        return False
    return bool(
        _WEB_RETRIEVAL_RE.search(raw)
        or re.search(r"\b(?:read|summarize|inspect|extract|render|compare|text|links?|html|source|content|dom\s+text|network\s+summary|cdp|browser\s+renderer)\b", normalized)
    )


def _looks_like_software_control(normalized: str) -> bool:
    if _DOMAIN_RE.search(normalized) or _URL_RE.search(normalized):
        return False
    if _SOFTWARE_VERBS_RE.search(normalized):
        return True
    return bool(_APP_OPEN_RE.search(normalized) and not any(token in normalized for token in (".com", ".net", ".org", "http")))


def _software_operation_hint(normalized: str) -> str:
    if "uninstall" in normalized or normalized.startswith("remove "):
        return "uninstall"
    if "reinstall" in normalized:
        return "reinstall"
    if "repair" in normalized:
        return "repair"
    if "update" in normalized or "upgrade" in normalized:
        return "update"
    if "check if" in normalized or "verify" in normalized:
        return "status"
    if "install" in normalized or "download and install" in normalized:
        return "install"
    return "launch"


def _system_lane(normalized: str) -> str:
    if any(token in normalized for token in ("network", "wifi", "wi-fi", "internet", "speed")):
        return "network"
    if any(token in normalized for token in ("battery", "power")):
        return "power"
    if any(token in normalized for token in ("storage", "disk")):
        return "storage"
    if any(token in normalized for token in ("cpu", "ram", "memory usage")):
        return "resources"
    return "machine"


def _safe_to_short_circuit(
    *,
    likely: list[str],
    confidence: float,
    needs_deictic_context: bool,
    needs_workspace_context: bool,
    needs_recent_tool_results: bool,
    needs_semantic_memory: bool,
    needs_screen_context: bool,
    clarification_likely: bool,
) -> bool:
    if not likely or confidence < 0.9 or clarification_likely:
        return False
    if needs_deictic_context or needs_workspace_context or needs_recent_tool_results or needs_semantic_memory or needs_screen_context:
        return False
    return likely[0] in {"calculations", "web_retrieval", "browser_destination", "software_control", "voice_control", "trust_approvals"}


def _excluded_families(likely: list[str], confidence: float, safe_to_short_circuit: bool) -> tuple[str, ...]:
    if not likely or confidence < 0.82:
        return ()
    protected = set(likely)
    if safe_to_short_circuit:
        return tuple(family for family in _ALL_NATIVE_ROUTE_FAMILIES if family not in protected)
    return tuple(family for family in _SEAM_ROUTE_FAMILIES if family not in protected)


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.9:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"
