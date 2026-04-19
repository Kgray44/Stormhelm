from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from stormhelm.core.orchestrator.router import ToolRequest


@dataclass(slots=True)
class PlannerDecision:
    tool_requests: list[ToolRequest] = field(default_factory=list)
    assistant_message: str | None = None


class DeterministicPlanner:
    def plan(
        self,
        message: str,
        *,
        session_id: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None = None,
    ) -> PlannerDecision:
        del active_module, workspace_context
        lower = message.strip().lower()
        if not lower:
            return PlannerDecision()

        if self._looks_like_workspace_restore(lower):
            return PlannerDecision(
                tool_requests=[ToolRequest("workspace_restore", {"query": message, "session_id": session_id})]
            )
        if self._looks_like_workspace_assemble(lower):
            return PlannerDecision(
                tool_requests=[ToolRequest("workspace_assemble", {"query": message, "session_id": session_id})]
            )
        if any(token in lower for token in {"battery", "charging", "plugged in", "power saver", "power state"}):
            return PlannerDecision(tool_requests=[ToolRequest("power_status")])
        if any(token in lower for token in {"storage", "disk space", "free space", "drive space"}):
            return PlannerDecision(tool_requests=[ToolRequest("storage_status")])
        if any(token in lower for token in {"wifi", "wi-fi", "network", "internet", "connected"}):
            return PlannerDecision(tool_requests=[ToolRequest("network_status")])
        if any(token in lower for token in {"running apps", "open apps", "active windows", "what is open", "open windows"}):
            return PlannerDecision(tool_requests=[ToolRequest("active_apps")])
        if any(token in lower for token in {"recent files", "recent documents", "what was i working on"}):
            return PlannerDecision(tool_requests=[ToolRequest("recent_files")])
        if any(token in lower for token in {"computer specs", "machine specs", "system specs", "hardware specs"}):
            return PlannerDecision(
                tool_requests=[ToolRequest("machine_status"), ToolRequest("resource_status"), ToolRequest("storage_status")]
            )
        if any(token in lower for token in {"cpu", "ram", "memory", "gpu", "resources"}):
            return PlannerDecision(tool_requests=[ToolRequest("resource_status")])
        if any(token in lower for token in {"machine name", "os version", "what computer", "what machine"}):
            return PlannerDecision(tool_requests=[ToolRequest("machine_status")])
        if surface_mode.strip().lower() == "ghost" and any(token in lower for token in {"open externally", "open in browser"}):
            return PlannerDecision(assistant_message="Standing by for a specific URL or file path to open externally.")
        return PlannerDecision()

    def should_escalate(
        self,
        message: str,
        *,
        tool_job_count: int,
        actions: list[dict[str, Any]],
        planner_text: str,
    ) -> bool:
        lower = message.lower()
        if tool_job_count > 1:
            return True
        if any(action.get("type") == "workspace_restore" for action in actions):
            return True
        if any(token in lower for token in {"compare", "explain", "why", "continue", "summarize", "restore", "workspace"}):
            return True
        return not bool(planner_text.strip())

    def _looks_like_workspace_restore(self, lower: str) -> bool:
        return (
            any(
                phrase in lower
                for phrase in {
                    "restore the workspace",
                    "open my workspace",
                    "continue where we left off",
                    "pick up where we left off",
                    "bring back the workspace",
                    "continue the ",
                }
            )
            and "workspace" in lower
        ) or "where we left off" in lower

    def _looks_like_workspace_assemble(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "set up a workspace",
                "setup a workspace",
                "gather everything relevant",
                "assemble a workspace",
                "open the project workspace",
                "workspace for ",
            }
        )
