from __future__ import annotations

import asyncio
from uuid import uuid4

from stormhelm.core.container import build_container
from stormhelm.core.tasks.models import TaskCheckpointRecord
from stormhelm.core.tasks.models import TaskRecord
from stormhelm.core.tasks.models import TaskState
from stormhelm.core.tasks.models import TaskStepRecord
from stormhelm.core.tasks.models import TaskStepState
from stormhelm.shared.time import utc_now_iso


def _save_task(container, *, task_id: str, state: TaskState) -> None:
    timestamp = utc_now_iso()
    checkpoint_status = "pending" if state == TaskState.VERIFICATION else "completed"
    container.task_service.repository.save_task(
        TaskRecord(
            task_id=task_id,
            session_id="default",
            title=f"Task {task_id}",
            summary="Synthetic assistant software trust task.",
            goal="Verify assistant trust task binding behavior.",
            state=state.value,
            created_at=timestamp,
            updated_at=timestamp,
            started_at=timestamp,
            finished_at=timestamp if state == TaskState.COMPLETED else "",
            active_step_id="" if state == TaskState.COMPLETED else f"{task_id}-step",
            steps=[
                TaskStepRecord(
                    step_id=f"{task_id}-step",
                    task_id=task_id,
                    sequence_index=0,
                    title="Synthetic step",
                    state=TaskStepState.COMPLETED.value
                    if state == TaskState.COMPLETED
                    else TaskStepState.IN_PROGRESS.value,
                    started_at=timestamp,
                    finished_at=timestamp if state == TaskState.COMPLETED else "",
                )
            ],
            checkpoints=[
                TaskCheckpointRecord(
                    checkpoint_id=str(uuid4()),
                    task_id=task_id,
                    label="Verify outcome",
                    status=checkpoint_status,
                    summary="",
                    created_at=timestamp,
                    completed_at=timestamp if checkpoint_status == "completed" else "",
                )
            ],
        )
    )
    container.assistant.session_state.set_active_task_id("default", task_id)


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


def test_assistant_does_not_leak_completed_task_scope_into_new_software_request(temp_config) -> None:
    container = build_container(temp_config)
    _save_task(container, task_id="task-complete", state=TaskState.COMPLETED)

    async def runner() -> dict[str, object]:
        await container.jobs.start()
        try:
            await container.assistant.handle_message(
                "install firefox",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
            )
            return container.assistant.session_state.get_active_request_state("default")
        finally:
            await container.jobs.stop()

    request_state = asyncio.run(runner())

    assert request_state["family"] == "software_control"
    assert request_state["task_id"] == ""
    assert request_state["trust"]["suggested_scope"] == "once"
