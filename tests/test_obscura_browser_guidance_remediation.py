from __future__ import annotations

from stormhelm.config.loader import load_config
from stormhelm.core.kraken.obscura_browser_guidance import (
    ObscuraCapabilityReport,
    ObscuraKrakenCase,
    ObscuraKrakenRow,
    _plan_route,
    _preflight_summary,
    _row_from_bundle,
    build_corpus,
    build_gate_summary,
    run_lane,
)
from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _cdp_unsupported_preflight() -> dict[str, object]:
    return _preflight_summary(
        {
            "results": {
                "obscura_cli": {"enabled": True, "status": "passed"},
                "obscura_cdp": {
                    "enabled": True,
                    "status": "incompatible",
                    "error_code": "cdp_navigation_unsupported",
                    "details": {
                        "endpoint_discovered": True,
                        "navigation_supported": False,
                        "page_inspection_supported": False,
                    },
                },
            }
        }
    )


def _planner() -> DeterministicPlanner:
    config = load_config()
    return DeterministicPlanner(
        screen_awareness_config=config.screen_awareness,
        discord_relay_config=config.discord_relay,
    )


def _winner_family(prompt: str) -> str:
    preflight = _cdp_unsupported_preflight()
    family, _ = _plan_route(
        _planner(),
        ObscuraKrakenCase(
            row_id="route_probe",
            prompt=prompt,
            target_url="https://example.com",
            target_kind="live_external",
            expected_route_family="web_retrieval",
            expected_subsystem="web_retrieval",
            expected_result_state="obscura_page_observed",
            expected_obscura_required=True,
        ),
        preflight=preflight,
    )
    return family


def test_capability_report_distinguishes_cli_render_from_cdp_session_support() -> None:
    preflight = _cdp_unsupported_preflight()
    report = ObscuraCapabilityReport.from_preflight(
        {
            "results": {
                "obscura_cli": {"enabled": True, "status": "passed"},
                "obscura_cdp": {
                    "enabled": True,
                    "status": "incompatible",
                    "error_code": "cdp_navigation_unsupported",
                    "details": {"endpoint_discovered": True},
                },
            }
        },
        private_ip_targets_allowed=False,
        local_fixture_targets_allowed=False,
    )

    assert report.obscura_cli_render_supported is True
    assert report.obscura_cdp_reachable is True
    assert report.obscura_cdp_navigation_supported is False
    assert report.obscura_tab_identity_supported is False
    assert preflight["blocking_reasons"] == []
    assert "cdp_navigation_unsupported" in preflight["warnings"]


def test_cdp_navigation_unsupported_is_typed_expected_unavailable() -> None:
    case = ObscuraKrakenCase(
        row_id="multi_tab_01",
        prompt="Which tab is active?",
        target_url="https://example.com",
        target_kind="multi_tab",
        expected_route_family="web_retrieval",
        expected_subsystem="web_retrieval",
        expected_result_state="obscura_tab_identity_unavailable",
        expected_obscura_required=True,
        retrieval_provider="obscura_cdp",
        tags=("multi_tab", "cdp_required"),
    )
    row = _row_from_bundle(
        case,
        bundle=None,
        preflight=_cdp_unsupported_preflight(),
        actual_route_family="web_retrieval",
        actual_subsystem="web_retrieval",
        planner_ms=1.0,
        route_handler_ms=1.0,
        total_ms=2.0,
    )

    assert row.actual_result_state == "obscura_tab_identity_unavailable"
    assert row.failure_category == "expected_unavailable"


def test_private_fixture_target_block_is_typed_safety_block() -> None:
    class Page:
        provider = "obscura"
        status = "failed"
        error_code = "process_error"
        error_message = "Access to private/internal IP address 127.0.0.1 is not allowed"
        title = ""
        text_chars = 0
        link_count = 0
        final_url = "http://127.0.0.1:12345/static.html"
        confidence = "low"

    class Trace:
        def to_dict(self) -> dict[str, object]:
            return {}

    class Bundle:
        pages = [Page()]
        trace = Trace()

    case = ObscuraKrakenCase(
        row_id="local_dom_01",
        prompt="Extract the visible headings from http://127.0.0.1:12345/static.html.",
        target_url="http://127.0.0.1:12345/static.html",
        target_kind="local_fixture",
        expected_route_family="web_retrieval",
        expected_subsystem="web_retrieval",
        expected_result_state="obscura_private_target_blocked",
        expected_obscura_required=True,
        tags=("dom", "local_fixture"),
    )

    row = _row_from_bundle(
        case,
        bundle=Bundle(),
        preflight=_cdp_unsupported_preflight(),
        actual_route_family="web_retrieval",
        actual_subsystem="web_retrieval",
        planner_ms=1.0,
        route_handler_ms=1.0,
        total_ms=2.0,
    )

    assert row.actual_result_state == "obscura_private_target_blocked"
    assert row.failure_category == "expected_blocked"


