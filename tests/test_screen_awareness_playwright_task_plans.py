from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any

import pytest

from stormhelm.core.events import EventBuffer
from stormhelm.core.screen_awareness import BrowserSemanticTaskPlan
from stormhelm.core.screen_awareness import BrowserSemanticTaskStep
from stormhelm.core.trust import PermissionScope
from stormhelm.ui.command_surface_v2 import build_command_surface_model

from test_screen_awareness_playwright_click_focus_execution import _FakeActionPlaywright
from test_screen_awareness_playwright_click_focus_execution import _all_browser_actions_config
from test_screen_awareness_playwright_click_focus_execution import _assert_no_submit_side_effects
from test_screen_awareness_playwright_click_focus_execution import _approved_click_plan
from test_screen_awareness_playwright_click_focus_execution import _approve_plan
from test_screen_awareness_playwright_click_focus_execution import _plan_observation
from test_screen_awareness_playwright_click_focus_execution import _subsystem_with_fake


def _task_plan_config():
    config = _all_browser_actions_config()
    playwright = config.browser_adapters.playwright
    playwright.allow_task_plans = True
    playwright.allow_dev_task_plans = True
    playwright.max_task_steps = 5
    playwright.stop_on_unverified_step = True
    playwright.stop_on_partial_step = True
    playwright.stop_on_ambiguous_step = True
    playwright.stop_on_unexpected_navigation = True
    return config


def _safe_steps(text: str = "task-plan sentinel text") -> list[dict[str, Any]]:
    return [
        {
            "action_kind": "type_text",
            "target_phrase": "Email field",
            "action_phrase": "type safe text into Email",
            "action_arguments": {"text": text},
            "expected_outcome": ["value_summary_changed"],
        },
        {
            "action_kind": "select_option",
            "target_phrase": "Country dropdown",
            "action_phrase": "select Canada from Country",
            "action_arguments": {"option": "Canada"},
            "expected_outcome": ["selected_option_changed"],
        },
        {
            "action_kind": "check",
            "target_phrase": "Newsletter checkbox",
            "action_phrase": "check Newsletter",
            "expected_outcome": ["checked_state_changed"],
        },
    ]


def _build_safe_task_plan(subsystem, *, text: str = "task-plan sentinel text") -> BrowserSemanticTaskPlan:
    return subsystem.build_playwright_browser_task_plan(
        _plan_observation(),
        task_phrase="enter safe text, select Canada, and check newsletter without submitting",
        steps=_safe_steps(text),
        expected_final_state=["Email redacted value present", "Canada selected", "Newsletter checked", "submit counter unchanged"],
    )


def _build_scroll_task_plan(subsystem) -> BrowserSemanticTaskPlan:
    return subsystem.build_playwright_browser_task_plan(
        _plan_observation(),
        task_phrase="scroll to the Privacy Policy link without clicking it",
        steps=[
            {
                "action_kind": "scroll_to_target",
                "target_phrase": "Privacy Policy link",
                "action_phrase": "scroll to Privacy Policy link",
                "action_arguments": {
                    "direction": "down",
                    "amount_pixels": 700,
                    "max_attempts": 2,
                    "target_phrase": "Privacy Policy link",
                },
                "expected_outcome": ["target_found"],
            }
        ],
        expected_final_state=["Privacy Policy link available", "submit counter unchanged"],
    )


def _approve_task_plan(subsystem, trust_service, plan: BrowserSemanticTaskPlan) -> None:
    pending = subsystem.request_playwright_browser_task_execution(
        plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_service,
        session_id="default",
        fixture_mode=True,
    )
    assert pending.status == "approval_required"
    trust_service.respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )


def _execute_task_plan(subsystem, trust_service, plan: BrowserSemanticTaskPlan | dict[str, Any]):
    return subsystem.execute_playwright_browser_task_plan(
        plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_service,
        session_id="default",
        fixture_mode=True,
    )


