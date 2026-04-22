from __future__ import annotations

from pathlib import Path

from stormhelm.config.models import AppConfig
from stormhelm.shared.result import SafetyClassification, SafetyDecision


class SafetyPolicy:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def authorize_tool(self, tool_name: str, classification: SafetyClassification) -> SafetyDecision:
        if not self.config.tools.enabled.is_enabled(tool_name):
            return SafetyDecision(False, f"Tool '{tool_name}' is disabled in configuration.")

        if classification == SafetyClassification.ACTION and tool_name == "shell_command":
            if not self.config.safety.allow_shell_stub:
                return SafetyDecision(False, "Shell command tool is disabled by safety policy.")

        return SafetyDecision(True, "Allowed by current safety policy.")

    def can_read_path(self, raw_path: str) -> SafetyDecision:
        candidate = Path(raw_path).expanduser().resolve()
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
