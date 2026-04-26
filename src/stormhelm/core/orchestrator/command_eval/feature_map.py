from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from stormhelm.config.loader import load_config
from stormhelm.core.adapters import default_adapter_contract_registry
from stormhelm.core.api.app import create_app
from stormhelm.core.orchestrator.planner_models import QueryShape
from stormhelm.core.orchestrator.planner_models import ResponseMode
from stormhelm.core.orchestrator.planner_models import RoutePosture
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.registry import ToolRegistry


def build_feature_map(*, project_root: Path | None = None) -> dict[str, Any]:
    root = (project_root or Path.cwd()).resolve()
    runtime_dir = root / ".artifacts" / "command-usability-eval" / "feature-map-runtime"
    config = load_config(
        project_root=root,
        env={
            "STORMHELM_DATA_DIR": str(runtime_dir),
            "STORMHELM_OPENAI_ENABLED": "false",
            "STORMHELM_HARDWARE_TELEMETRY_ENABLED": "false",
            "STORMHELM_SCREEN_AWARENESS_ACTION_POLICY_MODE": "observe_only",
        },
    )
    app = create_app(config)

    registry = ToolRegistry()
    register_builtin_tools(registry)
    tools = registry.metadata()
    tools_by_category: dict[str, list[str]] = defaultdict(list)
    for metadata in tools:
        tools_by_category[str(metadata.get("category") or "uncategorized")].append(str(metadata.get("name") or ""))

    contract_registry = default_adapter_contract_registry()
    api_routes = {
        route.path: sorted(route.methods or [])
        for route in app.routes
        if isinstance(route, APIRoute)
    }
    return {
        "generated_from": {
            "project_root": str(root),
            "source": "repo_introspection",
        },
        "input_boundary": {
            "endpoint": "POST /chat/send",
            "payload_fields": ["message", "session_id", "surface_mode", "active_module", "workspace_context", "input_context"],
            "ui_client": "stormhelm.ui.client.CoreApiClient.send_message",
            "core_handler": "stormhelm.core.api.app.send_chat -> AssistantOrchestrator.handle_message",
        },
        "api_routes": api_routes,
        "planner": {
            "query_shapes": [item.value for item in QueryShape],
            "response_modes": [item.value for item in ResponseMode],
            "route_postures": [item.value for item in RoutePosture],
            "telemetry_surface": "assistant_message.metadata.route_state",
            "obedience_surface": "assistant_message.metadata.planner_obedience",
        },
        "subsystems": {
            "calculations": asdict(config.calculations),
            "software_control": asdict(config.software_control),
            "software_recovery": asdict(config.software_recovery),
            "screen_awareness": asdict(config.screen_awareness),
            "discord_relay": {
                **asdict(config.discord_relay),
                "trusted_aliases": {alias: asdict(value) for alias, value in config.discord_relay.trusted_aliases.items()},
            },
            "trust": asdict(config.trust),
            "workspace": {"service": "WorkspaceService", "repository": "WorkspaceRepository", "indexer": "WorkspaceIndexer"},
            "jobs": {"manager": "JobManager", "tool_executor": "ToolExecutor", "tool_trace_surface": "/jobs and /events"},
            "events": asdict(config.event_stream),
            "provider": {"openai_enabled": config.openai.enabled, "fallback_surface": "generic_provider"},
            "lifecycle": asdict(config.lifecycle),
        },
        "tools": tools,
        "tools_by_category": {category: sorted(names) for category, names in sorted(tools_by_category.items())},
        "adapter_contracts": {
            "snapshot": contract_registry.snapshot(),
            "contracts": [contract.to_dict() for contract in contract_registry.list_contracts()],
        },
        "ui_state_surfaces": {
            "chat_response": [
                "assistant_message",
                "assistant_message.metadata",
                "jobs",
                "actions",
                "active_request_state",
                "recent_context_resolutions",
                "active_task",
            ],
            "snapshot": [
                "status",
                "events",
                "jobs",
                "history",
                "tools",
                "active_workspace",
                "active_request_state",
                "bridge_authority",
                "watch_state",
                "trust",
            ],
            "bridge_authority": "status.bridge_authority",
        },
        "support_paths": {
            "approval_trust_gates": ["TrustService", "SafetyPolicy", "assistant.active_request_state.trust"],
            "verification_paths": [
                "adapter_execution.claim_ceiling",
                "screen_awareness verification state",
                "discord relay verification strength",
                "software control prepared execution posture",
            ],
            "recovery_paths": ["software_recovery", "repair_action", "lifecycle resolution routes"],
            "telemetry_debug": ["route_state", "planner_debug", "planner_obedience", "events", "jobs", "bridge_authority"],
        },
    }
