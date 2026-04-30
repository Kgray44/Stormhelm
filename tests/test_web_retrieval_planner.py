from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _plan(message: str):
    return DeterministicPlanner().plan(
        message,
        session_id="web-retrieval-test",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state={},
        active_context={},
        recent_tool_results=[],
    )


def _plan_with_current_page(message: str):
    current_page = {
        "module": "browser",
        "active_item": {
            "title": "Example Docs",
            "url": "https://example.com/docs",
            "kind": "browser-tab",
        },
        "opened_items": [
            {
                "title": "Example Docs",
                "url": "https://example.com/docs",
                "kind": "browser-tab",
            }
        ],
    }
    return DeterministicPlanner().plan(
        message,
        session_id="web-retrieval-current-page-test",
        surface_mode="ghost",
        active_module="browser",
        workspace_context=current_page,
        active_posture={},
        active_request_state={},
        active_context=current_page,
        recent_tool_results=[],
    )


def _winner(decision) -> str:
    route_state = decision.route_state.to_dict()
    return route_state["winner"]["route_family"]


def test_planner_routes_url_summarization_to_web_retrieval_tool() -> None:
    decision = _plan("summarize https://example.com/docs")

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner(decision) == "web_retrieval"
    assert decision.structured_query.query_shape.value == "web_retrieval_request"
    assert decision.tool_requests[0].tool_name == "web_retrieval_fetch"
    assert decision.tool_requests[0].arguments["urls"] == ["https://example.com/docs"]
    assert decision.tool_requests[0].arguments["intent"] == "summarize_page"
    assert decision.active_request_state["family"] == "web_retrieval"


def test_planner_routes_url_link_extraction_to_web_retrieval_without_overriding_browser_open() -> None:
    extract = _plan("extract links from https://example.com/docs")
    open_page = _plan("open https://example.com/docs")

    assert _winner(extract) == "web_retrieval"
    assert extract.tool_requests[0].tool_name == "web_retrieval_fetch"
    assert extract.tool_requests[0].arguments["intent"] == "extract_links"

    assert _winner(open_page) == "browser_destination"
    assert open_page.tool_requests[0].tool_name == "external_open_url"


def test_planner_routes_render_current_page_to_web_retrieval_when_page_context_exists() -> None:
    decision = _plan_with_current_page("render this page")

    assert _winner(decision) == "web_retrieval"
    assert decision.tool_requests[0].tool_name == "web_retrieval_fetch"
    assert decision.tool_requests[0].arguments["urls"] == ["https://example.com/docs"]
    assert decision.tool_requests[0].arguments["intent"] == "render_page"


def test_planner_routes_cdp_specific_inspection_without_stealing_browser_open() -> None:
    decision = _plan("use Obscura CDP to inspect https://example.com/docs")
    network = _plan("show me network summary for this public page https://example.com/docs")
    open_page = _plan("open https://example.com/docs")

    assert _winner(decision) == "web_retrieval"
    assert decision.tool_requests[0].tool_name == "web_retrieval_fetch"
    assert decision.tool_requests[0].arguments["preferred_provider"] == "obscura_cdp"
    assert decision.tool_requests[0].arguments["intent"] == "cdp_inspect"
    assert decision.tool_requests[0].arguments["include_links"] is True

    assert _winner(network) == "web_retrieval"
    assert network.tool_requests[0].arguments["preferred_provider"] == "obscura_cdp"
    assert network.tool_requests[0].arguments["intent"] == "cdp_network_summary"

    assert _winner(open_page) == "browser_destination"


def test_planner_keeps_browser_open_requests_out_of_web_retrieval() -> None:
    youtube = _plan("open YouTube")
    chrome = _plan("open this in Chrome")

    assert _winner(youtube) == "browser_destination"
    assert youtube.tool_requests[0].tool_name == "external_open_url"
    assert _winner(chrome) in {"browser_destination", "app_control", "software_control"}
    assert _winner(chrome) != "web_retrieval"


def test_planner_keeps_screen_relay_app_control_and_generic_search_out_of_web_retrieval() -> None:
    cases = {
        "what am I looking at?": "screen_awareness",
        "send this page to Baby": "discord_relay",
        "install Chrome": "software_control",
    }

    for message, expected in cases.items():
        assert _winner(_plan(message)) == expected

    assert _winner(_plan("click the button on this page")) != "web_retrieval"

    search = _plan("search the web for storm surge radar")
    assert _winner(search) != "web_retrieval"
