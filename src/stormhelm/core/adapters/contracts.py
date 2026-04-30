from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from typing import Any, Callable


class TrustTier(StrEnum):
    PASSIVE = "passive"
    BOUNDED_LOCAL = "bounded_local"
    LOCAL_NETWORK = "local_network"
    LOCAL_MUTATION = "local_mutation"
    EXTERNAL_DISPATCH = "external_dispatch"
    PRIVILEGED_LOCAL = "privileged_local"


class ClaimOutcome(StrEnum):
    NONE = "none"
    PREVIEW = "preview"
    INITIATED = "initiated"
    OBSERVED = "observed"
    COMPLETED = "completed"
    VERIFIED = "verified"


_CLAIM_ORDER: dict[ClaimOutcome, int] = {
    ClaimOutcome.NONE: 0,
    ClaimOutcome.PREVIEW: 1,
    ClaimOutcome.INITIATED: 2,
    ClaimOutcome.OBSERVED: 3,
    ClaimOutcome.COMPLETED: 4,
    ClaimOutcome.VERIFIED: 5,
}


def _coerce_claim(value: ClaimOutcome | str | None, *, fallback: ClaimOutcome = ClaimOutcome.NONE) -> ClaimOutcome:
    if isinstance(value, ClaimOutcome):
        return value
    try:
        return ClaimOutcome(str(value or "").strip())
    except ValueError:
        return fallback


def clamp_claim_outcome(
    requested: ClaimOutcome | str | None,
    *,
    maximum: ClaimOutcome | str | None,
) -> ClaimOutcome:
    requested_claim = _coerce_claim(requested)
    maximum_claim = _coerce_claim(maximum)
    if _CLAIM_ORDER[requested_claim] <= _CLAIM_ORDER[maximum_claim]:
        return requested_claim
    return maximum_claim


def claim_outcome_from_verification_strength(strength: str | None) -> ClaimOutcome:
    normalized = str(strength or "").strip().lower()
    if normalized == "strong":
        return ClaimOutcome.VERIFIED
    if normalized == "moderate":
        return ClaimOutcome.OBSERVED
    if normalized in {"weak", "low", "limited", "none"}:
        return ClaimOutcome.INITIATED
    return ClaimOutcome.INITIATED


@dataclass(slots=True)
class ApprovalDescriptor:
    required: bool
    preview_allowed: bool = False
    preview_required: bool = False
    suggested_scope: str | None = None
    available_scopes: list[str] = field(default_factory=list)
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "preview_allowed": self.preview_allowed,
            "preview_required": self.preview_required,
            "suggested_scope": self.suggested_scope,
            "available_scopes": list(self.available_scopes),
            "note": self.note,
        }


@dataclass(slots=True)
class RollbackDescriptor:
    supported: bool
    posture: str
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "posture": self.posture,
            "note": self.note,
        }


@dataclass(slots=True)
class VerificationDescriptor:
    posture: str
    max_claimable_outcome: ClaimOutcome
    evidence: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "posture": self.posture,
            "max_claimable_outcome": self.max_claimable_outcome.value,
            "evidence": list(self.evidence),
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class AdapterContract:
    adapter_id: str
    display_name: str
    family: str
    description: str
    observation_modes: list[str]
    action_modes: list[str]
    artifact_modes: list[str]
    preview_modes: list[str]
    safety_posture: list[str]
    failure_posture: list[str]
    trust_tier: TrustTier
    approval: ApprovalDescriptor
    verification: VerificationDescriptor
    rollback: RollbackDescriptor
    planner_tags: list[str] = field(default_factory=list)
    local_first: bool = True
    external_side_effects: bool = False
    offline_behavior: str = "full"

    def preview_available(self) -> bool:
        return self.approval.preview_allowed or self.approval.preview_required or bool(self.preview_modes)

    def planner_view(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "display_name": self.display_name,
            "family": self.family,
            "description": self.description,
            "trust_tier": self.trust_tier.value,
            "approval_required": self.approval.required,
            "preview_available": self.preview_available(),
            "preview_required": self.approval.preview_required,
            "rollback_available": self.rollback.supported,
            "max_claimable_outcome": self.verification.max_claimable_outcome.value,
            "local_first": self.local_first,
            "external_side_effects": self.external_side_effects,
            "offline_behavior": self.offline_behavior,
            "planner_tags": list(self.planner_tags),
            "observation_modes": list(self.observation_modes),
            "action_modes": list(self.action_modes),
            "artifact_modes": list(self.artifact_modes),
            "preview_modes": list(self.preview_modes),
            "safety_posture": list(self.safety_posture),
            "failure_posture": list(self.failure_posture),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.planner_view(),
            "approval": self.approval.to_dict(),
            "verification": self.verification.to_dict(),
            "rollback": self.rollback.to_dict(),
        }


