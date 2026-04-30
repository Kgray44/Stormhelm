from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stormhelm.config.loader import load_config
from stormhelm.ui.app import resolve_main_qml_path
from stormhelm.ui.bridge import UiBridge


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    value = ordered[lower] * (1.0 - weight) + ordered[upper] * weight
    return round(value, 3)


def _stats(values: list[float]) -> dict[str, float | None]:
    return {
        "p50_ms": round(statistics.median(values), 3) if values else None,
        "p95_ms": _percentile(values, 0.95),
        "max_ms": round(max(values), 3) if values else None,
    }


def _route_event(cursor: int, request_id: str, stage: str) -> dict[str, Any]:
    return {
        "cursor": cursor,
        "event_id": cursor,
        "event_family": "route",
        "event_type": "route.selected",
        "severity": "info",
        "subsystem": "planner",
        "visibility_scope": "ghost_hint",
        "message": "Route selected.",
        "payload": {
            "request_id": request_id,
            "route_family": "software_control",
            "subject": "Calculator",
            "stage": stage,
            "summary": "Software route selected.",
        },
    }


def _approval_event(cursor: int, request_id: str) -> dict[str, Any]:
    return {
        "cursor": cursor,
        "event_id": cursor,
        "event_family": "approval",
        "event_type": "approval_required",
        "severity": "warning",
        "subsystem": "trust",
        "visibility_scope": "operator_blocking",
        "message": "Approval required.",
        "payload": {
            "request_id": request_id,
            "approval_id": f"approval-{request_id}",
            "route_family": "trust_approvals",
            "subject": "approval smoke",
            "operator_message": "Approval required.",
        },
    }


def _clarification_event(cursor: int, request_id: str) -> dict[str, Any]:
    return {
        "cursor": cursor,
        "event_id": cursor,
        "event_family": "route",
        "event_type": "clarification_required",
        "severity": "info",
        "subsystem": "planner",
        "visibility_scope": "ghost_hint",
        "message": "Clarification required.",
        "payload": {
            "request_id": request_id,
            "route_family": "software_control",
            "subject": "ambiguous target",
            "stage": "clarification_required",
            "summary": "Clarification required.",
            "clarification_choices": ["Calculator", "Settings"],
        },
    }


def _voice_event(cursor: int, request_id: str) -> dict[str, Any]:
    return {
        "cursor": cursor,
        "event_id": cursor,
        "event_family": "voice",
        "event_type": "voice.synthesis_started",
        "severity": "info",
        "subsystem": "voice",
        "visibility_scope": "deck_context",
        "message": "TTS started.",
        "payload": {
            "turn_id": request_id,
            "speech_request_id": f"speech-{request_id}",
            "status": "started",
        },
    }


def _measured(values: list[dict[str, Any]], key: str) -> list[float]:
    measured: list[float] = []
    for item in values:
        value = item.get(key)
        if isinstance(value, (int, float)):
            measured.append(float(value))
    return measured


def _wait_for_surface_confirmation(
    app: Any,
    bridge: UiBridge,
    surface: str,
    revision: int,
    *,
    timeout_ms: int = 1500,
) -> None:
    if app is None or revision <= 0:
        return
    from PySide6 import QtTest

    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        QtTest.QTest.qWait(15)
        for confirmation in reversed(bridge.uiRenderConfirmations):
            if confirmation.get("surface") != surface:
                continue
            if int(confirmation.get("model_revision") or 0) >= revision:
                return


def _load_qml_bridge() -> tuple[Any, UiBridge, Any, Any]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore, QtQml, QtWidgets
    from PySide6.QtQuickControls2 import QQuickStyle

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    QQuickStyle.setStyle("Basic")
    config = load_config(project_root=ROOT, env={})
    bridge = UiBridge(config)
    engine = QtQml.QQmlApplicationEngine()
    engine.rootContext().setContextProperty("stormhelmBridge", bridge)
    engine.rootContext().setContextProperty("stormhelmGhostInput", None)
    engine.load(QtCore.QUrl.fromLocalFile(str(resolve_main_qml_path(config))))
    if not engine.rootObjects():
        raise RuntimeError("QML shell did not load")
    app.processEvents()
    return app, bridge, engine, engine.rootObjects()[0]


def _exercise_bridge(
    bridge: UiBridge,
    samples: int,
    *,
    app: Any = None,
) -> None:
    for index in range(samples):
        cursor = 10_000 + index * 10
        request_id = f"l71-smoke-{index}"
        if app is not None:
            bridge.setMode("ghost")
            from PySide6 import QtTest

            QtTest.QTest.qWait(360)
            app.processEvents()
        bridge.apply_stream_event(_route_event(cursor, request_id, "route_selected"))
        _wait_for_surface_confirmation(
            app,
            bridge,
            "ghost_primary",
            bridge.renderSurfaceRevision("ghost_primary"),
        )
        _wait_for_surface_confirmation(
            app,
            bridge,
            "composer_chips",
            bridge.renderSurfaceRevision("composer_chips"),
        )

        bridge.apply_stream_event(_approval_event(cursor + 1, request_id))
        _wait_for_surface_confirmation(
            app,
            bridge,
            "approval_prompt",
            bridge.renderSurfaceRevision("approval_prompt"),
        )

        bridge.apply_stream_event(_clarification_event(cursor + 2, request_id))
        _wait_for_surface_confirmation(
            app,
            bridge,
            "clarification_prompt",
            bridge.renderSurfaceRevision("clarification_prompt"),
        )

        bridge.apply_stream_event(_voice_event(cursor + 3, request_id))
        _wait_for_surface_confirmation(
            app,
            bridge,
            "voice_core",
            bridge.renderSurfaceRevision("voice_core"),
        )

        if app is not None:
            bridge.setMode("deck")
            from PySide6 import QtTest

            QtTest.QTest.qWait(420)
            app.processEvents()
        bridge.apply_stream_state(
            {"source": "client", "phase": "reconnecting", "cursor": cursor + 4}
        )
        _wait_for_surface_confirmation(
            app,
            bridge,
            "deck_event_spine",
            bridge.renderSurfaceRevision("deck_event_spine"),
        )


