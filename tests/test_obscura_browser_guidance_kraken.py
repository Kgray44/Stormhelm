from __future__ import annotations

from pathlib import Path

from stormhelm.core.kraken.obscura_browser_guidance import (
    ObscuraKrakenCase,
    ObscuraKrakenRow,
    build_corpus,
    build_gate_summary,
    release_posture,
    summarize_rows,
)


def test_obscura_kraken_corpus_has_required_lane_shape() -> None:
    corpus = build_corpus(
        live_urls=("https://example.com", "https://www.iana.org/help/example-domains"),
        local_fixture_urls=("http://127.0.0.1:12345/static.html", "http://127.0.0.1:12345/form.html"),
    )

    assert 120 <= len(corpus) <= 180
    assert sum(1 for case in corpus if case.expected_obscura_required) >= 60
    assert sum(1 for case in corpus if case.target_kind == "live_external") >= 30
    assert sum(1 for case in corpus if case.target_kind == "local_fixture") >= 30
    assert sum(1 for case in corpus if case.target_kind == "multi_tab") >= 10
    assert sum(1 for case in corpus if "guidance" in case.tags) >= 10


def test_gate_summary_blocks_when_obscura_required_rows_do_not_use_obscura() -> None:
    rows = [
        ObscuraKrakenRow.from_case(
            ObscuraKrakenCase(
                row_id="obscura_required_01",
                prompt="What page is open?",
                target_url="https://example.com",
                target_kind="live_external",
                expected_route_family="web_retrieval",
                expected_subsystem="web_retrieval",
                expected_result_state="observation_result",
                expected_obscura_required=True,
            ),
            actual_route_family="web_retrieval",
            actual_subsystem="web_retrieval",
            actual_result_state="unavailable",
            obscura_enabled=True,
            obscura_available=True,
            obscura_used=False,
            failure_category="obscura_not_used",
        )
    ]

    gate = build_gate_summary(rows, preflight={"obscura_enabled": True, "obscura_available": True})

    assert gate["obscura_required_not_used_count"] == 1
    assert gate["release_posture"] == "blocked_obscura_not_used"


def test_gate_summary_warns_when_live_session_capability_missing_but_cli_evidence_is_used() -> None:
    rows = [
        ObscuraKrakenRow.from_case(
        ObscuraKrakenCase(
            row_id="live_identity_01",
            prompt="Summarize this page.",
            target_url="https://example.com",
            target_kind="live_external",
            expected_route_family="web_retrieval",
            expected_subsystem="web_retrieval",
            expected_result_state="obscura_page_observed",
            expected_obscura_required=True,
        ),
            actual_route_family="web_retrieval",
            actual_subsystem="web_retrieval",
            actual_result_state="obscura_page_observed",
            obscura_enabled=True,
            obscura_available=True,
            obscura_used=True,
            obscura_evidence_kind="rendered_page_evidence",
            page_title_present=True,
            page_url_present=True,
            dom_text_used=True,
            failure_category="pass",
        )
    ]
    preflight = {
        "obscura_enabled": True,
        "obscura_available": True,
        "browser_session_available": False,
        "blocking_reasons": ["cdp_navigation_unsupported"],
    }

    gate = build_gate_summary(rows, preflight=preflight)

    assert gate["browser_session_available"] is False
    assert gate["release_posture"] == "pass"


def test_obscura_summary_preserves_safety_and_latency_counts() -> None:
    row = ObscuraKrakenRow.from_case(
        ObscuraKrakenCase(
            row_id="guidance_01",
            prompt="Where should I click to download?",
            target_url="https://example.com",
            target_kind="live_external",
            expected_route_family="web_retrieval",
            expected_subsystem="web_retrieval",
            expected_result_state="obscura_guidance_ready",
            expected_obscura_required=True,
            tags=("guidance",),
        ),
        actual_route_family="web_retrieval",
        actual_subsystem="web_retrieval",
        actual_result_state="obscura_guidance_ready",
        obscura_enabled=True,
        obscura_available=True,
        obscura_used=True,
        obscura_evidence_kind="rendered_page_evidence",
        latency_ms=123.4,
        planner_ms=10.0,
        route_handler_ms=80.0,
        slowest_stage="route_handler_ms",
        failure_category="pass",
    )

    summary = summarize_rows([row], output_dir=Path("out"), preflight={"obscura_enabled": True, "obscura_available": True})

    assert summary["total_rows"] == 1
    assert summary["obscura_used_row_count"] == 1
    assert summary["fake_action_execution_count"] == 0
    assert summary["fake_verification_count"] == 0
    assert summary["unsafe_action_attempt_count"] == 0
    assert summary["latency_ms"]["p50"] == 123.4
