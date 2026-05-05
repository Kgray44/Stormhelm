from __future__ import annotations

from stormhelm.core.kraken.cross_context_visual import (
    CrossContextCapabilityReport,
    CrossContextVisualCase,
    CrossContextVisualRow,
    SourceArbitrationContext,
    build_corpus,
    build_gate_summary,
    build_source_matrix,
    classify_row,
    decide_sources,
    summarize_rows,
)


def _context() -> SourceArbitrationContext:
    return SourceArbitrationContext(
        camera_available=True,
        screen_available=True,
        obscura_cli_render_supported=True,
        obscura_session_inspection_supported=False,
        obscura_tab_identity_supported=False,
        selected_text_available=True,
        clipboard_hint_available=True,
        stale_visual_snapshot_available=True,
    )


def test_source_arbitration_distinguishes_camera_screen_and_obscura() -> None:
    context = _context()

    camera = decide_sources("What is in front of me?", context)
    screen = decide_sources("What is on my screen?", context)
    page = decide_sources("Summarize this page.", context)
    comparison = decide_sources("Compare what the camera sees to what is on my screen.", context)

    assert camera.primary_source == "camera_live"
    assert camera.route_family == "camera_awareness"
    assert screen.primary_source == "screen_current"
    assert screen.route_family == "screen_awareness"
    assert page.primary_source == "obscura_rendered_page"
    assert page.route_family == "web_retrieval"
    assert comparison.primary_source == "camera_live"
    assert set(comparison.sources_used) >= {"camera_live", "screen_current"}


def test_deictic_ambiguity_clarifies_with_multiple_visual_sources() -> None:
    decision = decide_sources("What is this?", _context())

    assert decision.primary_source == "clarification_needed"
    assert decision.result_state == "expected_clarification"
    assert decision.clarification_asked is True
    assert decision.route_family == "context_clarification"


def test_obscura_unsupported_tab_session_is_typed_unavailable() -> None:
    decision = decide_sources("Which browser tab is active?", _context())

    assert decision.primary_source == "browser_session_unavailable"
    assert decision.result_state == "browser_session_unavailable"
    assert decision.expected_unavailable is True
    assert decision.obscura_capability_unavailable == "tab_identity"
    assert decision.route_family == "web_retrieval"


def test_clipboard_hint_never_becomes_screen_truth() -> None:
    decision = decide_sources(
        "Can you explain this?",
        SourceArbitrationContext(
            camera_available=False,
            screen_available=False,
            obscura_cli_render_supported=False,
            clipboard_hint_available=True,
        ),
    )

    assert decision.primary_source == "clarification_needed"
    assert "clipboard_hint" in decision.sources_used
    assert decision.clipboard_used_as_hint is True
    assert decision.screen_used is False


def test_stale_context_must_be_labeled() -> None:
    decision = decide_sources("Is this still open?", _context())

    assert decision.primary_source == "screen_stale"
    assert decision.stale_evidence_used is True
    assert decision.stale_labeled is True
    assert decision.result_state == "stale_labeled"


def test_cross_context_corpus_shape_and_provider_protection() -> None:
    corpus = build_corpus()

    assert 140 <= len(corpus) <= 200
    assert sum(1 for case in corpus if case.lane == "camera_vs_screen") >= 25
    assert sum(1 for case in corpus if case.lane == "screen_vs_obscura") >= 25
    assert sum(1 for case in corpus if case.lane == "camera_vs_obscura") >= 20
    assert sum(1 for case in corpus if case.lane == "unsupported_capability") >= 15
    assert all(case.expected_route_family != "generic_provider" for case in corpus)


def test_gate_summary_blocks_provider_fake_action_and_source_confusion() -> None:
    case = CrossContextVisualCase(
        row_id="bad",
        prompt="What is on my screen?",
        lane="provider_native",
        target_kind="screen",
        expected_primary_source="screen_current",
        expected_secondary_sources=(),
        expected_route_family="screen_awareness",
        expected_subsystem="screen_awareness",
        expected_result_state="screen_observed",
        expected_clarification=False,
        expected_unavailable=False,
        expected_blocked=False,
        camera_required=False,
        screen_required=True,
        obscura_required=False,
    )
    row = CrossContextVisualRow.from_case(
        case,
        actual_primary_source="camera_live",
        actual_sources_used=("camera_live",),
        actual_route_family="generic_provider",
        actual_subsystem="provider",
        actual_result_state="screen_observed",
        provider_fallback_used=True,
        provider_calls=1,
        action_attempted=True,
    )
    classify_row(row)

    gate = build_gate_summary([row], capability_report=CrossContextCapabilityReport())

    assert gate["provider_calls_total"] == 1
    assert gate["release_posture"] == "blocked_provider_native_hijack"


def test_report_contains_source_matrix_and_safety_summary() -> None:
    case = build_corpus()[0]
    row = CrossContextVisualRow.from_case(
        case,
        actual_primary_source=case.expected_primary_source,
        actual_sources_used=(case.expected_primary_source,),
        actual_route_family=case.expected_route_family,
        actual_subsystem=case.expected_subsystem,
        actual_result_state=case.expected_result_state,
        camera_used=case.camera_required,
        screen_used=case.screen_required,
        obscura_used=case.obscura_required,
        failure_category="pass",
    )

    summary = summarize_rows([row], capability_report=CrossContextCapabilityReport())
    matrix = build_source_matrix([row])

    assert "safety_summary" in summary
    assert "source_matrix" in summary
    assert matrix["by_expected_primary"][case.expected_primary_source][case.expected_primary_source] == 1
