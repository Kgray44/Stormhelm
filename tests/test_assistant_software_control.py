from __future__ import annotations

import asyncio

from stormhelm.core.container import build_container


def test_assistant_routes_install_request_through_native_software_control_and_persists_resume_state(temp_config) -> None:
    container = build_container(temp_config)

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await container.jobs.start()
        try:
            payload = await container.assistant.handle_message(
                "install firefox",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
            )
            request_state = container.assistant.session_state.get_active_request_state("default")
            return payload, request_state
        finally:
            await container.jobs.stop()

    payload, request_state = asyncio.run(runner())
    metadata = payload["assistant_message"]["metadata"]
    planner_debug = metadata["planner_debug"]

    assert payload["jobs"] == []
    assert planner_debug["software_control"]["candidate"] is True
    assert planner_debug["software_control"]["result"]["status"] == "prepared"
    assert metadata["bearing_title"] == "Software Plan"
    assert metadata["micro_response"] == "Prepared a local install plan for Firefox."
    assert request_state["family"] == "software_control"
    assert request_state["parameters"]["request_stage"] == "awaiting_confirmation"


def test_assistant_routes_download_and_install_minecraft_through_native_software_control_lane(temp_config) -> None:
    container = build_container(temp_config)

    async def runner() -> tuple[dict[str, object], dict[str, object]]:
        await container.jobs.start()
        try:
            payload = await container.assistant.handle_message(
                "download and install Minecraft",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
            )
            request_state = container.assistant.session_state.get_active_request_state("default")
            return payload, request_state
        finally:
            await container.jobs.stop()

    payload, request_state = asyncio.run(runner())
    metadata = payload["assistant_message"]["metadata"]
    planner_debug = metadata["planner_debug"]

    assert payload["jobs"] == []
    assert planner_debug["software_control"]["candidate"] is True
    assert planner_debug["software_control"]["target_name"] == "minecraft"
    assert planner_debug["software_control"]["result"]["status"] == "prepared"
    assert metadata["bearing_title"] == "Software Plan"
    assert metadata["micro_response"] == "Prepared a local install plan for Minecraft."
    assert request_state["family"] == "software_control"
    assert request_state["parameters"]["selected_source_route"] == "winget"