@dataclass(slots=True)
class AdapterExecutionReport:
    adapter_id: str
    success: bool
    claim_ceiling: ClaimOutcome
    approval_required: bool
    preview_required: bool
    rollback_available: bool
    evidence: list[str] = field(default_factory=list)
    verification_observed: str | None = None
    failure_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "success": self.success,
            "claim_ceiling": self.claim_ceiling.value,
            "approval_required": self.approval_required,
            "preview_required": self.preview_required,
            "rollback_available": self.rollback_available,
            "evidence": list(self.evidence),
            "verification_observed": self.verification_observed,
            "failure_kind": self.failure_kind,
        }


def build_execution_report(
    contract: AdapterContract,
    *,
    success: bool,
    observed_outcome: ClaimOutcome | str | None,
    evidence: list[str] | None = None,
    verification_observed: str | None = None,
    failure_kind: str | None = None,
) -> AdapterExecutionReport:
    requested_outcome = _coerce_claim(observed_outcome, fallback=ClaimOutcome.NONE if not success else ClaimOutcome.PREVIEW)
    claim_ceiling = clamp_claim_outcome(requested_outcome, maximum=contract.verification.max_claimable_outcome)
    if not success and _CLAIM_ORDER[claim_ceiling] > _CLAIM_ORDER[ClaimOutcome.PREVIEW]:
        claim_ceiling = ClaimOutcome.NONE
    return AdapterExecutionReport(
        adapter_id=contract.adapter_id,
        success=success,
        claim_ceiling=claim_ceiling,
        approval_required=contract.approval.required,
        preview_required=contract.approval.preview_required,
        rollback_available=contract.rollback.supported,
        evidence=list(evidence or []),
        verification_observed=verification_observed,
        failure_kind=failure_kind,
    )


def attach_contract_metadata(
    payload: dict[str, Any],
    *,
    contract: AdapterContract | None,
    execution: AdapterExecutionReport | None,
) -> dict[str, Any]:
    enriched = dict(payload)
    if contract is not None:
        enriched["adapter_contract"] = contract.to_dict()
    if execution is not None:
        enriched["adapter_execution"] = execution.to_dict()
    return enriched


_Resolver = Callable[[dict[str, Any]], str | None]
_RoutePredicate = Callable[[dict[str, Any]], bool]


@dataclass(slots=True)
class AdapterRouteAssessment:
    tool_name: str
    contract_required: bool
    candidate_contracts: list[AdapterContract] = field(default_factory=list)
    selected_contract: AdapterContract | None = None
    errors: list[str] = field(default_factory=list)
    binding_mode: str = "always"

    @property
    def healthy(self) -> bool:
        return not self.errors and (not self.contract_required or self.selected_contract is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "contract_required": self.contract_required,
            "healthy": self.healthy,
            "binding_mode": self.binding_mode,
            "candidate_adapters": [contract.planner_view() for contract in self.candidate_contracts],
            "selected_adapter": self.selected_contract.planner_view() if self.selected_contract is not None else None,
            "errors": list(self.errors),
        }


@dataclass(slots=True)
class _ValidationFailure:
    kind: str
    subject: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "message": self.message,
        }


@dataclass(slots=True)
class _ToolBinding:
    adapter_ids: list[str]
    resolver: _Resolver | None = None
    applies: _RoutePredicate | None = None


