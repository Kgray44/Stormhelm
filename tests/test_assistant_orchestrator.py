from __future__ import annotations

import asyncio

from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.orchestrator.assistant import AssistantOrchestrator
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.providers.base import AssistantProvider, ProviderToolCall, ProviderTurnResult
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry


class FakeProvider(AssistantProvider):
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        instructions: str,
        input_items: str | list[dict[str, object]],
        previous_response_id: str | None,
        tools: list[dict[str, object]],
        model: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ProviderTurnResult:
        self.calls.append(
            {
                "instructions": instructions,
                "input_items": input_items,
                "previous_response_id": previous_response_id,
                "tool_names": [tool["name"] for tool in tools],
                "model": model,
                "max_output_tokens": max_output_tokens,
            }
        )
        if model and model.endswith("mini") and previous_response_id is None:
            return ProviderTurnResult(
                response_id="resp_1",
                output_text="",
                tool_calls=[
                    ProviderToolCall(call_id="call_clock", name="clock", arguments={}),
                    ProviderToolCall(call_id="call_system", name="system_info", arguments={}),
                ],
            )
        if model and model.endswith("mini"):
            return ProviderTurnResult(
                response_id="resp_planner_final",
                output_text="Planner bearings gathered.",
                tool_calls=[],
            )
        return ProviderTurnResult(
            response_id="resp_2",
            output_text="Current system bearings assembled.",
            tool_calls=[],
        )


class FakeConversationRecord:
    def __init__(self, *, role: str, content: str, metadata: dict[str, object] | None = None) -> None:
        self.role = role
        self.content = content
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
        }


class FakeConversationRepository:
    def __init__(self) -> None:
        self.messages: list[FakeConversationRecord] = []

    def ensure_session(self, session_id: str = "default", title: str = "Primary Session") -> None:
        del session_id, title

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> FakeConversationRecord:
        del session_id
        record = FakeConversationRecord(role=role, content=content, metadata=metadata)
        self.messages.append(record)
        return record


class FakeNotesRepository:
    def create_note(self, title: str, content: str) -> dict[str, str]:
        return {"title": title, "content": content}


class FakePreferencesRepository:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def set_preference(self, key: str, value: object) -> None:
        self.values[key] = value

    def get_all(self) -> dict[str, object]:
        return dict(self.values)


class FakeToolRunRepository:
    def upsert_run(self, **_: object) -> None:
        return None


def _build_assistant(temp_config) -> tuple[AssistantOrchestrator, JobManager, ToolExecutor, ConversationStateStore]:
    events = EventBuffer()
    notes = FakeNotesRepository()
    preferences = FakePreferencesRepository()
    session_state = ConversationStateStore(preferences)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry, max_sync_workers=temp_config.concurrency.max_workers)
    jobs = JobManager(
        config=temp_config,
        executor=executor,
        context_factory=lambda job_id: ToolContext(
            job_id=job_id,
            config=temp_config,
            events=events,
            notes=notes,
            preferences=preferences,
            safety_policy=SafetyPolicy(temp_config),
        ),
        tool_runs=FakeToolRunRepository(),
        events=events,
    )
    assistant = AssistantOrchestrator(
        config=temp_config,
        conversations=FakeConversationRepository(),
        jobs=jobs,
        router=IntentRouter(),
        events=events,
        tool_registry=registry,
        session_state=session_state,
        planner=DeterministicPlanner(),
        persona=PersonaContract(temp_config),
        workspace_service=None,
        provider=None,
    )
    return assistant, jobs, executor, session_state


def test_assistant_orchestrator_routes_deck_open_url_without_provider(temp_config) -> None:
    assistant, jobs, executor, _ = _build_assistant(temp_config)
    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "/open deck https://platform.openai.com/docs",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["actions"][0]["type"] == "workspace_open"
    assert payload["actions"][0]["module"] == "browser"
    assert payload["jobs"][0]["tool_name"] == "deck_open_url"
    assert "Deck browser" in payload["assistant_message"]["content"]


def test_assistant_orchestrator_uses_provider_and_keeps_previous_response_state(temp_config) -> None:
    provider = FakeProvider()
    temp_config.openai.enabled = True
    temp_config.openai.planner_model = "gpt-5.4-mini"
    temp_config.openai.reasoning_model = "gpt-5.4"
    assistant, jobs, executor, session_state = _build_assistant(temp_config)
    assistant.provider = provider
    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "Give me current system bearings.",
                surface_mode="deck",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert payload["assistant_message"]["content"] == "Current system bearings assembled."
    assert len(payload["jobs"]) == 2
    assert {job["tool_name"] for job in payload["jobs"]} == {"clock", "system_info"}
    assert provider.calls[0]["previous_response_id"] is None
    assert provider.calls[0]["model"] == "gpt-5.4-mini"
    assert provider.calls[1]["model"] == "gpt-5.4-mini"
    assert provider.calls[2]["model"] == "gpt-5.4"
    assert session_state.get_previous_response_id("default", role="planner") == "resp_planner_final"
    assert session_state.get_previous_response_id("default", role="reasoner") == "resp_2"


def test_assistant_orchestrator_prefers_deterministic_system_tools_before_provider(temp_config) -> None:
    provider = FakeProvider()
    temp_config.openai.enabled = True
    assistant, jobs, executor, _ = _build_assistant(temp_config)
    assistant.provider = provider

    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                "How much storage do I have left on this machine?",
                surface_mode="ghost",
                active_module="systems",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    payload = asyncio.run(runner())

    assert provider.calls == []
    assert payload["jobs"][0]["tool_name"] == "storage_status"
    assert "storage" in payload["assistant_message"]["content"].lower()
