from __future__ import annotations

import pytest

from stormhelm.core.adapters import AdapterContract
from stormhelm.core.adapters import AdapterContractRegistry
from stormhelm.core.adapters import ApprovalDescriptor
from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import RollbackDescriptor
from stormhelm.core.adapters import TrustTier
from stormhelm.core.adapters import VerificationDescriptor
from stormhelm.core.adapters import default_adapter_contract_registry


def _future_contract(adapter_id: str) -> AdapterContract:
    return AdapterContract(
        adapter_id=adapter_id,
        display_name=adapter_id.replace(".", " ").title(),
        family="future",
        description="Scaffold contract for validation and routing tests.",
        observation_modes=["semantic_context"],
        action_modes=["scaffold_only"],
        artifact_modes=["metadata"],
        preview_modes=["plan_only"],
        safety_posture=["backend_owned"],
        failure_posture=["explicit_limits"],
        trust_tier=TrustTier.BOUNDED_LOCAL,
        approval=ApprovalDescriptor(required=False, preview_allowed=True),
        verification=VerificationDescriptor(
            posture="scaffold_only",
            max_claimable_outcome=ClaimOutcome.PREVIEW,
            evidence=["future scaffolding only"],
        ),
        rollback=RollbackDescriptor(supported=False, posture="none"),
        planner_tags=["future"],
        local_first=True,
        external_side_effects=False,
        offline_behavior="full",
    )


def test_default_adapter_contract_registry_covers_core_adapter_families() -> None:
    registry = default_adapter_contract_registry()

    snapshot = registry.snapshot()

    assert {"browser", "app", "file", "relay", "settings", "terminal", "web_retrieval"}.issubset(set(snapshot["families"]))
    assert snapshot["healthy_contract_count"] >= snapshot["contract_count"]
    assert snapshot["validation_failure_count"] == 0
    assert registry.resolve_tool_contract("external_open_url", {"url": "https://example.com"}) is not None
    assert registry.resolve_tool_contract("external_open_url", {"url": "https://example.com"}).adapter_id == "browser.external"  # type: ignore[union-attr]
    assert registry.resolve_tool_contract("external_open_url", {"url": "ms-settings:bluetooth"}).adapter_id == "settings.system_uri"  # type: ignore[union-attr]
    assert registry.resolve_tool_contract("app_control", {"action": "focus", "app_name": "discord"}).adapter_id == "app.desktop_control"  # type: ignore[union-attr]
    assert registry.resolve_tool_contract("deck_open_file", {"path": "C:/Stormhelm/notes/test.md"}).adapter_id == "file.deck"  # type: ignore[union-attr]
    assert registry.resolve_tool_contract("shell_command", {"command": "dir"}).adapter_id == "terminal.shell_stub"  # type: ignore[union-attr]
    assert registry.resolve_tool_contract("web_retrieval_fetch", {"provider": "obscura"}).adapter_id == "web_retrieval.obscura.cli"  # type: ignore[union-attr]


def test_obscura_web_retrieval_contract_keeps_strict_claim_ceiling() -> None:
    contract = default_adapter_contract_registry().get_contract("web_retrieval.obscura.cli")

    assert contract.family == "web_retrieval"
    assert contract.trust_tier == TrustTier.EXTERNAL_DISPATCH
    assert contract.verification.max_claimable_outcome == ClaimOutcome.OBSERVED
    assert "rendered_page_evidence" in contract.artifact_modes
    assert "public_web_only" in contract.safety_posture
    assert "no_truth_verification" in contract.safety_posture
    assert "no_user_visible_screen_claim" in contract.safety_posture
    assert "click" not in contract.action_modes
    assert "form_submit" not in contract.action_modes