def test_task_plan_models_serialize_redacted_steps_without_raw_text() -> None:
    sentinel = "TASKPLAN-RAW-TEXT-SENTINEL-9"
    step = BrowserSemanticTaskStep(
        step_index=1,
        action_kind="type_text",
        target_phrase="Notes field",
        action_args_redacted={
            "typed_text_redacted": True,
            "text_redacted_summary": "[redacted text, 28 chars]",
            "text_length": len(sentinel),
            "text_fingerprint": "bounded-fingerprint",
        },
        action_arguments_private={"text": sentinel},
        expected_outcome=["value_summary_changed"],
        required_capability="browser.input.type_text",
        approval_binding_fingerprint="step-binding",
    )
    plan = BrowserSemanticTaskPlan(
        source_observation_id="observation-1",
        provider="playwright_live_semantic",
        steps=[step],
        max_steps=5,
        expected_final_state=["notes field changed"],
    )

    payload = json.dumps(plan.to_dict(), sort_keys=True)

    assert plan.claim_ceiling == "browser_semantic_task_plan"
    assert step.status == "pending"
    assert sentinel not in payload
    assert "[redacted text" in payload


def test_safe_task_plan_construction_is_bounded_and_rejects_submit_like_steps() -> None:
    subsystem = _subsystem_with_fake(_task_plan_config(), _FakeActionPlaywright())

    plan = _build_safe_task_plan(subsystem)
    blocked = subsystem.build_playwright_browser_task_plan(
        _plan_observation(),
        task_phrase="fill the form and submit it",
        steps=[
            {
                "action_kind": "submit_form",
                "target_phrase": "form",
                "action_phrase": "submit the form",
            }
        ],
    )

    assert plan.plan_kind == "safe_browser_sequence"
    assert plan.approval_required is True
    assert plan.executable_now is False
    assert len(plan.steps) == 3
    assert [step.action_kind for step in plan.steps] == ["type_text", "select_option", "check"]
    assert all(step.status == "pending" for step in plan.steps)
    assert blocked.executable_now is False
    assert blocked.reason_not_executable in {"unsupported_step", "restricted_step", "unsafe_task_step"}
    assert blocked.steps[0].status == "blocked"


