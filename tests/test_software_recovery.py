from __future__ import annotations

import json

from stormhelm.core.software_recovery import FailureEvent
from stormhelm.core.software_recovery import build_software_recovery_subsystem


class FakeCloudTroubleshooter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def diagnose(self, payload: dict[str, object]) -> list[dict[str, object]]:
        self.calls.append(dict(payload))
        return [
            {
                "summary": "Try the trusted vendor route instead of the unresolved package-manager route.",
                "confidence": 0.41,
                "recommended_route": "vendor_installer",
            }
        ]


def test_software_recovery_redacts_sensitive_context_before_cloud_fallback(temp_config) -> None:
    cloud = FakeCloudTroubleshooter()
    temp_config.software_recovery.cloud_fallback_enabled = True
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=True,
        cloud_troubleshooter=cloud,
    )
    failure = FailureEvent(
        failure_id="failure-1",
        operation_type="install",
        target_name="custom utility",
        stage="source_resolution",
        category="unresolved_target",
        message="Could not resolve a trusted source for C:\\Users\\kkids\\Secrets\\Installer.exe using sk-test-secret.",
    )

    context = recovery.build_troubleshooting_context(
        failure_event=failure,
        operation_plan={"requested_path": "C:\\Users\\kkids\\Downloads\\Installer.exe"},
        verification=None,
        local_signals={
            "log_excerpt": "OPENAI_API_KEY=sk-test-secret",
            "working_path": "C:\\Users\\kkids\\Documents\\Stormhelm\\private-notes.txt",
        },
    )
    recovery.diagnose_failure(context)

    assert cloud.calls
    serialized = json.dumps(cloud.calls[0])
    assert "sk-test-secret" not in serialized
    assert "C:\\Users\\kkids" not in serialized
    assert "<redacted_path>" in serialized
    assert "<redacted_token>" in serialized


def test_software_recovery_cloud_fallback_requires_openai_enablement_and_local_uncertainty(temp_config) -> None:
    cloud = FakeCloudTroubleshooter()
    temp_config.software_recovery.cloud_fallback_enabled = True
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=False,
        cloud_troubleshooter=cloud,
    )
    failure = FailureEvent(
        failure_id="failure-2",
        operation_type="install",
        target_name="firefox",
        stage="verification",
        category="verification_mismatch",
        message="Local verification found a clear version mismatch after install.",
    )

    context = recovery.build_troubleshooting_context(
        failure_event=failure,
        operation_plan={"target": "firefox"},
        verification={"status": "mismatch"},
        local_signals={"detected_version": "123.0", "expected_version": "124.0"},
    )
    plan = recovery.diagnose_failure(context)

    assert plan.cloud_fallback_disposition.value == "disabled"
    assert cloud.calls == []