def test_obscura_cdp_contract_keeps_headless_page_evidence_ceiling() -> None:
    registry = default_adapter_contract_registry()
    contract = registry.get_contract("web_retrieval.obscura.cdp")

    assert contract.family == "web_retrieval"
    assert contract.trust_tier == TrustTier.LOCAL_NETWORK
    assert contract.verification.max_claimable_outcome == ClaimOutcome.OBSERVED
    assert "headless_cdp_page_evidence" in contract.artifact_modes
    assert "web.cdp.start_local_session" in contract.action_modes
    assert "web.cdp.navigate_public_url" in contract.action_modes
    assert "browser.input.click" not in contract.action_modes
    assert "browser.input.type" not in contract.action_modes
    assert "browser.cookies.read" not in contract.action_modes
    assert "browser.visible_screen_verify" not in contract.artifact_modes
    assert "no_truth_verification" in contract.safety_posture
    assert "no_logged_in_context" in contract.safety_posture

    assert registry.resolve_tool_contract(
        "web_retrieval_fetch",
        {"preferred_provider": "obscura_cdp"},
    ).adapter_id == "web_retrieval.obscura.cdp"  # type: ignore[union-attr]


def test_adapter_contract_registry_supports_future_bindings() -> None:
    registry = AdapterContractRegistry()
    registry.register_contract(_future_contract("future.vision_probe"))
    registry.bind_tool("future_probe", ["future.vision_probe"])

    resolved = registry.resolve_tool_contract("future_probe", {})

    assert resolved is not None
    assert resolved.adapter_id == "future.vision_probe"
    assert "future" in registry.snapshot()["families"]


def test_adapter_contract_registry_rejects_malformed_contracts_and_records_failure() -> None:
    registry = AdapterContractRegistry()
    malformed = _future_contract("future.invalid")
    malformed.family = ""
    malformed.action_modes = []

    with pytest.raises(ValueError, match="future.invalid"):
        registry.register_contract(malformed)

    snapshot = registry.snapshot()

    assert snapshot["contract_count"] == 0
    assert snapshot["healthy_contract_count"] == 0
    assert snapshot["invalid_contract_count"] == 1
    assert snapshot["validation_failure_count"] == 1
    assert snapshot["validation_failures"][0]["subject"] == "future.invalid"
    assert snapshot["validation_failures"][0]["kind"] == "contract"


def test_adapter_contract_registry_rejects_ambiguous_multi_binding_without_resolver() -> None:
    registry = AdapterContractRegistry()
    registry.register_contract(_future_contract("future.alpha"))
    registry.register_contract(_future_contract("future.beta"))

    with pytest.raises(ValueError, match="future_switch"):
        registry.bind_tool("future_switch", ["future.alpha", "future.beta"])

    snapshot = registry.snapshot()

    assert snapshot["tool_binding_count"] == 0
    assert snapshot["invalid_binding_count"] == 1
    assert snapshot["validation_failure_count"] == 1
    assert snapshot["validation_failures"][0]["subject"] == "future_switch"
    assert snapshot["validation_failures"][0]["kind"] == "binding"


def test_adapter_contract_registry_assesses_conditional_contract_routes() -> None:
    registry = default_adapter_contract_registry()

    settings_route = registry.assess_tool_route("system_control", {"action": "open_settings_page"})
    plain_route = registry.assess_tool_route("system_control", {"action": "lock_workstation"})

    assert settings_route.contract_required is True
    assert settings_route.healthy is True
    assert settings_route.selected_contract is not None
    assert settings_route.selected_contract.adapter_id == "settings.system_page"
    assert plain_route.contract_required is False
    assert plain_route.healthy is True
    assert plain_route.selected_contract is None


def test_adapter_contract_registry_marks_declared_route_without_binding_as_invalid() -> None:
    registry = AdapterContractRegistry()
    registry.declare_tool_route("future_orphan_route")

    assessment = registry.assess_tool_route("future_orphan_route", {})

    assert assessment.contract_required is True
    assert assessment.healthy is False
    assert assessment.selected_contract is None
    assert "no binding is declared" in assessment.errors[0].lower()
