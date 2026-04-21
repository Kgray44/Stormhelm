from __future__ import annotations

from typing import Any

from stormhelm.core.operations.service import OperationalAwarenessService
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.system.probe import SystemProbe
from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


def _probe(context: ToolContext) -> SystemProbe:
    return context.system_probe or SystemProbe(context.config, preferences=context.preferences)


def _focus_payload(*, module: str, section: str = "diagnostics", state_hint: str = "") -> dict[str, Any]:
    return {
        "action": {
            "type": "workspace_focus",
            "target": "deck",
            "module": module,
            "section": section,
            "state_hint": state_hint,
        }
    }


def _merge_data_with_focus(
    data: dict[str, Any],
    *,
    present_in: str,
    module: str,
    section: str = "diagnostics",
    state_hint: str = "",
) -> dict[str, Any]:
    payload = dict(data)
    if present_in == "deck":
        payload.update(_focus_payload(module=module, section=section, state_hint=state_hint))
    return payload


def _finding_summary(finding: dict[str, Any]) -> str:
    headline = str(finding.get("headline") or "").strip()
    summary = str(finding.get("summary") or "").strip()
    if not headline:
        return summary
    if not summary:
        return headline
    if summary.lower().startswith(headline.lower()):
        return summary
    return f"{headline}. {summary}"


def _coerce_finding(raw: Any, *, key: str, label: str) -> dict[str, Any]:
    if isinstance(raw, dict):
        finding = dict(raw)
        finding.setdefault("key", key)
        finding.setdefault("label", label)
        return finding
    return {"key": key, "label": label, "headline": "Diagnosis unavailable", "summary": "No diagnostic finding was returned."}


class PowerDiagnosisTool(BaseTool):
    name = "power_diagnosis"
    display_name = "Power Diagnosis"
    description = "Interpret battery and charging telemetry into evidence-based battery and power findings."
    category = "power"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "present_in": {"type": "string", "enum": ["none", "deck"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        present_in = str(arguments.get("present_in", "none")).strip().lower() or "none"
        return {"present_in": present_in}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        probe = _probe(context)
        service = OperationalAwarenessService()
        if hasattr(probe, "power_diagnosis") and callable(getattr(probe, "power_diagnosis")):
            finding = _coerce_finding(probe.power_diagnosis(), key="power", label="Battery")
        else:
            finding = service.assess_power(probe.power_status()).to_dict(key="power", label="Battery")
        persona = PersonaContract(context.config)
        summary = persona.report(_finding_summary(finding))
        payload = _merge_data_with_focus(
            {"finding": finding},
            present_in=arguments["present_in"],
            module="systems",
            section="diagnostics",
            state_hint="power-diagnosis",
        )
        return ToolResult(success=True, summary=summary, data=payload)


class ResourceDiagnosisTool(BaseTool):
    name = "resource_diagnosis"
    display_name = "Resource Diagnosis"
    description = "Interpret CPU, RAM, GPU, and storage posture into evidence-based machine-load findings."
    category = "system"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "present_in": {"type": "string", "enum": ["none", "deck"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        present_in = str(arguments.get("present_in", "none")).strip().lower() or "none"
        return {"present_in": present_in}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        probe = _probe(context)
        service = OperationalAwarenessService()
        if hasattr(probe, "resource_diagnosis") and callable(getattr(probe, "resource_diagnosis")):
            finding = _coerce_finding(probe.resource_diagnosis(), key="resources", label="Machine Load")
        else:
            finding = service.assess_resources(probe.resource_status(), probe.storage_status()).to_dict(
                key="resources",
                label="Machine Load",
            )
        persona = PersonaContract(context.config)
        summary = persona.report(_finding_summary(finding))
        payload = _merge_data_with_focus(
            {"finding": finding},
            present_in=arguments["present_in"],
            module="systems",
            section="diagnostics",
            state_hint="resource-diagnosis",
        )
        return ToolResult(success=True, summary=summary, data=payload)


class StorageDiagnosisTool(BaseTool):
    name = "storage_diagnosis"
    display_name = "Storage Diagnosis"
    description = "Interpret disk and free-space posture into evidence-based storage pressure findings."
    category = "system"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "present_in": {"type": "string", "enum": ["none", "deck"], "default": "none"},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        present_in = str(arguments.get("present_in", "none")).strip().lower() or "none"
        return {"present_in": present_in}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        probe = _probe(context)
        service = OperationalAwarenessService()
        if hasattr(probe, "storage_diagnosis") and callable(getattr(probe, "storage_diagnosis")):
            finding = _coerce_finding(probe.storage_diagnosis(), key="storage", label="Storage")
        else:
            finding = service.assess_storage(probe.storage_status()).to_dict(key="storage", label="Storage")
        persona = PersonaContract(context.config)
        summary = persona.report(_finding_summary(finding))
        payload = _merge_data_with_focus(
            {"finding": finding},
            present_in=arguments["present_in"],
            module="systems",
            section="diagnostics",
            state_hint="storage-diagnosis",
        )
        return ToolResult(success=True, summary=summary, data=payload)
