from __future__ import annotations

import json
from typing import Any

import httpx

from stormhelm.config.models import OpenAIConfig
from stormhelm.core.providers.audit import record_provider_call
from stormhelm.core.providers.base import AssistantProvider, ProviderToolCall, ProviderTurnResult


class OpenAIResponsesProvider(AssistantProvider):
    def __init__(self, config: OpenAIConfig) -> None:
        self.config = config

    async def generate(
        self,
        *,
        instructions: str,
        input_items: str | list[dict[str, Any]],
        previous_response_id: str | None,
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ProviderTurnResult:
        selected_model = model or self.config.model
        record_provider_call(
            provider_name="openai",
            provider_type="openai_responses",
            source="stormhelm.core.providers.openai_responses.OpenAIResponsesProvider.generate",
            purpose=self._purpose_for_model(selected_model),
            model_name=selected_model,
            openai_called=True,
            llm_called=True,
            embedding_called=False,
            metadata={"tool_count": len(tools)},
        )
        if not self.config.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        payload: dict[str, Any] = {
            "model": selected_model,
            "instructions": instructions,
            "input": input_items,
            "tools": tools,
            "max_output_tokens": max_output_tokens or self.config.max_output_tokens,
        }
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(
                f"{self.config.base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        return ProviderTurnResult(
            response_id=data.get("id"),
            output_text=self._extract_output_text(data),
            tool_calls=self._extract_tool_calls(data),
            raw_response=data,
        )

    def _extract_output_text(self, payload: dict[str, Any]) -> str:
        top_level = payload.get("output_text")
        if isinstance(top_level, str) and top_level.strip():
            return top_level.strip()

        parts: list[str] = []
        for item in payload.get("output", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if not isinstance(content, dict):
                        continue
                    text = content.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
        return "\n".join(parts).strip()

    def _extract_tool_calls(self, payload: dict[str, Any]) -> list[ProviderToolCall]:
        calls: list[ProviderToolCall] = []
        for item in payload.get("output", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") != "function_call":
                continue
            raw_arguments = item.get("arguments", "{}")
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments or {})
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    f"OpenAI returned invalid JSON arguments for tool '{item.get('name', 'unknown')}'."
                ) from error
            calls.append(
                ProviderToolCall(
                    call_id=str(item.get("call_id", item.get("id", ""))),
                    name=str(item.get("name", "")),
                    arguments=arguments,
                )
            )
        return calls

    def _purpose_for_model(self, model_name: str) -> str:
        if model_name == self.config.reasoning_model:
            return "reasoner_summary"
        if model_name == self.config.planner_model:
            return "planner_or_tool_fallback"
        return "assistant_generation"
