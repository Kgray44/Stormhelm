from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any

import uvicorn

from stormhelm.config.loader import load_config
from stormhelm.core.api.app import create_app
from stormhelm.core.orchestrator.command_eval.runner import DryRunToolExecutor


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a process-isolated Stormhelm Core for command evaluation.")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    runtime_dir = args.runtime_dir.resolve()
    project_root = args.project_root.resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "logs").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "state").mkdir(parents=True, exist_ok=True)
    config = load_config(
        project_root=project_root,
        env={
            "STORMHELM_DATA_DIR": str(runtime_dir),
            "STORMHELM_OPENAI_ENABLED": "false",
            "STORMHELM_HARDWARE_TELEMETRY_ENABLED": "false",
            "STORMHELM_SCREEN_AWARENESS_ACTION_POLICY_MODE": "observe_only",
            "STORMHELM_MAX_CONCURRENT_JOBS": "4",
            "STORMHELM_DEFAULT_JOB_TIMEOUT_SECONDS": "2",
        },
    )
    app = create_app(config)
    container = app.state.container
    dry_run_executor = DryRunToolExecutor(container.tool_registry)
    container.tool_executor = dry_run_executor
    container.jobs.executor = dry_run_executor
    container.network_monitor = None

    @app.post("/__command_eval/session-state")
    async def set_command_eval_session_state(payload: dict[str, Any]) -> dict[str, object]:
        session_id = str(payload.get("session_id") or "default")
        active_request_state = payload.get("active_request_state")
        if isinstance(active_request_state, dict):
            container.assistant.session_state.set_active_request_state(session_id, active_request_state)
        return {
            "ok": True,
            "session_id": session_id,
            "active_request_state_set": isinstance(active_request_state, dict),
        }

    block_seconds = max(0.0, float(os.environ.get("STORMHELM_COMMAND_EVAL_BLOCK_SECONDS") or 0.0))
    if block_seconds:
        _install_blocking_handler(container, block_seconds=block_seconds)

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def _install_blocking_handler(container: Any, *, block_seconds: float) -> None:
    original = container.assistant.handle_message

    async def blocking_handle_message(*args: Any, **kwargs: Any) -> dict[str, object]:
        time.sleep(block_seconds)
        return await original(*args, **kwargs)

    container.assistant.handle_message = blocking_handle_message


if __name__ == "__main__":
    main()
