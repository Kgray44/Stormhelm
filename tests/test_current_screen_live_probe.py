from __future__ import annotations

import json

from stormhelm.core.kraken.current_screen_live_probe import (
    CurrentScreenLiveProbeOptions,
    detect_raw_payload_leak,
    run_current_screen_live_probe,
)


REQUIRED_ROW_FIELDS = {
    "scenario_label",
    "prompt",
    "route_family",
    "observation_attempted",
    "observation_available",
    "observation_allowed",
    "observation_blocked_reason",
    "evidence_before_observation",
    "evidence_after_observation",
    "answered_from_source",
    "visible_context_summary",
    "ghost_text",
    "deck_trace_summary",
    "weak_fallback_used",
    "no_visual_evidence_reason",
    "raw_payload_leak_detected",
    "ui_action_attempted",
    "pass_manual_review_hint",
    "warnings",
    "errors",
    "elapsed_ms",
}


class FakeResponse:
    def __init__(self, *, prompt: str, observation: dict, trace: dict, text: str, action_requested: bool = False) -> None:
        self.assistant_response = text
        self.response_contract = {
            "bearing_title": "Screen Bearings",
            "micro_response": text.split(".", 1)[0] + ".",
            "full_response": text,
            "evidence_kind": observation.get("evidence_kind", "visual_content"),
            "visible_context_summary": observation.get("visible_context_summary", {}).get("summary", ""),
        }
        self.telemetry = {
            "route": {"intent": "inspect_visible_state", "surface_mode": "ghost", "active_module": "chartroom"},
            "observation": observation,
            "trace": trace,
            "action": {"requested": action_requested},
        }
        self.analysis = None
        self.prompt = prompt


