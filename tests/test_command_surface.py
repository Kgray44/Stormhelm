from __future__ import annotations

from stormhelm.ui.command_surface import build_command_surface_model


def test_command_surface_labels_trust_approvals_as_trust() -> None:
    model = build_command_surface_model(
        active_request_state={
            "family": "trust_approvals",
            "subject": "firefox",
            "parameters": {"request_stage": "awaiting_confirmation"},
            "trust": {"approval_state": "pending_operator_confirmation"},
        },
        active_task=None,
        recent_context_resolutions=None,
        latest_message={
            "bearing_title": "Approval Required",
            "content": "Approval is still pending.",
            "metadata": {
                "route_state": {
                    "winner": {
                        "route_family": "trust_approvals",
                        "query_shape": "trust_approval_request",
                        "posture": "clear_winner",
                        "status": "awaiting_confirmation",
                    }
                }
            },
        },
        status=None,
        workspace_focus=None,
    )

    assert model["ghostPrimaryCard"]["routeLabel"] == "Trust"
    assert model["requestComposer"]["chips"][0]["value"] == "Trust"


def test_command_surface_labels_workspace_operations_as_workspace() -> None:
    model = build_command_surface_model(
        active_request_state={
            "family": "workspace_operations",
            "subject": "packaging",
            "parameters": {"request_stage": "restore"},
        },
        active_task=None,
        recent_context_resolutions=None,
        latest_message={
            "bearing_title": "Workspace Restore",
            "content": "Packaging workspace is ready to restore.",
            "metadata": {
                "route_state": {
                    "winner": {
                        "route_family": "workspace_operations",
                        "query_shape": "workspace_request",
                        "posture": "clear_winner",
                        "status": "restore",
                    }
                }
            },
        },
        status=None,
        workspace_focus=None,
    )

    assert model["ghostPrimaryCard"]["routeLabel"] == "Workspace"
    assert model["requestComposer"]["chips"][0]["value"] == "Workspace"
