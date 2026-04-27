from __future__ import annotations

from stormhelm.core.voice.evaluation import audit_voice_release_events
from stormhelm.core.voice.evaluation import audit_voice_release_payload
from stormhelm.core.voice.evaluation import voice_release_readiness_matrix


def test_voice20_payload_audit_catches_authority_privacy_and_copy_regressions() -> None:
    findings = audit_voice_release_payload(
        {
            "status": "Realtime assistant active. Always listening.",
            "realtime": {
                "direct_tools_allowed": True,
                "direct_action_tools_exposed": True,
                "raw_audio": b"audio",
            },
            "api_key": "secret-test-key",
            "result": "Done and verified.",
        }
    )

    assert "direct_tools_allowed_true" in findings["authority_boundary_findings"]
    assert "direct_action_tools_exposed_true" in findings["authority_boundary_findings"]
    assert "raw_audio_key_present:realtime.raw_audio" in findings["redaction_findings"]
    assert "secret_key_present:api_key" in findings["redaction_findings"]
    assert "forbidden_copy:always listening" in findings["ui_payload_findings"]
    assert "overclaim:done_without_core_completion" in findings["result_state_findings"]
    assert "overclaim:verified_without_core_verification" in findings["result_state_findings"]


def test_voice20_event_audit_catches_partial_transcript_core_route_and_fake_tool_exec() -> None:
    findings = audit_voice_release_events(
        [
            {
                "event_type": "voice.realtime_partial_transcript",
                "session_id": "session-1",
                "realtime_session_id": "rt-1",
                "core_request_id": "core-should-not-exist",
                "privacy": {"no_raw_audio": True},
            },
            {
                "event_type": "voice.realtime_direct_tool_blocked",
                "session_id": "session-1",
                "tool_execution_started": True,
                "privacy": {"no_raw_audio": True},
            },
            {
                "event_type": "voice.spoken_confirmation_accepted",
                "session_id": "session-1",
                "action_completed": True,
                "privacy": {"no_raw_audio": True},
            },
        ]
    )

    assert "partial_transcript_routed_core" in findings["authority_boundary_findings"]
    assert "direct_tool_blocked_looked_executed" in findings["authority_boundary_findings"]
    assert "confirmation_acceptance_claimed_action_completed" in findings["authority_boundary_findings"]


def test_voice20_release_matrix_documents_all_hardening_rows() -> None:
    matrix = voice_release_readiness_matrix()

    rows = {row["capability"]: row for row in matrix}
    assert rows["Wake local-only"]["authority_boundary"] == "local wake only; no command authority"
    assert rows["Realtime speech-to-speech Core bridge"]["authority_boundary"] == (
        "stormhelm_core_request only; no direct tools"
    )
    assert rows["Privacy/redaction"]["release_posture"] == "hardened"
    assert rows["Latency instrumentation"]["tests"]
    assert all("implemented" in row for row in matrix)