class FakeSubsystem:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def handle_request(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.responses:
            return self.responses.pop(0)
        raise AssertionError("No fake response configured")

    def status_snapshot(self) -> dict[str, object]:
        return {
            "phase": "phase12",
            "debug": {
                "latest_trace": {
                    "visible_context_summary": {"summary": "Trace summary"},
                    "raw_pixels": "iVBORw0KGgoSHOULD_NOT_PERSIST",
                }
            },
        }


def _trace(answered_from: str = "local_ocr") -> dict:
    return {
        "trace_id": "screen-test-trace",
        "observation_attempted": True,
        "observation_available": True,
        "observation_allowed": True,
        "observation_source": "screen_capture",
        "observation_freshness": "current",
        "answered_from_source": answered_from,
        "visible_context_summary": {
            "summary": "A visible error dialog is shown.",
            "key_text": ["Connection Error"],
            "likely_task": {"label": "troubleshooting a visible error", "confidence": "high"},
            "help_options": ["I can help troubleshoot the visible error."],
        },
        "evidence_ranking": [
            {
                "rank": 1,
                "source": "screen_capture",
                "freshness": "current",
                "confidence": {"level": "high", "score": 0.92},
            },
            {
                "rank": 2,
                "source": "local_ocr",
                "freshness": "current",
                "confidence": {"level": "high", "score": 0.9},
            },
        ],
    }


def _observation(answered_from: str = "local_ocr", *, weak: bool = False, clipboard: bool = False) -> dict:
    ranking = _trace(answered_from)["evidence_ranking"]
    if weak:
        ranking = [
            {
                "rank": 1,
                "source": "active_window_title",
                "freshness": "current",
                "confidence": {"level": "low", "score": 0.2},
            }
        ]
    if clipboard:
        ranking = [
            {
                "rank": 1,
                "source": "clipboard_hint",
                "freshness": "clipboard_hint",
                "confidence": {"level": "none", "score": 0.08},
                "used_for_summary": False,
            }
        ]
    return {
        "evidence_kind": "window_metadata" if weak else "clipboard_hint" if clipboard else "visual_content",
        "observation_attempted": True,
        "observation_available": not weak,
        "observation_allowed": True,
        "observation_blocked_reason": "screen_capture_unavailable" if weak else None,
        "observation_source": "active_window_title" if weak else "screen_capture",
        "observation_freshness": "current",
        "answered_from_source": answered_from,
        "weak_fallback_used": weak or clipboard,
        "no_visual_evidence_reason": "insufficient_visual_evidence" if weak or clipboard else None,
        "visible_context_summary": {} if weak or clipboard else _trace(answered_from)["visible_context_summary"],
        "evidence_before_observation": [],
        "evidence_after_observation": ranking,
        "evidence_ranking": ranking,
        "screen_capture": {
            "captured": not weak,
            "raw_screenshot_logged": False,
            "image_retained": False,
            "raw_pixels": "iVBORw0KGgoSHOULD_NOT_PERSIST",
        },
    }


def test_current_screen_live_probe_writes_required_artifacts_and_rows(tmp_path) -> None:
    subsystem = FakeSubsystem(
        [
            FakeResponse(
                prompt="What is on my screen right now?",
                observation=_observation(),
                trace=_trace(),
                text="Observed: A visible error dialog is shown. I can help troubleshoot it.",
            )
        ]
    )

    result = run_current_screen_live_probe(
        CurrentScreenLiveProbeOptions(
            scenario_label="clipping-tool-error",
            prompts=("What is on my screen right now?",),
            output_dir=tmp_path,
            timestamp="2026-05-04T150000Z",
        ),
        subsystem=subsystem,
    )

    assert result.output_dir.name == "2026-05-04T150000Z-clipping-tool-error"
    for name in {
        "live_current_screen_probe_report.json",
        "live_current_screen_probe_summary.md",
        "live_current_screen_probe_rows.jsonl",
        "live_current_screen_probe_rows.csv",
    }:
        assert (result.output_dir / name).exists()
    row = result.rows[0].to_dict()
    assert REQUIRED_ROW_FIELDS <= set(row)
    assert row["scenario_label"] == "clipping-tool-error"
    assert row["route_family"] == "screen_awareness"
    assert row["answered_from_source"] == "local_ocr"
    assert "answered_from_pixels_or_ocr" in row["pass_manual_review_hint"]
    assert "deck_trace_present" in row["pass_manual_review_hint"]


def test_current_screen_live_probe_scenario_label_does_not_fake_observation(tmp_path) -> None:
    subsystem = FakeSubsystem(
        [
            FakeResponse(
                prompt="What do you see?",
                observation=_observation("insufficient_visual_evidence", weak=True),
                trace={**_trace("insufficient_visual_evidence"), "evidence_ranking": _observation("insufficient_visual_evidence", weak=True)["evidence_ranking"]},
                text="Observed: I only have weak window metadata right now; I cannot honestly describe the screen contents yet.",
            )
        ]
    )

    result = run_current_screen_live_probe(
        CurrentScreenLiveProbeOptions(
            scenario_label="clipping-tool-error",
            prompts=("What do you see?",),
            output_dir=tmp_path,
            timestamp="2026-05-04T150001Z",
        ),
        subsystem=subsystem,
    )

    row = result.rows[0]
    assert row.scenario_label == "clipping-tool-error"
    assert row.answered_from_source == "insufficient_visual_evidence"
    assert "clipping_tool_content_first" not in row.pass_manual_review_hint
    assert "weak_metadata_only" in row.pass_manual_review_hint


def test_current_screen_live_probe_redacts_raw_payloads_and_detects_leaks(tmp_path) -> None:
    assert detect_raw_payload_leak({"image": "data:image/png;base64,iVBORw0KGgoAAA"}) is True
    subsystem = FakeSubsystem(
        [
            FakeResponse(
                prompt="What am I looking at?",
                observation=_observation(),
                trace=_trace(),
                text="Observed: A visible error dialog is shown.",
            )
        ]
    )

    result = run_current_screen_live_probe(
        CurrentScreenLiveProbeOptions(
            scenario_label="general",
            prompts=("What am I looking at?",),
            output_dir=tmp_path,
            timestamp="2026-05-04T150002Z",
        ),
        subsystem=subsystem,
    )

    serialized = json.dumps(json.loads((result.output_dir / "live_current_screen_probe_report.json").read_text()), sort_keys=True)
    assert "iVBORw0KGgoSHOULD_NOT_PERSIST" not in serialized
    assert "data:image" not in serialized
    assert result.rows[0].raw_payload_leak_detected is True
    assert "raw_payload_leak_detected" in result.rows[0].pass_manual_review_hint


def test_current_screen_live_probe_flags_ui_actions_and_clipboard_stale_hints(tmp_path) -> None:
    subsystem = FakeSubsystem(
        [
            FakeResponse(
                prompt="Can you help with this?",
                observation=_observation("clipboard_hint", clipboard=True),
                trace={**_trace("clipboard_hint"), "evidence_ranking": _observation("clipboard_hint", clipboard=True)["evidence_ranking"]},
                text="I cannot confirm that the clipboard matches what is on the screen.",
                action_requested=True,
            )
        ]
    )

    result = run_current_screen_live_probe(
        CurrentScreenLiveProbeOptions(
            scenario_label="clipboard-stale-mismatch",
            prompts=("Can you help with this?",),
            output_dir=tmp_path,
            timestamp="2026-05-04T150003Z",
        ),
        subsystem=subsystem,
    )

    row = result.rows[0]
    assert row.ui_action_attempted is True
    assert "ui_action_attempted" in row.pass_manual_review_hint
    assert "stale_or_clipboard_only" in row.pass_manual_review_hint
    assert "strong_evidence_used" not in row.pass_manual_review_hint


def test_current_screen_live_probe_clipping_tool_content_first_hint_and_unavailable_capture(tmp_path) -> None:
    subsystem = FakeSubsystem(
        [
            FakeResponse(
                prompt="Summarize this screen.",
                observation=_observation(),
                trace=_trace(),
                text="Observed: The screenshot content appears to show Connection Error. Supporting window metadata points to Clipping Tool.",
            ),
            FakeResponse(
                prompt="What do you see?",
                observation=_observation("foreground_window_stack", weak=True),
                trace={**_trace("foreground_window_stack"), "observation_available": False, "observation_blocked_reason": "screen_capture_unavailable"},
                text="Observed: I only have weak window metadata right now; capture is unavailable.",
            ),
        ]
    )

    result = run_current_screen_live_probe(
        CurrentScreenLiveProbeOptions(
            scenario_label="clipping-tool-error",
            prompts=("Summarize this screen.", "What do you see?"),
            output_dir=tmp_path,
            timestamp="2026-05-04T150004Z",
        ),
        subsystem=subsystem,
    )

    assert "clipping_tool_content_first" in result.rows[0].pass_manual_review_hint
    assert "capture_unavailable" in result.rows[1].pass_manual_review_hint
    assert result.report["completed"] is True
