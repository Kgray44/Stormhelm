from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from stormhelm.config.models import AppConfig
from stormhelm.core.adapters import AdapterContract
from stormhelm.core.trust import PermissionScope
from stormhelm.core.trust import TrustActionKind
from stormhelm.core.trust import TrustActionRequest
from stormhelm.shared.result import SafetyClassification, SafetyDecision

if TYPE_CHECKING:
    from stormhelm.core.tools.base import ToolContext


_TRUST_GATED_TOOL_NAMES = {
    "shell_command",
    "app_control",
    "window_control",
    "workflow_execute",
    "repair_action",
    "routine_execute",
    "trusted_hook_execute",
    "trusted_hook_register",
    "file_operation",
    "maintenance_action",
    "external_open_url",
    "external_open_file",
    "workspace_archive",
    "workspace_clear",
}


class SafetyPolicy:
    def __init__(self, config: AppConfig, *, trust_service: object | None = None) -> None:
        self.config = config
        self.trust_service = trust_service

    def authorize_tool(
        self,
        tool_name: str,
        classification: SafetyClassification,
        *,
        context: ToolContext | None = None,
        arguments: dict[str, object] | None = None,
        adapter_contract: AdapterContract | None = None,
    ) -> SafetyDecision:
        if not self.config.tools.enabled.is_enabled(tool_name):
            return SafetyDecision(False, f"Tool '{tool_name}' is disabled in configuration.")

        if classification == SafetyClassification.ACTION and self.config.safety.unsafe_test_mode:
            return SafetyDecision(
                True,
                "Unsafe test mode bypassed action safety gates.",
                details={"tool_name": tool_name, "unsafe_test_mode": True},
            )

        if classification == SafetyClassification.ACTION and tool_name == "shell_command":
            if not self.config.safety.allow_shell_stub:
                return SafetyDecision(False, "Shell command tool is disabled by safety policy.")

        contract_requires_approval = bool(adapter_contract is not None and adapter_contract.approval.required)
        if (
            classification == SafetyClassification.ACTION
            and (contract_requires_approval or tool_name in _TRUST_GATED_TOOL_NAMES)
            and self.trust_service is not None
            and context is not None
        ):
            task_scope = PermissionScope.TASK if str(context.task_id or "").strip() else PermissionScope.SESSION
            available_scopes = self._contract_scopes(adapter_contract, task_scope=task_scope)
            suggested_scope = self._contract_suggested_scope(adapter_contract, task_scope=task_scope)
            action_key = f"adapter.{adapter_contract.adapter_id}" if adapter_contract is not None else f"tool.{tool_name}"
            operator_subject = (
                adapter_contract.display_name if adapter_contract is not None else tool_name.replace("_", " ")
            )
            trust_request = TrustActionRequest(
                request_id=f"tool-{context.job_id}",
                family="tool",
                action_key=action_key,
                subject=str(tool_name),
                session_id=context.session_id,
                task_id=str(context.task_id or ""),
                action_kind=TrustActionKind.TOOL,
                approval_required=True,
                preview_allowed=bool(
                    adapter_contract is not None
                    and (adapter_contract.approval.preview_allowed or adapter_contract.approval.preview_required)
                ),
                suggested_scope=suggested_scope,
                available_scopes=available_scopes,
                operator_justification=self._tool_justification(tool_name, arguments or {}, adapter_contract=adapter_contract),
                operator_message=(
                    f"Approval is required before Stormhelm can use {operator_subject}."
                ),
                details={
                    "tool_name": tool_name,
                    "arguments": dict(arguments or {}),
                    "adapter_contract": adapter_contract.to_dict() if adapter_contract is not None else {},
                },
            )
            decision = self.trust_service.evaluate_action(trust_request)
            return SafetyDecision(
                decision.allowed,
                decision.reason,
                details=decision.to_dict(),
                approval_state=decision.approval_state.value,
                decision=decision.outcome.value,
                operator_message=decision.operator_message,
            )

        return SafetyDecision(True, "Allowed by current safety policy.")

    def can_read_path(self, raw_path: str) -> SafetyDecision:
        candidate = Path(raw_path).expanduser().resolve()
        if self.config.safety.unsafe_test_mode:
            return SafetyDecision(
                True,
                "Unsafe test mode allows unrestricted reads.",
                {"path": str(candidate), "unsafe_test_mode": True},
            )
        allowed = any(candidate.is_relative_to(base.resolve()) for base in self.config.safety.allowed_read_dirs)
        if allowed:
            return SafetyDecision(True, "Path is within an allowlisted directory.", {"path": str(candidate)})
        return SafetyDecision(
            False,
            "Path is outside allowlisted directories.",
            {"path": str(candidate), "allowed_read_dirs": [str(item) for item in self.config.safety.allowed_read_dirs]},
        )

    def authorize_software_route(self, route_kind: str, *, requires_elevation: bool = False) -> SafetyDecision:
        software = self.config.software_control
        normalized = str(route_kind or "").strip().lower()
        if self.config.safety.unsafe_test_mode:
            return SafetyDecision(
                True,
                "Unsafe test mode bypassed software route restrictions.",
                {"route_kind": normalized, "requires_elevation": requires_elevation, "unsafe_test_mode": True},
            )
        if requires_elevation and not software.privileged_operations_allowed:
            return SafetyDecision(
                False,
                "Privileged software operations are disabled by policy.",
                {"route_kind": normalized, "requires_elevation": True},
            )
        if normalized in {"winget", "chocolatey", "package_manager"} and not software.package_manager_routes_enabled:
            return SafetyDecision(
                False,
                "Package-manager software routes are disabled by policy.",
                {"route_kind": normalized},
            )
        if normalized == "vendor_installer" and not software.vendor_installer_routes_enabled:
            return SafetyDecision(
                False,
                "Vendor installer routes are disabled by policy.",
                {"route_kind": normalized},
            )
        if normalized in {"browser", "browser_guided"} and not software.browser_guided_routes_enabled:
            return SafetyDecision(
                False,
                "Browser-guided software acquisition is disabled by policy.",
                {"route_kind": normalized},
            )
        return SafetyDecision(
            True,
            "Allowed by current software safety policy.",
            {"route_kind": normalized, "requires_elevation": requires_elevation},
        )

    def _tool_justification(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        adapter_contract: AdapterContract | None = None,
    ) -> str:
        if adapter_contract is not None and adapter_contract.family == "relay":
            return "Discord relay can send material outside Stormhelm's local workspace."
        if tool_name == "file_operation":
            operation = str(arguments.get("operation") or "change files").replace("_", " ").strip()
            path = str(arguments.get("path") or "").strip()
            if path:
                return f"{operation.title()} may change local files at {path}."
            return f"{operation.title()} may change local files."
        if tool_name in {"external_open_url", "external_open_file"}:
            target = str(arguments.get("url") or arguments.get("path") or "").strip()
            return f"This will hand work off to a native external surface{f' ({target})' if target else ''}."
        if tool_name == "shell_command":
            return "Shell execution can change the local machine state."
        return f"{tool_name.replace('_', ' ').title()} can change the local system state."

    def _contract_scopes(
        self,
        adapter_contract: AdapterContract | None,
        *,
        task_scope: PermissionScope,
    ) -> list[PermissionScope]:
        if adapter_contract is None or not adapter_contract.approval.available_scopes:
            return [
                PermissionScope.ONCE,
                PermissionScope.TASK if task_scope == PermissionScope.TASK else PermissionScope.SESSION,
            ]
        scopes: list[PermissionScope] = []
        for raw_scope in adapter_contract.approval.available_scopes:
            scope = self._permission_scope(raw_scope, task_scope=task_scope)
            if scope not in scopes:
                scopes.append(scope)
        return scopes or [
            PermissionScope.ONCE,
            PermissionScope.TASK if task_scope == PermissionScope.TASK else PermissionScope.SESSION,
        ]

    def _contract_suggested_scope(
        self,
        adapter_contract: AdapterContract | None,
        *,
        task_scope: PermissionScope,
    ) -> PermissionScope:
        if adapter_contract is None or not adapter_contract.approval.suggested_scope:
            return task_scope
        return self._permission_scope(adapter_contract.approval.suggested_scope, task_scope=task_scope)

    def _permission_scope(self, raw_scope: str, *, task_scope: PermissionScope) -> PermissionScope:
        normalized = str(raw_scope or "").strip().lower()
        if normalized == PermissionScope.ONCE.value:
            return PermissionScope.ONCE
        if normalized == PermissionScope.TASK.value:
            return PermissionScope.TASK if task_scope == PermissionScope.TASK else PermissionScope.SESSION
        if normalized == PermissionScope.SESSION.value:
            return PermissionScope.SESSION
        return task_scope