def _surface_report(surface: str, summaries: list[dict[str, Any]]) -> dict[str, Any]:
    surface_summaries = [
        summary for summary in summaries if summary.get("surface") == surface
    ]
    received_to_bridge = _measured(surface_summaries, "received_to_bridge_update_ms")
    bridge_to_model = _measured(surface_summaries, "bridge_update_to_model_notify_ms")
    model_to_render = _measured(
        surface_summaries,
        "model_notify_to_render_confirmed_ms",
    )
    received_to_render = _measured(
        surface_summaries,
        "received_to_render_confirmed_ms",
    )
    statuses = {
        str(summary.get("render_confirmation_status") or "unknown")
        for summary in surface_summaries
    }
    render_status = (
        "confirmed"
        if "confirmed" in statuses
        else "hidden"
        if "hidden" in statuses or "not_visible" in statuses
        else "not_measured"
    )
    bridge_stats = _stats(received_to_bridge)
    model_stats = _stats(bridge_to_model)
    render_stats = _stats(model_to_render)
    total_render_stats = _stats(received_to_render)
    return {
        "received_to_bridge_p50_ms": bridge_stats["p50_ms"],
        "received_to_bridge_p95_ms": bridge_stats["p95_ms"],
        "received_to_bridge_max_ms": bridge_stats["max_ms"],
        "bridge_to_model_p50_ms": model_stats["p50_ms"],
        "bridge_to_model_p95_ms": model_stats["p95_ms"],
        "bridge_to_model_max_ms": model_stats["max_ms"],
        "model_to_render_p50_ms": render_stats["p50_ms"],
        "model_to_render_p95_ms": render_stats["p95_ms"],
        "model_to_render_max_ms": render_stats["max_ms"],
        "received_to_render_p50_ms": total_render_stats["p50_ms"],
        "received_to_render_p95_ms": total_render_stats["p95_ms"],
        "received_to_render_max_ms": total_render_stats["max_ms"],
        "samples": len(surface_summaries),
        "render_status": render_status,
    }


def run_smoke(samples: int, mode: str) -> dict[str, Any]:
    last_stream_state: dict[str, Any] = {}
    if mode == "live_qml":
        summaries: list[dict[str, Any]] = []
        for _ in range(samples):
            app = None
            engine = None
            root = None
            try:
                app, bridge, engine, root = _load_qml_bridge()
                _exercise_bridge(bridge, 1, app=app)
                summaries.extend(bridge.uiEventRenderLatencySummaries)
                last_stream_state = bridge.eventStreamConnectionState
            finally:
                if root is not None:
                    root.close()
                if engine is not None:
                    engine.deleteLater()
                if app is not None:
                    app.processEvents()
    else:
        app = None
        config = load_config(project_root=ROOT, env={})
        bridge = UiBridge(config)
        _exercise_bridge(bridge, samples, app=app)
        summaries = bridge.uiEventRenderLatencySummaries
        last_stream_state = bridge.eventStreamConnectionState

    surfaces = {
        surface: _surface_report(surface, summaries)
        for surface in (
            "ghost_primary",
            "ghost_action_strip",
            "composer_chips",
            "approval_prompt",
            "clarification_prompt",
            "voice_core",
            "deck_event_spine",
            "route_inspector",
        )
    }
    unknown_count = sum(
        1
        for summary in summaries
        if str(summary.get("render_confirmation_status") or "unknown")
        in {"unknown", "not_measured", "model_only"}
    )
    notes = []
    if mode == "headless":
        notes.append(
            "Headless smoke measures bridge/model timing only; render visibility is not measured without QML confirmations."
        )
    elif mode == "live_qml":
        notes.append(
            "Live QML smoke uses QML component hooks; it confirms QML-visible state changes, not GPU paint completion."
        )
    else:
        notes.append(
            "Mode label requested a live/manual run, but this command did not launch the QML shell."
        )
    return {
        "phase": "L7.1",
        "mode": mode,
        "samples": samples,
        "environment": {
            "project_root": str(ROOT),
            "python": sys.version.split()[0],
        },
        "surfaces": surfaces,
        "unknown_or_not_measured_count": unknown_count,
        "polling_fallback_used_count": sum(
            1 for summary in summaries if summary.get("used_polling_fallback")
        ),
        "duplicate_ignored_count": int(
            last_stream_state.get("duplicate_ignored_count") or 0
        ),
        "out_of_order_ignored_count": int(
            last_stream_state.get("out_of_order_ignored_count") or 0
        ),
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the L7.1 headless UI render-latency smoke harness."
    )
    parser.add_argument("--samples", type=int, default=25)
    parser.add_argument(
        "--mode",
        choices=("headless", "live_qml", "manual_dev"),
        default="headless",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    samples = max(1, int(args.samples))
    report = run_smoke(samples, args.mode)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