def test_task_plan_capability_is_absent_and_execution_blocks_when_gates_disabled(trust_harness) -> None:
    config = _all_browser_actions_config()
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(config, fake)
    plan = subsystem.build_playwright_browser_task_plan(
        _plan_observation(),
        task_phrase="enter safe text and stop",
        steps=[_safe_steps("gate disabled safe text")[0]],
    )
    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]

    result = subsystem.request_playwright_browser_task_execution(
        plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert "browser.task.safe_sequence" not in status["declared_action_capabilities"]
    assert status["task_plans_enabled"] is False
    assert result.status == "blocked"
    assert result.failure_reason == "task_plans_disabled"
    assert fake.page.actions == []


def test_task_plan_requires_whole_plan_approval_and_binds_ordered_steps(trust_harness) -> None:
    subsystem = _subsystem_with_fake(_task_plan_config(), _FakeActionPlaywright())
    plan = _build_safe_task_plan(subsystem, text="approval binding text")

    pending = subsystem.request_playwright_browser_task_execution(
        plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    assert pending.status == "approval_required"
    assert pending.completed_step_count == 0

    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )

    reordered = replace(plan, steps=[plan.steps[1], plan.steps[0], plan.steps[2]])
    changed_text_step = replace(
        plan.steps[0],
        action_args_redacted={**plan.steps[0].action_args_redacted, "text_fingerprint": "changed-text-fingerprint"},
    )
    changed_text = replace(plan, steps=[changed_text_step, plan.steps[1], plan.steps[2]])

    reordered_result = subsystem.execute_playwright_browser_task_plan(
        reordered,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    changed_text_result = subsystem.execute_playwright_browser_task_plan(
        changed_text,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert reordered_result.status in {"approval_required", "blocked"}
    assert reordered_result.action_attempted is False
    assert reordered_result.completed_step_count == 0
    assert changed_text_result.status in {"approval_required", "blocked"}
    assert changed_text_result.action_attempted is False
    assert changed_text_result.completed_step_count == 0


def test_task_plan_tampering_blocks_with_precise_reason_codes(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_task_plan_config(), fake)
    plan = _build_safe_task_plan(subsystem, text="precise tamper text")
    _approve_task_plan(subsystem, trust_harness["trust_service"], plan)

    cases: list[tuple[str, BrowserSemanticTaskPlan, str]] = [
        ("reordered", replace(plan, steps=[plan.steps[1], plan.steps[0], plan.steps[2]]), "step_order_changed"),
        ("removed", replace(plan, steps=[plan.steps[0], plan.steps[1]]), "step_count_changed"),
        (
            "inserted",
            replace(plan, steps=[plan.steps[0], plan.steps[1], plan.steps[2], replace(plan.steps[2], step_index=4)]),
            "step_count_changed",
        ),
        ("action", replace(plan, steps=[replace(plan.steps[0], action_kind="click"), plan.steps[1], plan.steps[2]]), "step_action_changed"),
        (
            "target",
            replace(plan, steps=[replace(plan.steps[0], target_fingerprint="tampered-target"), plan.steps[1], plan.steps[2]]),
            "step_target_changed",
        ),
        (
            "text",
            replace(
                plan,
                steps=[
                    replace(
                        plan.steps[0],
                        action_args_redacted={**plan.steps[0].action_args_redacted, "text_fingerprint": "changed-text-fingerprint"},
                    ),
                    plan.steps[1],
                    plan.steps[2],
                ],
            ),
            "step_argument_changed",
        ),
        (
            "option",
            replace(
                plan,
                steps=[
                    plan.steps[0],
                    replace(
                        plan.steps[1],
                        action_args_redacted={**plan.steps[1].action_args_redacted, "option_fingerprint": "changed-option-fingerprint"},
                    ),
                    plan.steps[2],
                ],
            ),
            "step_argument_changed",
        ),
        (
            "outcome",
            replace(
                plan,
                steps=[replace(plan.steps[0], expected_outcome=["unexpected outcome"]), plan.steps[1], plan.steps[2]],
            ),
            "step_expected_outcome_changed",
        ),
        ("final state", replace(plan, expected_final_state=["different final state"]), "plan_fingerprint_mismatch"),
    ]

    for label, tampered, expected_reason in cases:
        result = _execute_task_plan(subsystem, trust_harness["trust_service"], tampered)

        assert result.status == "blocked", label
        assert result.failure_reason == expected_reason, label
        assert result.action_attempted is False, label
        assert result.completed_step_count == 0, label

    assert fake.page.actions == []


def test_expired_task_plan_blocks_with_plan_expired_reason(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_task_plan_config(), fake)
    plan = _build_safe_task_plan(subsystem, text="expired plan text")
    _approve_task_plan(subsystem, trust_harness["trust_service"], plan)
    expired = replace(plan, expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat())

    result = _execute_task_plan(subsystem, trust_harness["trust_service"], expired)

    assert result.status == "blocked"
    assert result.failure_reason == "plan_expired"
    assert result.action_attempted is False
    assert result.completed_step_count == 0
    assert fake.page.actions == []


def test_task_plan_scroll_argument_tamper_blocks_before_execution(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_task_plan_config(), fake)
    plan = _build_scroll_task_plan(subsystem)
    _approve_task_plan(subsystem, trust_harness["trust_service"], plan)
    tampered_step = replace(
        plan.steps[0],
        action_args_redacted={
            **plan.steps[0].action_args_redacted,
            "direction": "up",
            "scroll_fingerprint": "changed-scroll-fingerprint",
        },
    )
    tampered = replace(plan, steps=[tampered_step])

    result = _execute_task_plan(subsystem, trust_harness["trust_service"], tampered)

    assert result.status == "blocked"
    assert result.failure_reason == "step_argument_changed"
    assert result.action_attempted is False
    assert fake.page.actions == []


def test_task_plan_approval_cannot_cross_primitive_action_boundaries(trust_harness) -> None:
    trust_service = trust_harness["trust_service"]
    primitive_fake = _FakeActionPlaywright()
    primitive_subsystem = _subsystem_with_fake(_task_plan_config(), primitive_fake)
    primitive_plan = _approved_click_plan(primitive_subsystem)
    _approve_plan(primitive_subsystem, trust_service, primitive_plan, url="http://127.0.0.1:60231/task-plan.html")
    task_plan_without_task_approval = _build_safe_task_plan(primitive_subsystem, text="primitive cannot approve task")

    task_result = _execute_task_plan(primitive_subsystem, trust_service, task_plan_without_task_approval)

    assert task_result.status in {"approval_required", "blocked"}
    assert task_result.action_attempted is False
    assert primitive_fake.page.actions == []

    task_fake = _FakeActionPlaywright()
    task_subsystem = _subsystem_with_fake(_task_plan_config(), task_fake)
    task_plan = _build_safe_task_plan(task_subsystem, text="task cannot approve primitive")
    _approve_task_plan(task_subsystem, trust_service, task_plan)
    unapproved_primitive = _approved_click_plan(task_subsystem)

    primitive_result = task_subsystem.execute_playwright_browser_action(
        unapproved_primitive,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_service,
        session_id="default",
        fixture_mode=True,
    )

    assert primitive_result.status in {"approval_required", "blocked"}
    assert primitive_result.action_attempted is False
    assert task_fake.page.actions == []


def test_denied_and_expired_task_plan_approvals_fail_closed(trust_harness) -> None:
    trust_service = trust_harness["trust_service"]
    denied_fake = _FakeActionPlaywright()
    denied_subsystem = _subsystem_with_fake(_task_plan_config(), denied_fake)
    denied_plan = _build_safe_task_plan(denied_subsystem, text="denied plan text")
    pending = denied_subsystem.request_playwright_browser_task_execution(
        denied_plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_service,
        session_id="default",
        fixture_mode=True,
    )
    trust_service.respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="deny",
        session_id="default",
        scope=PermissionScope.ONCE,
    )

    denied_result = _execute_task_plan(denied_subsystem, trust_service, denied_plan)

    assert denied_result.status == "blocked"
    assert denied_result.failure_reason == "approval_denied"
    assert denied_result.action_attempted is False
    assert denied_fake.page.actions == []

    expired_fake = _FakeActionPlaywright()
    expired_subsystem = _subsystem_with_fake(_task_plan_config(), expired_fake)
    expired_plan = _build_safe_task_plan(expired_subsystem, text="expired grant text")
    _approve_task_plan(expired_subsystem, trust_service, expired_plan)
    grant = trust_service.repository.list_grants(session_id="default")[0]
    grant.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    trust_service.repository.save_grant(grant)

    expired_result = _execute_task_plan(expired_subsystem, trust_service, expired_plan)

    assert expired_result.status in {"approval_required", "blocked"}
    assert expired_result.action_attempted is False
    assert expired_fake.page.actions == []


def test_task_plan_once_grant_is_consumed_and_cannot_replay(trust_harness) -> None:
    events = EventBuffer(capacity=192)
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_task_plan_config(), fake, events=events)
    plan = _build_safe_task_plan(subsystem, text="once grant safe text")
    _approve_task_plan(subsystem, trust_harness["trust_service"], plan)
    first = subsystem.execute_playwright_browser_task_plan(
        plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    fake.page.actions.clear()

    replay = subsystem.execute_playwright_browser_task_plan(
        plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert first.status == "completed_verified"
    assert replay.status in {"approval_required", "blocked"}
    assert replay.completed_step_count == 0
    assert replay.action_attempted is False
    assert fake.page.actions == []


def test_task_plan_grant_cannot_replay_after_partial_execution(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="type_unverifiable")
    subsystem = _subsystem_with_fake(_task_plan_config(), fake)
    plan = _build_safe_task_plan(subsystem, text="partial replay text")
    _approve_task_plan(subsystem, trust_harness["trust_service"], plan)
    first = _execute_task_plan(subsystem, trust_harness["trust_service"], plan)
    fake.page.actions.clear()

    replay = _execute_task_plan(subsystem, trust_harness["trust_service"], plan)

    assert first.status == "stopped_on_unverified"
    assert replay.status in {"approval_required", "blocked"}
    assert replay.completed_step_count == 0
    assert replay.action_attempted is False
    assert fake.page.actions == []


def test_approved_task_plan_executes_steps_verifies_final_state_and_does_not_submit(trust_harness) -> None:
    events = EventBuffer(capacity=256)
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_task_plan_config(), fake, events=events)
    raw_text = "TASKPLAN-RAW-TEXT-SENTINEL-9"
    plan = _build_safe_task_plan(subsystem, text=raw_text)
    _approve_task_plan(subsystem, trust_harness["trust_service"], plan)

    result = subsystem.execute_playwright_browser_task_plan(
        plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    status = subsystem.status_snapshot()["browser_adapters"]["playwright"]
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "browser task execution",
            "parameters": {"result_state": result.status, "request_stage": "execution"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": result.user_message,
            "metadata": {"route_state": {"winner": {"route_family": "screen_awareness"}}},
        },
        status={"screen_awareness": subsystem.status_snapshot()},
        workspace_focus={},
    )
    serialized = json.dumps(
        {
            "result": result.to_dict(),
            "status": status,
            "events": events.recent(limit=256),
            "deck": surface,
        },
        sort_keys=True,
    )

    assert result.status == "completed_verified"
    assert result.completed_step_count == 3
    assert result.final_verification_status == "supported"
    assert [step.status for step in result.step_results] == ["verified_supported", "verified_supported", "verified_supported"]
    assert result.cleanup_status == "closed"
    assert result.claim_ceiling == "browser_semantic_task_execution"
    assert raw_text not in serialized
    assert "text_redacted_summary" in serialized
    assert "playwright_task_execution_started" in serialized
    assert status["last_task_execution_summary"]["status"] == "completed_verified"
    _assert_no_submit_side_effects(fake, allowed_actions={"type_text", "focus", "select_option", "check"})


def test_serialized_task_plan_without_private_text_payload_cannot_type(trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_task_plan_config(), fake)
    plan = _build_safe_task_plan(subsystem, text="serialized raw text sentinel")
    serialized_plan = plan.to_dict()
    pending = subsystem.request_playwright_browser_task_execution(
        serialized_plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )
    trust_harness["trust_service"].respond_to_request(
        approval_request_id=pending.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
    )

    result = subsystem.execute_playwright_browser_task_plan(
        serialized_plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "stopped_on_blocked"
    assert result.completed_step_count == 1
    assert result.step_results[0].error_code == "serialized_plan_replay_blocked"
    assert result.action_attempted is False
    assert fake.page.actions == []


def test_task_plan_stops_on_unverified_step_and_skips_later_steps(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="type_unverifiable")
    subsystem = _subsystem_with_fake(_task_plan_config(), fake)
    plan = _build_safe_task_plan(subsystem, text="unverified safe text")
    _approve_task_plan(subsystem, trust_harness["trust_service"], plan)

    result = subsystem.execute_playwright_browser_task_plan(
        plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "stopped_on_unverified"
    assert result.completed_step_count == 1
    assert result.blocked_step_id == plan.steps[0].step_id
    assert [step.status for step in result.step_results] == ["completed_unverified"]
    assert [step.status for step in plan.steps] == ["completed_unverified", "skipped", "skipped"]
    assert all(action[0] not in {"select_option", "check"} for action in fake.page.actions)
    _assert_no_submit_side_effects(fake, allowed_actions={"type_text", "focus"})


@pytest.mark.parametrize(
    ("scenario", "expected_reason", "allowed_actions"),
    [
        ("option_removed", "option_not_found", {"type_text", "focus"}),
        ("option_duplicate_after_preview", "option_ambiguous", {"type_text", "focus"}),
        ("checkbox_payment_authorization", "target_sensitive", {"type_text", "focus", "select_option"}),
    ],
)
def test_task_plan_step_drift_stops_later_steps(
    trust_harness,
    scenario: str,
    expected_reason: str,
    allowed_actions: set[str],
) -> None:
    fake = _FakeActionPlaywright(scenario=scenario)
    subsystem = _subsystem_with_fake(_task_plan_config(), fake)
    plan = _build_safe_task_plan(subsystem, text="step drift text")
    _approve_task_plan(subsystem, trust_harness["trust_service"], plan)

    result = _execute_task_plan(subsystem, trust_harness["trust_service"], plan)

    assert result.status == "stopped_on_blocked"
    assert result.failure_reason == expected_reason
    assert result.blocked_step_id
    assert result.cleanup_status == "closed"
    assert all(action[0] in allowed_actions for action in fake.page.actions)
    if scenario != "checkbox_payment_authorization":
        assert plan.steps[2].status == "skipped"
    _assert_no_submit_side_effects(fake, allowed_actions=allowed_actions)


def test_task_plan_stops_on_submit_counter_change_before_later_steps(trust_harness) -> None:
    fake = _FakeActionPlaywright(scenario="choice_submit_on_change")
    subsystem = _subsystem_with_fake(_task_plan_config(), fake)
    plan = _build_safe_task_plan(subsystem, text="safe task text")
    _approve_task_plan(subsystem, trust_harness["trust_service"], plan)

    result = subsystem.execute_playwright_browser_task_plan(
        plan,
        url="http://127.0.0.1:60231/task-plan.html",
        trust_service=trust_harness["trust_service"],
        session_id="default",
        fixture_mode=True,
    )

    assert result.status == "stopped_on_unexpected_side_effect"
    assert result.completed_step_count == 2
    assert result.failure_reason == "unexpected_form_submission"
    assert result.step_results[-1].status == "failed"
    assert all(action[0] != "check" for action in fake.page.actions)
    assert fake.page.submit_count == 1


def test_task_plan_redaction_invariant_covers_status_events_deck_audit_and_results(trust_harness) -> None:
    events = EventBuffer(capacity=256)
    fake = _FakeActionPlaywright(scenario="redaction_sentinel_fields")
    subsystem = _subsystem_with_fake(_task_plan_config(), fake, events=events)
    raw_text = "TASKPLAN-RAW-SECRET-SENTINEL-9-1"
    plan = _build_safe_task_plan(subsystem, text=raw_text)
    _approve_task_plan(subsystem, trust_harness["trust_service"], plan)

    result = _execute_task_plan(subsystem, trust_harness["trust_service"], plan)
    surface = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "browser task execution",
            "parameters": {"result_state": result.status, "request_stage": "execution"},
        },
        active_task=None,
        recent_context_resolutions=[],
        latest_message={
            "content": result.user_message,
            "metadata": {"route_state": {"winner": {"route_family": "screen_awareness"}}},
        },
        status={"screen_awareness": subsystem.status_snapshot()},
        workspace_focus={},
    )
    recent_audit = [record.to_dict() for record in trust_harness["trust_service"].repository.list_recent_audit(session_id="default", limit=32)]
    serialized = json.dumps(
        {
            "plan": plan.to_dict(),
            "result": result.to_dict(),
            "status": subsystem.status_snapshot(),
            "events": events.recent(limit=256),
            "deck": surface,
            "audit": recent_audit,
        },
        sort_keys=True,
        default=str,
    )

    assert result.status in {"completed_verified", "stopped_on_blocked"}
    assert "text_redacted_summary" in serialized
    for forbidden in {
        raw_text,
        "PASSWORD-KRAKEN-RAW-SECRET-8-1",
        "HIDDEN-KRAKEN-RAW-SECRET-8-1",
        "OPTION-KRAKEN-HIDDEN-SECRET-8-1",
        "COOKIE-KRAKEN-RAW-SECRET-8-1",
    }:
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "blocked_step",
    [
        {"action_kind": "submit_form", "target_phrase": "Form", "action_phrase": "submit this form"},
        {"action_kind": "login", "target_phrase": "Login", "action_phrase": "log me in"},
        {"action_kind": "payment", "target_phrase": "Checkout", "action_phrase": "buy this"},
        {"action_kind": "captcha", "target_phrase": "CAPTCHA", "action_phrase": "solve the captcha"},
    ],
)
def test_task_plan_route_boundary_steps_are_not_executable_safe_plans(blocked_step: dict[str, Any], trust_harness) -> None:
    fake = _FakeActionPlaywright()
    subsystem = _subsystem_with_fake(_task_plan_config(), fake)
    plan = subsystem.build_playwright_browser_task_plan(
        _plan_observation(),
        task_phrase=blocked_step["action_phrase"],
        steps=[blocked_step],
    )

    result = _execute_task_plan(subsystem, trust_harness["trust_service"], plan)

    assert plan.executable_now is False
    assert plan.steps[0].status == "blocked"
    assert result.status in {"blocked", "unsupported"}
    assert result.failure_reason == "unsupported_step"
    assert result.action_attempted is False
    assert fake.page.actions == []