def _require_text(field_name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _validate_text_list(
    field_name: str,
    values: object,
    *,
    allow_empty: bool,
) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list of non-empty strings.")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _require_text(field_name, item)
        if text in seen:
            raise ValueError(f"{field_name} contains a duplicate value: {text!r}.")
        seen.add(text)
        cleaned.append(text)
    if not allow_empty and not cleaned:
        raise ValueError(f"{field_name} must declare at least one value.")
    return cleaned


class AdapterContractRegistry:
    def __init__(self) -> None:
        self._contracts: dict[str, AdapterContract] = {}
        self._tool_bindings: dict[str, _ToolBinding] = {}
        self._tool_requirements: dict[str, _RoutePredicate | None] = {}
        self._validation_failures: list[_ValidationFailure] = []

    def register_contract(self, contract: AdapterContract) -> None:
        adapter_id = str(getattr(contract, "adapter_id", "") or "").strip() or "<invalid>"
        try:
            self._validate_contract(contract)
        except ValueError as error:
            self._record_validation_failure("contract", adapter_id, str(error))
            raise
        if contract.adapter_id in self._contracts:
            message = f"Adapter contract '{contract.adapter_id}' is already registered."
            self._record_validation_failure("contract", contract.adapter_id, message)
            raise ValueError(message)
        self._contracts[contract.adapter_id] = contract

    def bind_tool(
        self,
        tool_name: str,
        adapter_ids: list[str],
        *,
        resolver: _Resolver | None = None,
        applies: _RoutePredicate | None = None,
    ) -> None:
        normalized_tool_name = str(tool_name or "").strip() or "<invalid>"
        try:
            binding = self._validate_binding(tool_name, adapter_ids, resolver=resolver, applies=applies)
        except ValueError as error:
            self._record_validation_failure("binding", normalized_tool_name, str(error))
            raise
        self.declare_tool_route(binding[0], applies=applies)
        self._tool_bindings[binding[0]] = _ToolBinding(
            adapter_ids=list(binding[1]),
            resolver=resolver,
            applies=applies,
        )

    def declare_tool_route(
        self,
        tool_name: str,
        *,
        applies: _RoutePredicate | None = None,
    ) -> None:
        normalized_tool_name = str(tool_name or "").strip() or "<invalid>"
        try:
            _require_text("tool_name", tool_name)
            if applies is not None and not callable(applies):
                raise ValueError(f"Tool route '{normalized_tool_name}' applies predicate must be callable.")
        except ValueError as error:
            self._record_validation_failure("binding", normalized_tool_name, str(error))
            raise
        self._tool_requirements[normalized_tool_name] = applies

    def get_contract(self, adapter_id: str) -> AdapterContract:
        try:
            return self._contracts[adapter_id]
        except KeyError as error:
            raise KeyError(f"Unknown adapter contract: {adapter_id}") from error

    def list_contracts(self) -> list[AdapterContract]:
        return [self._contracts[key] for key in sorted(self._contracts)]

    def contracts_for_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> list[AdapterContract]:
        binding = self._tool_bindings.get(tool_name)
        if binding is None:
            return []
        if arguments is not None and binding.applies is not None and not binding.applies(dict(arguments)):
            return []
        return [self._contracts[adapter_id] for adapter_id in binding.adapter_ids]

    def resolve_tool_contract(self, tool_name: str, arguments: dict[str, Any] | None = None) -> AdapterContract | None:
        assessment = self.assess_tool_route(tool_name, arguments)
        if not assessment.healthy:
            return None
        return assessment.selected_contract

    def assess_tool_route(self, tool_name: str, arguments: dict[str, Any] | None = None) -> AdapterRouteAssessment:
        binding = self._tool_bindings.get(tool_name)
        normalized_arguments = dict(arguments or {})
        requirement_declared = tool_name in self._tool_requirements
        requirement = self._tool_requirements.get(tool_name)
        binding_mode = "conditional" if requirement_declared and requirement is not None else ("always" if requirement_declared else "unbound")
        contract_required = False
        if not requirement_declared:
            if binding is None:
                return AdapterRouteAssessment(tool_name=tool_name, contract_required=False, binding_mode="unbound")
            binding_mode = "conditional" if binding.applies is not None else "always"
            if binding.applies is None:
                contract_required = True
            elif binding.applies(normalized_arguments):
                contract_required = True
        elif requirement is None:
            contract_required = True
        elif requirement(normalized_arguments):
            contract_required = True
        if not contract_required:
            return AdapterRouteAssessment(
                tool_name=tool_name,
                contract_required=False,
                binding_mode=binding_mode,
            )
        if binding is None:
            return AdapterRouteAssessment(
                tool_name=tool_name,
                contract_required=True,
                binding_mode=binding_mode,
                errors=[f"Tool route '{tool_name}' requires adapter contract backing, but no binding is declared."],
            )
        binding_mode = "conditional" if binding.applies is not None else "always"
        candidate_contracts = [self._contracts[adapter_id] for adapter_id in binding.adapter_ids]
        errors: list[str] = []
        selected_contract: AdapterContract | None = None
        if binding.resolver is not None:
            adapter_id = binding.resolver(normalized_arguments)
            if adapter_id is None:
                errors.append(
                    f"Tool route '{tool_name}' requires contract resolution, but no declared adapter was selected."
                )
            elif adapter_id not in self._contracts:
                errors.append(
                    f"Tool route '{tool_name}' resolved undeclared adapter contract '{adapter_id}'."
                )
            elif adapter_id not in binding.adapter_ids:
                errors.append(
                    f"Tool route '{tool_name}' resolved adapter contract '{adapter_id}' outside its declared binding."
                )
            else:
                selected_contract = self._contracts[adapter_id]
        elif len(binding.adapter_ids) == 1:
            selected_contract = candidate_contracts[0]
        else:
            errors.append(
                f"Tool route '{tool_name}' has multiple candidate adapter contracts but no selected declared adapter."
            )
        return AdapterRouteAssessment(
            tool_name=tool_name,
            contract_required=True,
            candidate_contracts=candidate_contracts,
            selected_contract=selected_contract,
            errors=errors,
            binding_mode=binding_mode,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "contract_count": len(self._contracts),
            "healthy_contract_count": len(self._contracts),
            "invalid_contract_count": sum(1 for failure in self._validation_failures if failure.kind == "contract"),
            "tool_binding_count": len(self._tool_bindings),
            "invalid_binding_count": sum(1 for failure in self._validation_failures if failure.kind == "binding"),
            "validation_failure_count": len(self._validation_failures),
            "validation_failures": [failure.to_dict() for failure in self._validation_failures],
            "families": sorted({contract.family for contract in self._contracts.values()}),
            "route_enforced_tools": sorted(self._tool_requirements),
            "tool_bindings": {
                tool_name: list(binding.adapter_ids)
                for tool_name, binding in sorted(self._tool_bindings.items(), key=lambda item: item[0])
            },
            "tool_binding_modes": {
                tool_name: (
                    "conditional"
                    if self._tool_requirements.get(tool_name) is not None
                    else "always"
                )
                for tool_name in sorted(self._tool_requirements)
            },
        }

    def _record_validation_failure(self, kind: str, subject: str, message: str) -> None:
        self._validation_failures.append(_ValidationFailure(kind=kind, subject=subject, message=message))

    def _validate_contract(self, contract: AdapterContract) -> None:
        adapter_id = _require_text("adapter_id", contract.adapter_id)
        try:
            _require_text("display_name", contract.display_name)
            _require_text("family", contract.family)
            _require_text("description", contract.description)
            _require_text("offline_behavior", contract.offline_behavior)
            _validate_text_list("observation_modes", contract.observation_modes, allow_empty=False)
            _validate_text_list("action_modes", contract.action_modes, allow_empty=False)
            _validate_text_list("artifact_modes", contract.artifact_modes, allow_empty=False)
            _validate_text_list("preview_modes", contract.preview_modes, allow_empty=True)
            _validate_text_list("safety_posture", contract.safety_posture, allow_empty=False)
            _validate_text_list("failure_posture", contract.failure_posture, allow_empty=False)
            _validate_text_list("planner_tags", contract.planner_tags, allow_empty=True)
            _validate_text_list("approval.available_scopes", contract.approval.available_scopes, allow_empty=True)
            _require_text("verification.posture", contract.verification.posture)
            _validate_text_list("verification.evidence", contract.verification.evidence, allow_empty=False)
            _validate_text_list("verification.notes", contract.verification.notes, allow_empty=True)
            _require_text("rollback.posture", contract.rollback.posture)
        except ValueError as error:
            raise ValueError(f"Invalid adapter contract '{adapter_id}': {error}") from error
        approval = contract.approval
        if approval.preview_required and not approval.preview_allowed:
            raise ValueError(
                f"Invalid adapter contract '{adapter_id}': approval.preview_required requires approval.preview_allowed."
            )
        if approval.required and not approval.available_scopes:
            raise ValueError(
                f"Invalid adapter contract '{adapter_id}': approval.available_scopes must be declared when approval is required."
            )
        if approval.suggested_scope:
            suggested_scope = _require_text("approval.suggested_scope", approval.suggested_scope)
            if approval.available_scopes and suggested_scope not in approval.available_scopes:
                raise ValueError(
                    f"Invalid adapter contract '{adapter_id}': approval.suggested_scope must be one of approval.available_scopes."
                )

    def _validate_binding(
        self,
        tool_name: str,
        adapter_ids: list[str],
        *,
        resolver: _Resolver | None,
        applies: _RoutePredicate | None,
    ) -> tuple[str, list[str]]:
        normalized_tool_name = _require_text("tool_name", tool_name)
        normalized_adapter_ids = _validate_text_list("adapter_ids", adapter_ids, allow_empty=False)
        missing = [adapter_id for adapter_id in normalized_adapter_ids if adapter_id not in self._contracts]
        if missing:
            raise ValueError(f"Unknown adapter contracts for binding '{normalized_tool_name}': {missing}")
        if len(normalized_adapter_ids) > 1 and resolver is None:
            raise ValueError(
                f"Tool binding '{normalized_tool_name}' must declare a resolver when multiple adapter contracts are bound."
            )
        if resolver is not None and not callable(resolver):
            raise ValueError(f"Tool binding '{normalized_tool_name}' resolver must be callable.")
        if applies is not None and not callable(applies):
            raise ValueError(f"Tool binding '{normalized_tool_name}' applies predicate must be callable.")
        return normalized_tool_name, normalized_adapter_ids


def _resolve_external_open_url(arguments: dict[str, Any]) -> str | None:
    url = str(arguments.get("url") or "").strip().lower()
    if url.startswith("ms-settings:"):
        return "settings.system_uri"
    return "browser.external"


def _resolve_system_control(arguments: dict[str, Any]) -> str | None:
    action = str(arguments.get("action") or "").strip().lower()
    if action == "open_settings_page":
        return "settings.system_page"
    return None


def _resolve_app_or_window_control(arguments: dict[str, Any]) -> str | None:
    action = str(arguments.get("action") or "").strip().lower()
    if action in {"close", "quit"}:
        return "app.desktop_graceful_close"
    return "app.desktop_control"


def _supports_system_control_contract_route(arguments: dict[str, Any]) -> bool:
    return _resolve_system_control(arguments) is not None


def _resolve_web_retrieval(arguments: dict[str, Any]) -> str | None:
    provider = str(
        arguments.get("provider")
        or arguments.get("preferred_provider")
        or arguments.get("selected_provider")
        or ""
    ).strip().lower()
    intent = str(arguments.get("intent") or "").strip().lower()
    if provider in {"obscura_cdp", "obscura.cdp", "cdp"} or intent.startswith("cdp_"):
        return "web_retrieval.obscura.cdp"
    return "web_retrieval.obscura.cli"


@lru_cache(maxsize=1)
def default_adapter_contract_registry() -> AdapterContractRegistry:
    registry = AdapterContractRegistry()
    registry.register_contract(
        AdapterContract(
            adapter_id="browser.deck",
            display_name="Deck Browser Adapter",
            family="browser",
            description="Queues a URL into Stormhelm's internal Deck browser surface.",
            observation_modes=["url_metadata"],
            action_modes=["queue_open"],
            artifact_modes=["deck_browser_item"],
            preview_modes=[],
            safety_posture=["local_first", "backend_owned", "no_external_handoff"],
            failure_posture=["explicit_queue_only"],
            trust_tier=TrustTier.BOUNDED_LOCAL,
            approval=ApprovalDescriptor(required=False),
            verification=VerificationDescriptor(
                posture="queued_action_only",
                max_claimable_outcome=ClaimOutcome.INITIATED,
                evidence=["workspace action emission"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["deck", "browser", "local"],
            local_first=True,
            external_side_effects=False,
            offline_behavior="full",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="browser.external",
            display_name="External Browser Adapter",
            family="browser",
            description="Hands a URL to an external browser target without claiming the page was verified open.",
            observation_modes=["url_validation"],
            action_modes=["external_handoff"],
            artifact_modes=["external_open_request"],
            preview_modes=[],
            safety_posture=["external_handoff", "truthful_limits"],
            failure_posture=["handoff_only", "no_false_open_claims"],
            trust_tier=TrustTier.EXTERNAL_DISPATCH,
            approval=ApprovalDescriptor(
                required=True,
                suggested_scope="session",
                available_scopes=["once", "session", "task"],
                note="External browser handoff can leave Stormhelm's local surface.",
            ),
            verification=VerificationDescriptor(
                posture="handoff_acknowledgement",
                max_claimable_outcome=ClaimOutcome.INITIATED,
                evidence=["open request emission"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["browser", "external"],
            local_first=False,
            external_side_effects=True,
            offline_behavior="partial",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="settings.system_uri",
            display_name="Settings URI Adapter",
            family="settings",
            description="Hands a Windows settings URI to the shell without claiming the page is visibly open yet.",
            observation_modes=["uri_validation"],
            action_modes=["external_settings_handoff"],
            artifact_modes=["settings_open_request"],
            preview_modes=[],
            safety_posture=["local_system_surface", "truthful_limits"],
            failure_posture=["handoff_only"],
            trust_tier=TrustTier.BOUNDED_LOCAL,
            approval=ApprovalDescriptor(required=True, suggested_scope="session", available_scopes=["once", "session", "task"]),
            verification=VerificationDescriptor(
                posture="handoff_acknowledgement",
                max_claimable_outcome=ClaimOutcome.INITIATED,
                evidence=["settings URI dispatch"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["settings", "uri"],
            local_first=True,
            external_side_effects=True,
            offline_behavior="full",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="settings.system_page",
            display_name="System Settings Page Adapter",
            family="settings",
            description="Opens a Windows settings page through the native system control surface.",
            observation_modes=["page_target"],
            action_modes=["open_settings_page"],
            artifact_modes=["settings_open_request"],
            preview_modes=[],
            safety_posture=["local_system_surface", "backend_owned"],
            failure_posture=["explicit_action_result"],
            trust_tier=TrustTier.BOUNDED_LOCAL,
            approval=ApprovalDescriptor(required=False),
            verification=VerificationDescriptor(
                posture="system_acknowledgement",
                max_claimable_outcome=ClaimOutcome.INITIATED,
                evidence=["native system control response"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["settings", "system_control"],
            local_first=True,
            external_side_effects=False,
            offline_behavior="full",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="file.deck",
            display_name="Deck File Adapter",
            family="file",
            description="Queues an allowlisted file into the Deck viewer after local path validation.",
            observation_modes=["path_exists", "allowlist_check"],
            action_modes=["queue_open"],
            artifact_modes=["deck_file_item"],
            preview_modes=[],
            safety_posture=["allowlisted_only", "local_first"],
            failure_posture=["explicit_missing_file"],
            trust_tier=TrustTier.BOUNDED_LOCAL,
            approval=ApprovalDescriptor(required=False),
            verification=VerificationDescriptor(
                posture="queue_only",
                max_claimable_outcome=ClaimOutcome.INITIATED,
                evidence=["allowlisted file inspection", "workspace action emission"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["file", "deck"],
            local_first=True,
            external_side_effects=False,
            offline_behavior="full",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="file.external",
            display_name="External File Adapter",
            family="file",
            description="Hands an allowlisted file path to the native external application without claiming it visibly opened.",
            observation_modes=["path_exists", "allowlist_check"],
            action_modes=["external_handoff"],
            artifact_modes=["external_open_request"],
            preview_modes=[],
            safety_posture=["allowlisted_only", "truthful_limits"],
            failure_posture=["handoff_only"],
            trust_tier=TrustTier.EXTERNAL_DISPATCH,
            approval=ApprovalDescriptor(required=True, suggested_scope="session", available_scopes=["once", "session", "task"]),
            verification=VerificationDescriptor(
                posture="handoff_acknowledgement",
                max_claimable_outcome=ClaimOutcome.INITIATED,
                evidence=["allowlisted file inspection", "open request emission"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["file", "external"],
            local_first=True,
            external_side_effects=True,
            offline_behavior="full",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="file.operation",
            display_name="File Operation Adapter",
            family="file",
            description="Runs bounded local file mutations with preview posture and explicit filesystem-backed completion limits.",
            observation_modes=["path_scan", "filesystem_postcheck"],
            action_modes=["rename", "move", "archive", "deduplicate", "analyze"],
            artifact_modes=["filesystem_diff", "preview_report"],
            preview_modes=["dry_run"],
            safety_posture=["bounded_local_changes", "preview_supported"],
            failure_posture=["partial_results_explicit", "bounded_failures"],
            trust_tier=TrustTier.LOCAL_MUTATION,
            approval=ApprovalDescriptor(
                required=True,
                preview_allowed=True,
                suggested_scope="task",
                available_scopes=["once", "task", "session"],
                note="Local file mutation may change allowlisted workspace state.",
            ),
            verification=VerificationDescriptor(
                posture="filesystem_postcheck",
                max_claimable_outcome=ClaimOutcome.COMPLETED,
                evidence=["filesystem change result", "preview diff"],
            ),
            rollback=RollbackDescriptor(supported=True, posture="conditional", note="Undo is operation-specific and may require planned reverse steps."),
            planner_tags=["file", "mutation", "preview"],
            local_first=True,
            external_side_effects=False,
            offline_behavior="full",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="app.desktop_control",
            display_name="Desktop App Control Adapter",
            family="app",
            description="Issues typed Windows app/window control requests and reports only the level of acknowledgement the OS returned.",
            observation_modes=["window_match", "process_match"],
            action_modes=[
                "launch",
                "focus",
                "minimize",
                "maximize",
                "restore",
                "restart",
            ],
            artifact_modes=["system_action_result"],
            preview_modes=[],
            safety_posture=["typed_actions", "backend_owned", "truthful_limits"],
            failure_posture=["explicit_match_failure", "explicit_reason_codes"],
            trust_tier=TrustTier.LOCAL_MUTATION,
            approval=ApprovalDescriptor(required=True, suggested_scope="task", available_scopes=["once", "task", "session"]),
            verification=VerificationDescriptor(
                posture="os_api_acknowledgement",
                max_claimable_outcome=ClaimOutcome.OBSERVED,
                evidence=["window resolution", "OS action response"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["app", "desktop_control"],
            local_first=True,
            external_side_effects=False,
            offline_behavior="full",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="terminal.shell_stub",
            display_name="Shell Stub Adapter",
            family="terminal",
            description="Represents a terminal lane that is present for planning and approval posture, but disabled for execution here.",
            observation_modes=["command_capture"],
            action_modes=["shell_command_stub"],
            artifact_modes=["requested_command"],
            preview_modes=["manual_approval"],
            safety_posture=["disabled_by_default", "manual_gate"],
            failure_posture=["explicit_disabled_state"],
            trust_tier=TrustTier.PRIVILEGED_LOCAL,
            approval=ApprovalDescriptor(required=True, preview_allowed=True, suggested_scope="once", available_scopes=["once"]),
            verification=VerificationDescriptor(
                posture="disabled_stub",
                max_claimable_outcome=ClaimOutcome.PREVIEW,
                evidence=["requested command capture"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["terminal", "stub"],
            local_first=True,
            external_side_effects=False,
            offline_behavior="full",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="relay.discord_local_client",
            display_name="Discord Local Client Adapter",
            family="relay",
            description="Uses the local Discord client with preview-first dispatch and bounded delivery claims based on verification strength.",
            observation_modes=["current_context", "thread_verification"],
            action_modes=["preview_dispatch", "send_via_local_client"],
            artifact_modes=["preview_payload", "dispatch_trace"],
            preview_modes=["mandatory_preview"],
            safety_posture=["preview_required", "truthful_delivery_limits"],
            failure_posture=["stale_preview_refusal", "wrong_thread_refusal", "duplicate_suppression"],
            trust_tier=TrustTier.EXTERNAL_DISPATCH,
            approval=ApprovalDescriptor(
                required=True,
                preview_allowed=True,
                preview_required=True,
                suggested_scope="once",
                available_scopes=["once", "session"],
                note="Discord relay leaves Stormhelm's local workspace and requires explicit approval.",
            ),
            verification=VerificationDescriptor(
                posture="route_strength_bounded",
                max_claimable_outcome=ClaimOutcome.VERIFIED,
                evidence=["local client route", "verification strength"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["relay", "discord", "preview"],
            local_first=False,
            external_side_effects=True,
            offline_behavior="partial",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="relay.discord_official_scaffold",
            display_name="Discord Official Scaffold Adapter",
            family="relay",
            description="Represents the official Discord route scaffold without overclaiming send capability before that adapter is fully implemented.",
            observation_modes=["route_selection"],
            action_modes=["scaffold_only"],
            artifact_modes=["relay_scaffold"],
            preview_modes=["mandatory_preview"],
            safety_posture=["preview_required", "scaffold_only"],
            failure_posture=["explicit_scaffold_limits"],
            trust_tier=TrustTier.EXTERNAL_DISPATCH,
            approval=ApprovalDescriptor(required=True, preview_allowed=True, preview_required=True, suggested_scope="once", available_scopes=["once", "session"]),
            verification=VerificationDescriptor(
                posture="scaffold_only",
                max_claimable_outcome=ClaimOutcome.PREVIEW,
                evidence=["scaffold route only"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["relay", "discord", "scaffold"],
            local_first=False,
            external_side_effects=True,
            offline_behavior="partial",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="app.desktop_graceful_close",
            display_name="Desktop Graceful Close Adapter",
            family="app",
            description="Sends a Windows graceful close request to a matched top-level window and verifies the close result before claiming closure.",
            observation_modes=["window_match", "process_match", "post_close_window_check", "confirmation_prompt_detection"],
            action_modes=["graceful_close", "close", "quit", "force_close_requires_approval"],
            artifact_modes=["system_action_result", "close_trace"],
            preview_modes=[],
            safety_posture=["typed_actions", "backend_owned", "truthful_limits", "no_default_force_close"],
            failure_posture=[
                "explicit_match_failure",
                "explicit_reason_codes",
                "confirmation_required",
                "force_close_requires_approval",
            ],
            trust_tier=TrustTier.LOCAL_MUTATION,
            approval=ApprovalDescriptor(required=True, suggested_scope="task", available_scopes=["once", "task", "session"]),
            verification=VerificationDescriptor(
                posture="close_request_with_postcheck",
                max_claimable_outcome=ClaimOutcome.VERIFIED,
                evidence=["window resolution", "OS action response", "post-close window/process check"],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=["app", "desktop_control", "graceful_close"],
            local_first=True,
            external_side_effects=False,
            offline_behavior="full",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="web_retrieval.obscura.cli",
            display_name="Obscura Web Renderer",
            family="web_retrieval",
            description=(
                "Runs the optional Obscura CLI against public URLs and returns bounded "
                "rendered-page evidence without truth or visible-screen claims."
            ),
            observation_modes=[
                "public_url_validation",
                "provider_readiness",
                "rendered_page_output",
            ],
            action_modes=[
                "fetch_public_url",
                "render_javascript",
                "extract_text",
                "extract_links",
                "extract_html",
            ],
            artifact_modes=[
                "rendered_page_evidence",
                "text_excerpt",
                "link_list",
                "bounded_html",
            ],
            preview_modes=["evidence_preview"],
            safety_posture=[
                "backend_owned",
                "public_web_only",
                "external_network",
                "local_subprocess",
                "no_logged_in_context",
                "no_forms_or_clicks",
                "no_truth_verification",
                "no_user_visible_screen_claim",
                "bounded_output",
                "credentials_redacted",
            ],
            failure_posture=[
                "binary_missing_explicit",
                "timeout_explicit",
                "partial_extraction_explicit",
                "fallback_explicit",
            ],
            trust_tier=TrustTier.EXTERNAL_DISPATCH,
            approval=ApprovalDescriptor(required=False, preview_allowed=True),
            verification=VerificationDescriptor(
                posture="rendered_page_evidence_only",
                max_claimable_outcome=ClaimOutcome.OBSERVED,
                evidence=["provider process result", "extracted page text and link counts"],
                notes=["Does not verify truth or the user's visible screen."],
            ),
            rollback=RollbackDescriptor(supported=False, posture="none"),
            planner_tags=[
                "web_retrieval",
                "obscura",
                "public_web",
                "rendered_page_evidence",
            ],
            local_first=False,
            external_side_effects=False,
            offline_behavior="partial",
        )
    )
    registry.register_contract(
        AdapterContract(
            adapter_id="web_retrieval.obscura.cdp",
            display_name="Obscura CDP Renderer",
            family="web_retrieval",
            description=(
                "Starts a bounded local Obscura CDP session for public-page inspection "
                "and returns headless page evidence without browser actions, login context, "
                "truth verification, or visible-screen claims."
            ),
            observation_modes=[
                "public_url_validation",
                "provider_readiness",
                "local_cdp_endpoint_probe",
                "headless_page_inspection",
            ],
            action_modes=[
                "web.cdp.start_local_session",
                "web.cdp.navigate_public_url",
                "web.cdp.extract_title",
                "web.cdp.extract_current_url",
                "web.cdp.extract_dom_text",
                "web.cdp.extract_links",
                "web.cdp.extract_html_excerpt",
                "web.cdp.network_summary",
            ],
            artifact_modes=[
                "headless_cdp_page_evidence",
                "dom_text_excerpt",
                "link_list",
                "bounded_html_excerpt",
                "network_summary",
                "console_summary",
            ],
            preview_modes=["evidence_preview"],
            safety_posture=[
                "backend_owned",
                "localhost_bind_only",
                "public_web_only",
                "external_network",
                "local_subprocess",
                "no_logged_in_context",
                "no_cookies",
                "no_input_domain",
                "no_forms_or_clicks",
                "no_playwright_control",
                "no_truth_verification",
                "no_user_visible_screen_claim",
                "bounded_output",
                "credentials_redacted",
            ],
            failure_posture=[
                "binary_missing_explicit",
                "startup_timeout_explicit",
                "endpoint_probe_failure_explicit",
                "redirect_block_explicit",
                "cleanup_explicit",
            ],
            trust_tier=TrustTier.LOCAL_NETWORK,
            approval=ApprovalDescriptor(required=False, preview_allowed=True),
            verification=VerificationDescriptor(
                posture="headless_cdp_page_evidence_only",
                max_claimable_outcome=ClaimOutcome.OBSERVED,
                evidence=[
                    "local CDP session lifecycle",
                    "page title/final URL",
                    "DOM text and link counts",
                    "bounded network/console summaries",
                ],
                notes=[
                    "Does not verify truth.",
                    "Does not observe the user's visible screen.",
                    "Does not click, type, submit forms, read cookies, or reuse logged-in context.",
                ],
            ),
            rollback=RollbackDescriptor(supported=False, posture="stop_local_session"),
            planner_tags=[
                "web_retrieval",
                "obscura",
                "cdp",
                "headless_cdp_page_evidence",
                "public_web",
            ],
            local_first=True,
            external_side_effects=False,
            offline_behavior="partial",
        )
    )
    registry.bind_tool("deck_open_url", ["browser.deck"])
    registry.bind_tool("external_open_url", ["browser.external", "settings.system_uri"], resolver=_resolve_external_open_url)
    registry.bind_tool("deck_open_file", ["file.deck"])
    registry.bind_tool("external_open_file", ["file.external"])
    registry.bind_tool("file_operation", ["file.operation"])
    registry.bind_tool(
        "app_control",
        ["app.desktop_control", "app.desktop_graceful_close"],
        resolver=_resolve_app_or_window_control,
    )
    registry.bind_tool(
        "window_control",
        ["app.desktop_control", "app.desktop_graceful_close"],
        resolver=_resolve_app_or_window_control,
    )
    registry.bind_tool("shell_command", ["terminal.shell_stub"])
    registry.bind_tool(
        "system_control",
        ["settings.system_page"],
        resolver=_resolve_system_control,
        applies=_supports_system_control_contract_route,
    )
    registry.bind_tool(
        "web_retrieval_fetch",
        ["web_retrieval.obscura.cli", "web_retrieval.obscura.cdp"],
        resolver=_resolve_web_retrieval,
    )
    return registry
