from __future__ import annotations

from pathlib import Path

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

