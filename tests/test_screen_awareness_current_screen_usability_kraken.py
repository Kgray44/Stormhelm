from __future__ import annotations

from stormhelm.core.kraken.current_screen_usability import (
    CurrentScreenUsabilityKrakenHarness,
    default_current_screen_usability_cases,
    summarize_current_screen_usability_rows,
)


REQUIRED_SCENARIO_FAMILIES = {
    "clipping_tool_error",
    "clipping_tool_homework_math",
    "browser_article",
    "file_explorer",
    "terminal_error_log",
    "settings_control_panel",
    "multiple_overlapping_windows",
    "blank_low_information_desktop",
    "ocr_heavy_screen",
    "image_heavy_low_ocr",
    "weak_metadata_only",
    "capture_unavailable",
    "clipboard_stale_hints",
}

REQUIRED_EVIDENCE_MODES = {
    "weak_metadata",
    "fresh_ocr",
    "screenshot_pixels",
    "ui_automation",
    "selected_visible_text",
    "app_semantic_context",
    "multiple_windows",
    "stale_and_clipboard_hints",
}

REQUIRED_ROW_FIELDS = {
    "prompt",
    "scenario_id",
    "expected_route_family",
    "evidence_before_observation",
    "observation_attempted",
    "evidence_after_observation",
    "answered_from_source",
    "visible_context_summary_present",
    "key_text_quality",
    "task_hypothesis_quality",
    "ghost_compact",
    "deck_trace_complete",
    "raw_payload_leak_detected",
    "pass_fail_reason",
}


def _harness(temp_config) -> CurrentScreenUsabilityKrakenHarness:
    return CurrentScreenUsabilityKrakenHarness(temp_config.screen_awareness)


def test_current_screen_usability_kraken_fixtures_cover_required_scenarios() -> None:
    cases = default_current_screen_usability_cases()

    assert REQUIRED_SCENARIO_FAMILIES <= {case.scenario_family for case in cases}
    assert REQUIRED_EVIDENCE_MODES <= {case.evidence_mode for case in cases}
    assert {
        "what is on my screen right now?",
        "what do you see?",
        "what am I looking at?",
        "can you help with this?",
    } <= {case.prompt for case in cases}
    assert all(case.golden_response_snapshot for case in cases)


def test_current_screen_usability_kraken_scores_default_cases_as_useful_and_grounded(temp_config) -> None:
    rows = _harness(temp_config).run(default_current_screen_usability_cases())

    assert len(rows) >= len(REQUIRED_SCENARIO_FAMILIES)
    assert not [row.to_dict() for row in rows if not row.passed]
    for row in rows:
        payload = row.to_dict()
        assert REQUIRED_ROW_FIELDS <= set(payload)
        assert row.expected_route_family == "screen_awareness"
        assert row.raw_payload_leak_detected is False
        assert row.ui_action_attempted is False
        assert row.ghost_compact is True
        assert row.deck_trace_complete is True


def test_current_screen_usability_kraken_preserves_evidence_ranking_and_source_truth(temp_config) -> None:
    rows = {row.scenario_id: row for row in _harness(temp_config).run(default_current_screen_usability_cases())}

    assert rows["weak_metadata_only"].weak_fallback_used is True
    assert rows["weak_metadata_only"].visible_context_summary_present is False
    assert rows["weak_metadata_only"].answered_from_source in {"foreground_window_stack", "active_window_title"}

    assert rows["clipping_tool_error"].answered_from_source == "local_ocr"
    assert rows["clipping_tool_error"].evidence_after_observation[0]["source"] == "screen_capture"
    assert rows["clipping_tool_error"].evidence_after_observation[0]["freshness"] == "current"

    assert rows["image_heavy_low_ocr"].answered_from_source == "screen_capture"
    assert rows["selected_visible_text"].answered_from_source == "selected_text"
    assert rows["ui_automation_context"].answered_from_source == "accessibility_ui_tree"
    assert rows["browser_semantic_context"].answered_from_source == "app_semantic_adapter"

    stale_clipboard = rows["clipboard_stale_hints"]
    assert stale_clipboard.weak_fallback_used is True
    assert stale_clipboard.answered_from_source not in {"clipboard_hint", "stale_recent_context"}
    assert stale_clipboard.no_visual_evidence_reason


def test_current_screen_usability_kraken_outputs_golden_examples_and_report_summary(temp_config) -> None:
    rows = _harness(temp_config).run(default_current_screen_usability_cases())
    summary = summarize_current_screen_usability_rows(rows)

    assert summary["total"] == len(rows)
    assert summary["passed"] == len(rows)
    assert summary["failed"] == 0
    assert summary["raw_payload_leaks"] == 0
    assert summary["ui_action_attempts"] == 0
    assert summary["families_covered"] >= len(REQUIRED_SCENARIO_FAMILIES)

    examples = summary["representative_outputs"]
    assert "clipping_tool_error" in examples
    assert "connection" in examples["clipping_tool_error"]["after"].lower()
    assert "screenshot 2026-05-04" not in examples["clipping_tool_error"]["after"].lower()
    assert "weak window metadata" in examples["weak_metadata_only"]["after"].lower()
    assert "clipboard" in examples["clipboard_stale_hints"]["after"].lower()
