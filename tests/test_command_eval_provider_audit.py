from __future__ import annotations

import asyncio
import json

import pytest

from stormhelm.config.models import OpenAIConfig
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.providers.openai_responses import OpenAIResponsesProvider


def _openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        enabled=True,
        api_key="sk-test",
        base_url="https://api.openai.test/v1",
        model="gpt-test",
        planner_model="gpt-planner",
        reasoning_model="gpt-reasoner",
        timeout_seconds=1.0,
        max_tool_rounds=1,
        max_output_tokens=32,
        planner_max_output_tokens=32,
        reasoning_max_output_tokens=32,
        instructions="",
    )


def test_openai_boundary_records_and_blocks_command_eval_provider_attempt(tmp_path, monkeypatch) -> None:
    audit_path = tmp_path / "provider-audit.jsonl"
    monkeypatch.setenv("STORMHELM_COMMAND_EVAL_PROVIDER_AUDIT_PATH", str(audit_path))
    monkeypatch.setenv("STORMHELM_COMMAND_EVAL_BLOCK_PROVIDER_CALLS", "true")
    monkeypatch.setenv("STORMHELM_COMMAND_EVAL_PROVIDER_ALLOWED", "false")

    provider = OpenAIResponsesProvider(_openai_config())

    with pytest.raises(RuntimeError, match="provider call blocked"):
        asyncio.run(
            provider.generate(
                instructions="Answer briefly.",
                input_items="hello",
                previous_response_id=None,
                tools=[],
                model="gpt-planner",
                max_output_tokens=16,
            )
        )

    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["provider_name"] == "openai"
    assert row["model_name"] == "gpt-planner"
    assert row["openai_called"] is True
    assert row["llm_called"] is True
    assert row["embedding_called"] is False
    assert row["blocked"] is True
    assert row["provider_call_violation"] is True


def test_command_eval_result_exposes_ai_provider_violation_fields() -> None:
    case = CommandEvalCase(
        case_id="provider_violation_case",
        message="write a poem",
        expected=ExpectedBehavior(route_family="generic_provider", subsystem="provider"),
        tags=("generic",),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=1.0,
        ui_response="Provider call was blocked.",
        session_id="provider-audit-test",
        actual_route_family="generic_provider",
        actual_subsystem="provider",
        ai_provider_calls=(
            {
                "provider_name": "openai",
                "model_name": "gpt-planner",
                "purpose": "planner_fallback",
                "source": "stormhelm.core.providers.openai_responses.OpenAIResponsesProvider.generate",
                "openai_called": True,
                "llm_called": True,
                "embedding_called": False,
                "blocked": True,
                "provider_call_violation": True,
            },
        ),
    )

    payload = CommandEvalResult(
        case=case,
        observation=observation,
        assertions={},
        run_id="provider-audit",
    ).to_dict()

    assert payload["provider_called"] is True
    assert payload["openai_called"] is True
    assert payload["llm_called"] is True
    assert payload["embedding_called"] is False
    assert payload["provider_call_count"] == 1
    assert payload["openai_call_count"] == 1
    assert payload["provider_names"] == ["openai"]
    assert payload["model_names"] == ["gpt-planner"]
    assert payload["provider_call_purposes"] == ["planner_fallback"]
    assert payload["provider_call_allowed"] is False
    assert payload["provider_call_violation"] is True
    assert "blocked" in payload["ai_usage_summary"]


def test_provider_fallback_diagnostic_tag_allows_provider_audit_calls() -> None:
    case = CommandEvalCase(
        case_id="provider_allowed_case",
        message="provider diagnostic",
        expected=ExpectedBehavior(route_family="generic_provider", subsystem="provider"),
        tags=("provider_fallback_diagnostic",),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=1.0,
        ui_response="Provider diagnostic ran.",
        session_id="provider-audit-test",
        actual_route_family="generic_provider",
        actual_subsystem="provider",
        ai_provider_calls=(
            {
                "provider_name": "openai",
                "model_name": "gpt-planner",
                "purpose": "planner_fallback",
                "source": "stormhelm.core.providers.openai_responses.OpenAIResponsesProvider.generate",
                "openai_called": True,
                "llm_called": True,
                "embedding_called": False,
                "blocked": False,
                "provider_call_violation": False,
            },
        ),
    )

    payload = CommandEvalResult(case=case, observation=observation, assertions={}).to_dict()

    assert payload["provider_call_allowed"] is True
    assert payload["provider_call_violation"] is False
