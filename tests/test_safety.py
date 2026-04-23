from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from stormhelm.config.loader import load_config
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.shared.result import SafetyClassification


def test_safety_policy_allows_only_allowlisted_files(temp_config, temp_project_root: Path) -> None:
    inside_file = temp_project_root / "inside.txt"
    inside_file.write_text("safe", encoding="utf-8")
    outside_file = temp_project_root.parent / "outside.txt"
    outside_file.write_text("blocked", encoding="utf-8")

    policy = SafetyPolicy(temp_config)

    assert policy.can_read_path(str(inside_file)).allowed is True
    assert policy.can_read_path(str(outside_file)).allowed is False
    assert policy.authorize_tool("shell_command", SafetyClassification.ACTION).allowed is False


def test_safety_policy_blocks_disabled_software_routes(temp_config) -> None:
    temp_config.software_control.browser_guided_routes_enabled = False
    temp_config.software_control.privileged_operations_allowed = False
    policy = SafetyPolicy(temp_config)

    assert policy.authorize_software_route("browser_guided").allowed is False
    assert policy.authorize_software_route("winget").allowed is True
    assert policy.authorize_software_route("vendor_installer", requires_elevation=True).allowed is False


def test_safety_policy_unsafe_test_mode_bypasses_read_and_trust_gates(
    temp_project_root: Path,
    trust_harness,
) -> None:
    outside_file = temp_project_root.parent / "outside.txt"
    outside_file.write_text("open", encoding="utf-8")
    unsafe_config = load_config(
        project_root=temp_project_root,
        env={"STORMHELM_UNSAFE_TEST_MODE": "true"},
    )
    policy = SafetyPolicy(unsafe_config, trust_service=trust_harness["trust_service"])

    decision = policy.authorize_tool(
        "shell_command",
        SafetyClassification.ACTION,
        context=SimpleNamespace(job_id="job-unsafe", session_id="default", task_id=""),
        arguments={"command": "cmd /c echo unsafe-ok"},
    )

    assert policy.can_read_path(str(outside_file)).allowed is True
    assert decision.allowed is True
