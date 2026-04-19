from __future__ import annotations

from typing import Any

from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.system.probe import SystemProbe
from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


def _probe(context: ToolContext) -> SystemProbe:
    return context.system_probe or SystemProbe(context.config)


class MachineStatusTool(BaseTool):
    name = "machine_status"
    display_name = "Machine Status"
    description = "Return Stormhelm's current machine identity, OS details, time zone, and local clock."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).machine_status()
        persona = PersonaContract(context.config)
        summary = persona.report(
            f"Systems report {data['machine_name']} on {data['platform']} in {data['timezone']}."
        )
        return ToolResult(success=True, summary=summary, data=data)


class PowerStatusTool(BaseTool):
    name = "power_status"
    display_name = "Power Status"
    description = "Return current battery and AC power bearings when available."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).power_status()
        persona = PersonaContract(context.config)
        if not data.get("available"):
            summary = persona.report("Power bearings are not available on this machine.")
        elif data.get("battery_percent") is None:
            summary = persona.report(f"AC line is {data.get('ac_line_status', 'unknown')} and no battery percentage is available.")
        else:
            summary = persona.report(
                f"Power is holding at {data['battery_percent']}% with AC line {data.get('ac_line_status', 'unknown')}."
            )
        return ToolResult(success=True, summary=summary, data=data)


class ResourceStatusTool(BaseTool):
    name = "resource_status"
    display_name = "Resource Status"
    description = "Return CPU, RAM, and GPU bearings for the current machine."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).resource_status()
        memory = data.get("memory", {})
        total_gb = round((memory.get("total_bytes", 0) or 0) / (1024**3), 1)
        free_gb = round((memory.get("free_bytes", 0) or 0) / (1024**3), 1)
        cpu = data.get("cpu", {})
        persona = PersonaContract(context.config)
        summary = persona.report(
            f"Resource bearings show {cpu.get('logical_processors', 0)} logical processors with {free_gb} GB free of {total_gb} GB memory."
        )
        return ToolResult(success=True, summary=summary, data=data)


class StorageStatusTool(BaseTool):
    name = "storage_status"
    display_name = "Storage Status"
    description = "Return disk and free-space bearings for mounted local drives."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).storage_status()
        drives = data.get("drives", [])
        persona = PersonaContract(context.config)
        if not drives:
            summary = persona.report("Storage bearings are unavailable right now.")
        else:
            primary = drives[0]
            free_gb = round((primary.get("free_bytes", 0) or 0) / (1024**3), 1)
            total_gb = round((primary.get("total_bytes", 0) or 0) / (1024**3), 1)
            summary = persona.report(
                f"Storage shows {free_gb} GB free on {primary.get('drive', 'the primary drive')} out of {total_gb} GB."
            )
        return ToolResult(success=True, summary=summary, data=data)


class NetworkStatusTool(BaseTool):
    name = "network_status"
    display_name = "Network Status"
    description = "Return current host and network interface bearings."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).network_status()
        interfaces = data.get("interfaces", [])
        persona = PersonaContract(context.config)
        if interfaces:
            summary = persona.report(
                f"Signal steady through {interfaces[0].get('interface_alias', 'the active interface')} on {data.get('hostname', 'this machine')}."
            )
        else:
            summary = persona.report(f"Network bearings are limited, but {data.get('hostname', 'this machine')} is on watch.")
        return ToolResult(success=True, summary=summary, data=data)


class ActiveAppsTool(BaseTool):
    name = "active_apps"
    display_name = "Active Apps"
    description = "Return the current visible desktop applications and windows."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).active_apps()
        apps = data.get("applications", [])
        persona = PersonaContract(context.config)
        if apps:
            summary = persona.report(f"Watch has {len(apps)} visible application windows in view.")
        else:
            summary = persona.report("Watch does not currently see any visible application windows.")
        return ToolResult(success=True, summary=summary, data=data)


class RecentFilesTool(BaseTool):
    name = "recent_files"
    display_name = "Recent Files"
    description = "Return recently modified files from Stormhelm's allowlisted local bearings."
    category = "system"

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        del arguments
        data = _probe(context).recent_files()
        files = data.get("files", [])
        persona = PersonaContract(context.config)
        if files:
            summary = persona.report(f"Recent file bearings recovered {len(files)} local items from the current watch.")
        else:
            summary = persona.report("Recent file bearings are empty right now.")
        return ToolResult(success=True, summary=summary, data=data)
