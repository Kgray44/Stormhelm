from __future__ import annotations

import re

from stormhelm.config.models import SoftwareControlConfig
from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.software_control.catalog import find_catalog_target
from stormhelm.core.software_control.models import SoftwarePlannerEvaluation
from stormhelm.core.software_control.models import SoftwareRouteDisposition


_CONFIRMATION_PHRASES = {
    "continue",
    "continue please",
    "go ahead",
    "confirm",
    "yes",
    "do it",
    "proceed",
}

_DENIAL_PHRASES = {
    "deny",
    "no",
    "stop",
    "cancel",
    "don't",
    "do not",
    "never mind",
}

_DIRECT_REQUEST_PATTERNS: tuple[tuple[re.Pattern[str], str, bool], ...] = (
    (re.compile(r"^(?:(?:can|could)\s+you\s+)?(?:please\s+)?(?:downloads? and install|install)\s+(?P<target>.+)$"), "install", False),
    (re.compile(r"^(?:(?:can|could)\s+you\s+)?(?:please\s+)?(?:get|put)\s+(?P<target>.+?)\s+(?:on here|on this computer|on my computer|installed)$"), "install", False),
    (re.compile(r"^get\s+(?P<target>.+?)\s+installed$"), "install", False),
    (re.compile(r"^(?:set up|setup)\s+(?P<target>.+)$"), "install", True),
    (re.compile(r"^(?:update|upgrade)\s+(?P<target>.+)$"), "update", False),
    (re.compile(r"^check for updates?(?: for)?\s+(?P<target>.+)$"), "update", False),
    (re.compile(r"^(?:uninstall|remove)\s+(?P<target>.+)$"), "uninstall", False),
    (re.compile(r"^get rid of\s+(?P<target>.+)$"), "uninstall", False),
    (re.compile(r"^(?:repair|reinstall)\s+(?P<target>.+)$"), "repair", False),
    (re.compile(r"^fix\s+(?P<target>.+?)(?: installation)?$"), "repair", True),
    (re.compile(r"^(?:launch|open|start)\s+(?P<target>.+)$"), "launch", True),
    (re.compile(r"^(?:get)\s+(?P<target>.+?)\s+running$"), "launch", True),
    (re.compile(r"^check if\s+(?P<target>.+?)\s+is installed(?: correctly)?$"), "verify", False),
    (re.compile(r"^check whether\s+(?P<target>.+?)\s+is installed(?: correctly)?$"), "verify", False),
    (re.compile(r"^do\s+i\s+have\s+(?P<target>.+?)\s+installed(?: correctly)?$"), "verify", False),
    (re.compile(r"^is\s+(?P<target>.+?)\s+installed(?: correctly)?$"), "verify", False),
    (re.compile(r"^verify\s+(?P<target>.+?)\s+is installed(?: correctly)?$"), "verify", False),
    (re.compile(r"^what version of\s+(?P<target>.+?)\s+is installed$"), "verify", False),
    (re.compile(r"^verify\s+(?P<target>.+)$"), "verify", False),
)