def test_url_page_reads_route_web_retrieval_while_direct_open_stays_browser_destination() -> None:
    assert _winner_family("Read https://example.com") == "web_retrieval"
    assert _winner_family("Find the section about installation on https://example.com.") == "web_retrieval"
    assert _winner_family("On https://example.com, which link should I click for documentation?") == "web_retrieval"
    assert _winner_family("open github.com") == "browser_destination"


def test_active_tab_prompt_does_not_select_generic_provider_when_obscura_session_is_unavailable() -> None:
    assert _winner_family("Which tab is active?") == "web_retrieval"
    assert _winner_family("What are the open tabs?") == "web_retrieval"


def test_expected_unavailable_and_blocked_rows_do_not_count_as_obscura_not_used() -> None:
    rows = [
        ObscuraKrakenRow.from_case(
            ObscuraKrakenCase(
                row_id="tab_unavailable",
                prompt="Which tab is active?",
                target_url="https://example.com",
                target_kind="multi_tab",
                expected_route_family="web_retrieval",
                expected_subsystem="web_retrieval",
                expected_result_state="obscura_tab_identity_unavailable",
                expected_obscura_required=True,
            ),
            actual_route_family="web_retrieval",
            actual_subsystem="web_retrieval",
            actual_result_state="obscura_tab_identity_unavailable",
            obscura_enabled=True,
            obscura_available=True,
            obscura_used=False,
            failure_category="expected_unavailable",
        ),
        ObscuraKrakenRow.from_case(
            ObscuraKrakenCase(
                row_id="fixture_blocked",
                prompt="Read the fixture.",
                target_url="http://127.0.0.1:1/static.html",
                target_kind="local_fixture",
                expected_route_family="web_retrieval",
                expected_subsystem="web_retrieval",
                expected_result_state="obscura_private_target_blocked",
                expected_obscura_required=True,
            ),
            actual_route_family="web_retrieval",
            actual_subsystem="web_retrieval",
            actual_result_state="obscura_private_target_blocked",
            obscura_enabled=True,
            obscura_available=True,
            obscura_used=False,
            failure_category="expected_blocked",
        ),
    ]

    gate = build_gate_summary(rows, preflight=_cdp_unsupported_preflight())

    assert gate["obscura_required_not_used_count"] == 0
    assert gate["expected_unavailable_count"] == 1
    assert gate["expected_blocked_count"] == 1
    assert gate["release_posture"] == "pass"


def test_obscura_required_corpus_routes_never_select_generic_provider() -> None:
    preflight = _cdp_unsupported_preflight()
    planner = _planner()
    cases = build_corpus(
        live_urls=("https://example.com", "https://www.example.org"),
        local_fixture_urls=("http://127.0.0.1:12345/static.html", "http://127.0.0.1:12345/form.html"),
    )

    selected = [_plan_route(planner, case, preflight=preflight)[0] for case in cases if case.expected_obscura_required]

    assert "generic_provider" not in selected


def test_run_lane_writes_standalone_capability_report(tmp_path, monkeypatch) -> None:
    def fake_run_all(self):  # type: ignore[no-untyped-def]
        class Report:
            def to_dict(self) -> dict[str, object]:
                return {
                    "results": {
                        "obscura_cli": {"enabled": True, "status": "passed"},
                        "obscura_cdp": {
                            "enabled": True,
                            "status": "incompatible",
                            "error_code": "cdp_navigation_unsupported",
                            "details": {"endpoint_discovered": True},
                        },
                    }
                }

        return Report()

    monkeypatch.setattr(
        "stormhelm.core.kraken.obscura_browser_guidance.LiveBrowserIntegrationRunner.run_all",
        fake_run_all,
    )
    monkeypatch.setattr(
        "stormhelm.core.kraken.obscura_browser_guidance.execute_corpus",
        lambda *args, **kwargs: [],
    )

    summary = run_lane(output_dir=tmp_path, live_urls=("https://example.com",))
    capability_path = tmp_path / "obscura_capability_report.json"

    assert capability_path.exists()
    assert summary["obscura_capability_report"]["obscura_cli_render_supported"] is True
