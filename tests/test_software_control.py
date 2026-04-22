from __future__ import annotations

import shutil

from stormhelm.core.software_control import SoftwareExecutionStatus
from stormhelm.core.software_control import SoftwareOperationRequest
from stormhelm.core.software_control import SoftwareOperationType
from stormhelm.core.software_control import build_software_control_subsystem
from stormhelm.core.software_recovery import build_software_recovery_subsystem


def test_software_control_prefers_trusted_package_manager_sources_before_browser_routes(temp_config) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    target = software.resolve_software_target("install firefox")
    sources = software.discover_software_sources(target)

    assert target is not None
    assert [source.kind.value for source in sources[:2]] == ["package_manager", "package_manager"]
    assert sources[0].route == "winget"
    assert sources[-1].kind.value == "browser_guided"


def test_software_control_builds_truthful_install_plan_with_confirmation_gate(temp_config) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    target = software.resolve_software_target("install firefox")
    sources = software.discover_software_sources(target)
    plan = software.plan_software_operation(
        operation_type=SoftwareOperationType.INSTALL,
        target=target,
        sources=sources,
    )

    assert plan.target.canonical_name == "firefox"
    assert plan.selected_source is not None
    assert plan.selected_source.route == "winget"
    assert plan.presentation_depth == "ghost"
    assert plan.requires_command_deck is False
    assert [step.status.value for step in plan.steps[:4]] == [
        "found",
        "uncertain",
        "prepared",
        "waiting_confirmation",
    ]


def test_software_control_hands_adapter_failure_to_recovery_with_route_switch(temp_config) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    response = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-1",
            source_surface="ghost",
            raw_input="continue installing firefox",
            user_visible_text="continue installing firefox",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="confirm_execution",
            follow_up_reuse=True,
        ),
    )

    assert response.result is not None
    assert response.result.status == SoftwareExecutionStatus.RECOVERY_IN_PROGRESS
    assert response.recovery_plan is not None
    assert response.recovery_result is not None
    assert response.trace.recovery_invoked is True
    assert response.recovery_result.route_switched_to == "vendor_installer"


def test_software_control_resolves_minecraft_to_trusted_local_routes(temp_config) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    target = software.resolve_software_target("download and install minecraft")
    sources = software.discover_software_sources(target)

    assert target is not None
    assert target.canonical_name == "minecraft"
    assert sources
    assert sources[0].route == "winget"
    assert sources[0].locator == "Mojang.MinecraftLauncher"


def test_software_control_does_not_offer_unverified_browser_route_when_trusted_sources_only(temp_config) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    target = software.resolve_software_target("install some made up tool")
    sources = software.discover_software_sources(target)

    assert target is not None
    assert target.canonical_name == "some made up tool"
    assert sources == []


def test_software_control_verifies_local_install_state_without_confirmation(temp_config, monkeypatch) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    original_which = shutil.which

    def fake_which(name: str) -> str | None:
        if name == "git":
            return r"C:\Program Files\Git\cmd\git.exe"
        return original_which(name)

    monkeypatch.setattr("stormhelm.core.software_control.service.shutil.which", fake_which)

    response = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-verify-1",
            source_surface="ghost",
            raw_input="check if git is installed",
            user_visible_text="check if git is installed",
            operation_type=SoftwareOperationType.VERIFY,
            target_name="git",
            request_stage="prepare_plan",
            follow_up_reuse=False,
        ),
    )

    assert response.result is not None
    assert response.result.status == SoftwareExecutionStatus.VERIFIED
    assert response.verification is not None
    assert response.verification.status.value == "verified"
    assert response.active_request_state == {}
    assert "installed" in response.assistant_response.lower()
