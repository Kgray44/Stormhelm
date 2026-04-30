from __future__ import annotations

from typing import Any

from stormhelm.ui.command_surface_v2 import _stations
from stormhelm.ui.command_surface_v2 import build_command_surface_model


_DEFAULT_DEICTIC = object()


def _screen_station_runtime(screen: Any) -> dict[str, Any]:
    return {
        "present": True,
        "headline": "Live",
        "tone": "steady",
        "watch": {"present": False},
        "lifecycle": {"present": False},
        "screenAwareness": screen,
    }


def _continuity() -> dict[str, Any]:
    return {"present": False, "tone": "steady", "summary": "", "posture": "", "freshness": ""}


def _memory() -> dict[str, Any]:
    return {"present": False, "count": "Support memory", "contributors": []}


def _screen_station(*, screen: Any, deictic: Any = _DEFAULT_DEICTIC) -> list[dict[str, Any]]:
    return _stations(
        "screen_awareness",
        "Visual Context - Prepared",
        "Holding screen-awareness state.",
        "Prepared",
        "prepared",
        "current screen",
        {},
        {},
        {} if deictic is _DEFAULT_DEICTIC else deictic,
        _continuity(),
        _memory(),
        _screen_station_runtime(screen),
        [],
        [],
    )


def test_command_surface_v2_screen_none_does_not_crash() -> None:
    stations = _screen_station(screen=None)

    assert stations[0]["stationFamily"] == "screen_awareness"
    assert "Screen Route" in {section["title"] for section in stations[0]["sections"]}


def test_command_surface_v2_screen_policy_none_does_not_crash() -> None:
    stations = _screen_station(screen={"phase": "phase12", "policy": None, "trace": {"durationMs": 4.2}})

    assert stations[0]["stationFamily"] == "screen_awareness"


def test_command_surface_v2_screen_trace_none_does_not_crash() -> None:
    stations = _screen_station(screen={"phase": "phase12", "policy": {"action_policy_mode": "observe_only"}, "trace": None})

    assert stations[0]["stationFamily"] == "screen_awareness"


def test_command_surface_v2_deictic_none_does_not_crash() -> None:
    stations = _screen_station(
        screen={"phase": "phase12", "policy": {"action_policy_mode": "observe_only"}, "trace": {"summary": "trace"}}, deictic=None
    )

    assert stations[0]["stationFamily"] == "screen_awareness"


def test_command_surface_v2_selected_target_none_does_not_crash() -> None:
    stations = _screen_station(
        screen={"phase": "phase12", "policy": {"action_policy_mode": "observe_only"}, "trace": {"summary": "trace"}},
        deictic={"selected_target": None, "source_summary": "No live target binding."},
    )

    assert stations[0]["stationFamily"] == "screen_awareness"


def test_command_surface_v2_builds_screen_awareness_station_from_partial_state() -> None:
    model = build_command_surface_model(
        active_request_state={
            "family": "screen_awareness",
            "subject": "current screen",
            "parameters": {"request_stage": "inspect"},
        },
        active_task=None,
        recent_context_resolutions=None,
        latest_message={
            "bearing_title": "Screen Bearings",
            "content": "I only have partial screen-awareness state.",
            "metadata": {
                "route_state": {
                    "winner": {
                        "route_family": "screen_awareness",
                        "query_shape": "screen_awareness_request",
                        "status": "inspect",
                    },
                    "deictic_binding": {"selected_target": None},
                }
            },
        },
        status={"screen_awareness": {"phase": "phase12", "policy_state": None, "hardening": {"latest_trace": None}}},
        workspace_focus=None,
    )

    station = next(item for item in model["deckStations"] if item["stationFamily"] == "screen_awareness")
    entries = [entry for section in station["sections"] for entry in section["entries"]]
    assert station["title"] == "Screen Awareness"
    assert any(entry.get("primary") == "Policy" for entry in entries)
    assert any(entry.get("primary") == "Binding" for entry in entries)