class SoftwareControlPlannerSeam:
    def __init__(self, config: SoftwareControlConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        raw_text: str,
        normalized_text: str,
        surface_mode: str,
        active_module: str,
        active_request_state: dict[str, object] | None = None,
        active_context: dict[str, object] | None = None,
    ) -> SoftwarePlannerEvaluation:
        del raw_text, surface_mode, active_module, active_context
        lower = normalize_phrase(normalized_text)
        active_request_state = active_request_state or {}
        follow_up = self._follow_up_evaluation(lower, active_request_state)
        if follow_up is not None:
            return follow_up

        operation_type, target_name = self._direct_request(lower)
        if operation_type is None or not target_name:
            return SoftwarePlannerEvaluation(
                candidate=False,
                disposition=SoftwareRouteDisposition.NOT_REQUESTED,
                feature_enabled=self.config.enabled,
                planner_routing_enabled=self.config.planner_routing_enabled,
                route_confidence=0.0,
            )

        if not self.config.enabled:
            return SoftwarePlannerEvaluation(
                candidate=True,
                disposition=SoftwareRouteDisposition.FEATURE_DISABLED,
                operation_type=operation_type,
                target_name=target_name,
                request_stage="prepare_plan",
                feature_enabled=False,
                planner_routing_enabled=self.config.planner_routing_enabled,
                route_confidence=0.92,
                reasons=["software lifecycle intent detected but the subsystem is disabled"],
            )

        if not self.config.planner_routing_enabled:
            return SoftwarePlannerEvaluation(
                candidate=True,
                disposition=SoftwareRouteDisposition.ROUTING_DISABLED,
                operation_type=operation_type,
                target_name=target_name,
                request_stage="prepare_plan",
                feature_enabled=True,
                planner_routing_enabled=False,
                route_confidence=0.92,
                reasons=["software lifecycle intent detected but planner routing is disabled"],
            )

        return SoftwarePlannerEvaluation(
            candidate=True,
            disposition=SoftwareRouteDisposition.DIRECT_REQUEST,
            operation_type=operation_type,
            target_name=target_name,
            request_stage="prepare_plan",
            feature_enabled=True,
            planner_routing_enabled=True,
            route_confidence=0.96,
            reasons=["software lifecycle verb matched a native software-control route"],
        )

    def _follow_up_evaluation(
        self,
        lower: str,
        active_request_state: dict[str, object],
    ) -> SoftwarePlannerEvaluation | None:
        family = str(active_request_state.get("family") or "").strip().lower()
        parameters = active_request_state.get("parameters")
        params = dict(parameters) if isinstance(parameters, dict) else {}
        if family != "software_control":
            return None
        trust = active_request_state.get("trust") if isinstance(active_request_state.get("trust"), dict) else {}
        approval_outcome = "approve"
        if lower in _DENIAL_PHRASES or any(lower.startswith(f"{phrase} ") for phrase in _DENIAL_PHRASES):
            approval_outcome = "deny"
        elif not (
            lower in _CONFIRMATION_PHRASES
            or lower.startswith("continue ")
            or lower.startswith("confirm ")
            or lower.startswith("go ahead")
            or lower.startswith("allow ")
            or lower.startswith("approve ")
        ):
            return None
        operation_type = str(params.get("operation_type") or "").strip().lower()
        target_name = str(params.get("target_name") or active_request_state.get("subject") or "").strip().lower()
        if not operation_type or not target_name:
            return None
        if not self.config.enabled:
            disposition = SoftwareRouteDisposition.FEATURE_DISABLED
        elif not self.config.planner_routing_enabled:
            disposition = SoftwareRouteDisposition.ROUTING_DISABLED
        else:
            disposition = SoftwareRouteDisposition.FOLLOW_UP_CONFIRMATION
        approval_scope = "once"
        if "session" in lower:
            approval_scope = "session"
        elif "task" in lower:
            approval_scope = "task"
        return SoftwarePlannerEvaluation(
            candidate=True,
            disposition=disposition,
            operation_type=operation_type,
            target_name=target_name,
            request_stage="confirm_execution",
            feature_enabled=self.config.enabled,
            planner_routing_enabled=self.config.planner_routing_enabled,
            follow_up_reuse=True,
            approval_scope=approval_scope,
            approval_outcome=approval_outcome,
            trust_request_id=str(trust.get("request_id") or "").strip() or None,
            route_confidence=0.99,
            reasons=["follow-up confirmation matched a pending software-control request"],
        )

    def _direct_request(self, lower: str) -> tuple[str | None, str]:
        for pattern, operation, require_catalog_match in _DIRECT_REQUEST_PATTERNS:
            match = pattern.match(lower)
            if match is None:
                continue
            target = self._normalize_target_name(match.group("target"))
            if not target:
                continue
            catalog_target = find_catalog_target(target)
            if require_catalog_match and catalog_target is None:
                continue
            if operation == "launch" and catalog_target is not None and not self._launch_routed_through_software_control(
                catalog_target.canonical_name
            ):
                continue
            return operation, target
        return None, ""

    def _normalize_target_name(self, raw_target: str) -> str:
        target = normalize_phrase(raw_target)
        target = re.sub(r"\s+because\b.*$", "", target)
        target = re.sub(r"\b(?:my|the|a|an)\b", " ", target)
        target = re.sub(r"\b(?:app|application)\b$", "", target)
        target = re.sub(r"\b(?:installation|install)\b$", "", target)
        target = " ".join(target.split()).strip(" .")
        return target

    def _launch_routed_through_software_control(self, canonical_name: str) -> bool:
        return canonical_name not in {"chrome", "firefox"}
