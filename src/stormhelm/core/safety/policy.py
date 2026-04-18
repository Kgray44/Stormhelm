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

