from __future__ import annotations

from stormhelm.core.judgment.models import ActionRiskTier
from stormhelm.core.judgment.service import JudgmentService
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.orchestrator.session_state import ConversationStateStore


def _service(temp_config) -> JudgmentService:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    preferences = PreferencesRepository(database)
    session_state = ConversationStateStore(preferences)
    return JudgmentService(config=temp_config, session_state=session_state)


def test_judgment_service_marks_force_quit_as_high_risk_and_suggests_relaunch(temp_config) -> None:
    service = _service(temp_config)

    pre = service.assess_pre_action(
        session_id="default",
        message="force quit Chrome",
        tool_requests=[ToolRequest("app_control", {"action": "force_quit", "app_name": "chrome"})],
        active_context={},
    )
    post = service.evaluate_post_action(
        session_id="default",
        message="force quit Chrome",
        jobs=[
            {
                "tool_name": "app_control",
                "arguments": {"action": "force_quit", "app_name": "chrome"},
                "result": {"success": True, "action": "force_quit", "process_name": "chrome"},
            }
        ],
        actions=[],
        active_context={},
        active_request_state={"family": "app_control", "parameters": {"action": "force_quit", "app_name": "chrome"}},
        pre_action=pre,
    )

    assert pre.risk_tier is ActionRiskTier.HIGH
    assert pre.outcome == "act_direct"
    assert post.next_suggestion is not None
    assert post.next_suggestion["title"] == "Relaunch Chrome"
    assert post.next_suggestion["command"] == "relaunch chrome"


def test_judgment_service_suppresses_repeated_ignored_suggestion(temp_config) -> None:
    service = _service(temp_config)

    pre = service.assess_pre_action(
        session_id="default",
        message="force quit Chrome",
        tool_requests=[ToolRequest("app_control", {"action": "force_quit", "app_name": "chrome"})],
        active_context={},
    )
    first = service.evaluate_post_action(
        session_id="default",
        message="force quit Chrome",
        jobs=[
            {
                "tool_name": "app_control",
                "arguments": {"action": "force_quit", "app_name": "chrome"},
                "result": {"success": True, "action": "force_quit", "process_name": "chrome"},
            }
        ],
        actions=[],
        active_context={},
        active_request_state={"family": "app_control", "parameters": {"action": "force_quit", "app_name": "chrome"}},
        pre_action=pre,
    )

    service.observe_operator_turn("default", "what is my battery level?")

    second = service.evaluate_post_action(
        session_id="default",
        message="force quit Chrome",
        jobs=[
            {
                "tool_name": "app_control",
                "arguments": {"action": "force_quit", "app_name": "chrome"},
                "result": {"success": True, "action": "force_quit", "process_name": "chrome"},
            }
        ],
        actions=[],
        active_context={},
        active_request_state={"family": "app_control", "parameters": {"action": "force_quit", "app_name": "chrome"}},
        pre_action=pre,
    )

    assert first.next_suggestion is not None
    assert second.next_suggestion is None
    assert second.suppressed_reason == "recently_ignored"
