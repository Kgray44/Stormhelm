from __future__ import annotations

import os

from PySide6 import QtWidgets

from stormhelm.ui.bridge import UiBridge


def _ensure_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _authority_payload() -> dict[str, object]:
    return {
        "summary": {
            "mappedFamilyCount": 8,
            "commandableFamilyCount": 4,
            "inspectableFamilyCount": 8,
            "previewableFamilyCount": 5,
            "degradedFamilyCount": 1,
            "bridgeReadiness": "partial",
        },
        "routeFamilies": [
            "native_deterministic",
            "native_orchestration",
            "adapter_backed",
            "observational",
            "preview_and_confirm",
            "recovery",
            "ui_only",
        ],
        "resultStates": [
            "requested",
            "planned",
            "pending_approval",
            "executing",
            "completed",
            "verified",
            "failed",
            "blocked",
            "stale",
            "unknown",
        ],
        "families": [
            {
                "familyId": "trust",
                "label": "Trust",
                "ownerFamily": "trust",
                "routeFamily": "preview_and_confirm",
                "status": "pending_approval",
                "resultState": "pending_approval",
                "commandAuthority": "limited",
                "inspectAuthority": "available",
                "previewAuthority": "available",
                "displayOnlyZone": "none",
                "summary": "One trust decision is waiting for operator confirmation.",
                "supportedCommands": ["approval.review_via_chat", "approval.respond"],
            },
            {
                "familyId": "software",
                "label": "Software",
                "ownerFamily": "software",
                "routeFamily": "native_orchestration",
                "status": "ready",
                "resultState": "planned",
                "commandAuthority": "available",
                "inspectAuthority": "available",
                "previewAuthority": "available",
                "displayOnlyZone": "none",
                "summary": "Software plans and verification are backend-owned.",
                "supportedCommands": ["software.plan", "software.execute"],
            },
            {
                "familyId": "systems",
                "label": "Systems State",
                "ownerFamily": "systems",
                "routeFamily": "observational",
                "status": "ready",
                "resultState": "verified",
                "commandAuthority": "unavailable",
                "inspectAuthority": "available",
                "previewAuthority": "unavailable",
                "displayOnlyZone": "presentation_only",
                "summary": "Systems exposes telemetry truth but does not pretend to control hardware.",
                "supportedCommands": [],
            },
            {
                "familyId": "adapters",
                "label": "Adapters",
                "ownerFamily": "adapters",
                "routeFamily": "adapter_backed",
                "status": "degraded",
                "resultState": "blocked",
                "commandAuthority": "limited",
                "inspectAuthority": "available",
                "previewAuthority": "limited",
                "displayOnlyZone": "none",
                "summary": "Adapter contracts are visible with downgrade truth.",
                "degradedReason": "One adapter contract failed validation.",
                "supportedCommands": ["adapter.inspect"],
            },
        ],
        "ghostCards": [
            {
                "familyId": "trust",
                "title": "Approval Needed",
                "subtitle": "Install",
                "body": "Stormhelm needs confirmation before changing installed software.",
                "routeFamily": "preview_and_confirm",
                "resultState": "pending_approval",
                "actions": [{"label": "Review", "command": "approval.review_via_chat"}],
            }
        ],
        "deckSections": [
            {
                "title": "Commandable Families",
                "summary": "Real command lanes exposed by backend authority.",
                "entries": [
                    {
                        "title": "Software",
                        "status": "available",
                        "detail": "software.plan, software.execute",
                    }
                ],
            }
        ],
        "gapRegister": [
            {
                "familyId": "adapters",
                "severity": "degraded",
                "summary": "Adapter contract validation is degraded.",
            }
        ],
    }


def test_ui_bridge_surfaces_backend_authority_in_ghost_and_systems_deck(temp_config) -> None:
    _ensure_app()
    bridge = UiBridge(temp_config)

    bridge.apply_snapshot({"status": {"bridge_authority": _authority_payload()}})

    assert any(card["title"] == "Approval Needed" for card in bridge.context_cards)
    assert bridge.ghost_corner_readouts[2]["primary"] == "Approval Needed"
    assert bridge.ghost_corner_readouts[2]["secondary"] == "Stormhelm needs confirmation before changing installed software."

    bridge.setMode("deck")
    bridge.activateModule("systems")

    authority_group = next(
        group for group in bridge.workspaceCanvas["factGroups"] if group["title"] == "Bridge Authority"
    )
    assert any(row["label"] == "Mapped Families" and row["value"] == "8" for row in authority_group["rows"])
    assert any(row["label"] == "Commandable" and row["value"] == "4" for row in authority_group["rows"])
    assert any(row["label"] == "Gaps" and "Adapter contract" in row["detail"] for row in authority_group["rows"])

    assert any(column["title"] == "Authority Map" for column in bridge.workspaceCanvas["columns"])

    authority_column = next(column for column in bridge.workspaceCanvas["columns"] if column["title"] == "Authority Map")
    assert any(entry["primary"] == "Software" and entry["secondary"] == "Available" for entry in authority_column["entries"])
    assert any(entry["primary"] == "Systems State" and entry["secondary"] == "Unavailable" for entry in authority_column["entries"])
