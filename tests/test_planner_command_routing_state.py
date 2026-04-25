from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _plan(
    message: str,
    *,
    planner: DeterministicPlanner | None = None,
    active_request_state: dict[str, object] | None = None,
    active_context: dict[str, object] | None = None,
    surface_mode: str = "ghost",
):
    return (planner or DeterministicPlanner()).plan(
        message,
        session_id="default",
        surface_mode=surface_mode,
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state=active_request_state or {},
        recent_tool_results=[],
        active_context=active_context or {},
    )


def _route_state(decision) -> dict[str, object]:
    assert decision.route_state is not None
    payload = decision.route_state.to_dict()
    assert decision.debug["routing"] == payload
    return payload


def test_messy_install_phrase_scores_native_software_over_provider(temp_config) -> None:
    temp_config.software_control.enabled = True
    temp_config.software_control.planner_routing_enabled = True
    planner = DeterministicPlanner(software_control_config=temp_config.software_control)

    decision = _plan("can u pls get Minecraft on here", planner=planner)

    routing = _route_state(decision)
    candidates = {candidate["route_family"]: candidate for candidate in routing["candidates"]}
    assert decision.request_type == "software_control_response"
    assert decision.debug["normalized_command"]["normalized_text"] == "can you please get minecraft on here"
    assert routing["winner"]["route_family"] == "software_control"
    assert routing["winner"]["posture"] in {"clear_winner", "likely_winner"}
    assert candidates["software_control"]["score"] > candidates["generic_provider"]["score"]
    assert "native_route_candidate_present" in candidates["generic_provider"]["disqualifiers"]


def test_relay_request_binds_single_selected_payload_without_generic_fallback() -> None:
    decision = _plan(
        "send this to Baby",
        active_context={
            "selection": {
                "kind": "text",
                "value": "Selected launch notes.",
                "preview": "Selected launch notes.",
            }
        },
    )

    routing = _route_state(decision)
    candidates = {candidate["route_family"]: candidate for candidate in routing["candidates"]}
    assert decision.request_type == "discord_relay_dispatch"
    assert decision.structured_query is not None
    assert decision.structured_query.slots["payload_hint"] == "selected_text"
    assert routing["winner"]["route_family"] == "discord_relay"
    assert routing["deictic_binding"]["selected_source"] == "selection"
    assert candidates["discord_relay"]["score"] > candidates["generic_provider"]["score"]


def test_relay_request_clarifies_narrowly_when_payload_sources_compete() -> None:
    decision = _plan(
        "send this to Baby",
        active_context={
            "selection": {"kind": "text", "value": "Selected text.", "preview": "Selected text."},
            "clipboard": {"kind": "url", "value": "https://example.com", "preview": "https://example.com"},
        },
    )

    routing = _route_state(decision)
    assert decision.request_type == "clarification_request"
    assert decision.clarification_reason is not None
    assert decision.clarification_reason.code == "ambiguous_relay_payload"
    assert (
        decision.assistant_message
        == 'This looks like a relay request, but I still need to know whether "this" means the selected text or the clipboard.'
    )
    assert routing["winner"]["route_family"] == "discord_relay"
    assert routing["winner"]["posture"] == "conditional_winner"
    assert routing["winner"]["unresolved_targets"] == ["payload"]


def test_do_that_confirms_pending_relay_preview_through_shared_deictic_binding() -> None:
    decision = _plan(
        "do that",
        active_request_state={
            "family": "discord_relay",
            "subject": "Baby",
            "parameters": {
                "destination_alias": "Baby",
                "payload_hint": "selected_text",
                "pending_preview": {"preview_id": "relay-preview-1", "route_mode": "local_client_automation"},
            },
            "trust": {"request_id": "trust-1"},
        },
    )

    routing = _route_state(decision)
    assert decision.request_type == "discord_relay_dispatch"
    assert decision.structured_query is not None
    assert decision.structured_query.slots["request_stage"] == "dispatch"
    assert routing["winner"]["route_family"] == "discord_relay"
    assert routing["deictic_binding"]["selected_source"] == "active_preview"


def test_open_it_uses_single_recent_entity_binding() -> None:
    decision = _plan(
        "open it",
        active_context={
            "recent_entities": [
                {
                    "title": "Stormhelm docs",
                    "kind": "page",
                    "url": "https://docs.example.com/stormhelm",
                }
            ]
        },
    )

    routing = _route_state(decision)
    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://docs.example.com/stormhelm"
    assert routing["winner"]["route_family"] == "browser_destination"
    assert routing["deictic_binding"]["selected_source"] == "recent_session_entity"


def test_open_it_clarifies_between_recent_page_and_file_candidates() -> None:
    decision = _plan(
        "open it",
        active_context={
            "recent_entities": [
                {"title": "Stormhelm docs", "kind": "page", "url": "https://docs.example.com/stormhelm"},
                {"title": "Stormhelm notes", "kind": "file", "path": "C:\\Stormhelm\\README.md"},
            ]
        },
    )

    routing = _route_state(decision)
    assert decision.request_type == "clarification_request"
    assert decision.clarification_reason is not None
    assert decision.clarification_reason.code == "ambiguous_open_target"
    assert decision.assistant_message == "I think you mean the recent page, but a recent file is also still live. Which one should I open?"
    assert routing["winner"]["posture"] == "conditional_winner"
    assert routing["winner"]["unresolved_targets"] == ["target"]


def test_folder_correction_reuses_search_family_without_restating_request() -> None:
    decision = _plan(
        "no, the folder one",
        active_request_state={
            "family": "desktop_search",
            "subject": "search",
            "parameters": {
                "query": "Stormhelm docs",
                "ambiguity_choices": ["file", "folder"],
                "open_target": "external",
            },
        },
    )

    routing = _route_state(decision)
    assert decision.request_type == "search_and_act"
    assert decision.tool_requests[0].tool_name == "desktop_search"
    assert decision.tool_requests[0].arguments["query"] == "Stormhelm docs"
    assert decision.tool_requests[0].arguments["prefer_folders"] is True
    assert routing["winner"]["route_family"] == "desktop_search"
    assert "correction" in routing["decomposition"]["correction_cues"]


def test_trust_explanation_request_stays_native_instead_of_provider_fallback() -> None:
    decision = _plan(
        "why are you asking me?",
        active_request_state={
            "family": "software_control",
            "subject": "firefox",
            "parameters": {
                "operation_type": "install",
                "target_name": "firefox",
                "request_stage": "awaiting_confirmation",
            },
            "trust": {"request_id": "trust-42", "reason": "Installing software changes the machine."},
        },
    )

    routing = _route_state(decision)
    assert decision.request_type == "trust_approval_explanation"
    assert decision.tool_requests == []
    assert decision.assistant_message is not None
    assert "approval" in decision.assistant_message.lower()
    assert routing["winner"]["route_family"] == "trust_approvals"
    assert routing["winner"]["provider_fallback_reason"] is None


def test_unclassified_open_ended_request_exposes_honest_provider_fallback_reason() -> None:
    decision = _plan("write a poetic explanation of why finals feel like a haunted engine room")

    routing = _route_state(decision)
    assert decision.request_type == "unclassified"
    assert routing["winner"]["route_family"] == "generic_provider"
    assert routing["winner"]["posture"] == "genuine_provider_fallback"
    assert routing["winner"]["provider_fallback_reason"] == "open_ended_reasoning_or_generation"


def test_recent_entity_open_prefers_fresher_candidate_over_stale_one() -> None:
    decision = _plan(
        "open it",
        active_context={
            "recent_entities": [
                {"title": "Old docs", "kind": "page", "url": "https://old.example.com", "freshness": "stale"},
                {"title": "New docs", "kind": "page", "url": "https://new.example.com", "freshness": "current"},
            ]
        },
    )

    routing = _route_state(decision)
    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://new.example.com"
    assert routing["deictic_binding"]["selected_source"] == "recent_session_entity"
    assert routing["deictic_binding"]["selected_target"]["label"] == "New docs"
    assert routing["deictic_binding"]["selected_target"]["freshness"] == "current"


def test_direct_relay_request_refreshes_binding_from_current_selection_over_old_preview() -> None:
    decision = _plan(
        "send this to Baby",
        active_request_state={
            "family": "discord_relay",
            "subject": "Baby",
            "parameters": {
                "destination_alias": "Baby",
                "payload_hint": "page_link",
                "pending_preview": {"preview_id": "relay-preview-1", "route_mode": "local_client_automation"},
            },
            "trust": {"request_id": "trust-1"},
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "Fresh selected text",
                "preview": "Fresh selected text",
            }
        },
    )

    routing = _route_state(decision)
    assert decision.request_type == "discord_relay_dispatch"
    assert decision.structured_query is not None
    assert decision.structured_query.slots["payload_hint"] == "selected_text"
    assert routing["deictic_binding"]["selected_source"] == "selection"
    assert routing["deictic_binding"]["selected_target"]["label"] == "Fresh selected text"


def test_near_tie_winner_stays_honest_about_runner_up_pressure() -> None:
    decision = _plan(
        "open it",
        active_context={
            "recent_entities": [
                {
                    "title": "Stormhelm docs",
                    "kind": "page",
                    "url": "https://docs.example.com/stormhelm",
                }
            ]
        },
    )

    routing = _route_state(decision)
    assert routing["winner"]["route_family"] == "browser_destination"
    assert routing["winner"]["posture"] == "likely_winner"
    assert routing["winner"]["ambiguity_live"] is True
    assert routing["winner"]["runner_up_summary"]["route_family"] == "screen_awareness"
    assert routing["winner"]["margin_to_runner_up"] < 0.1


def test_polite_install_phrase_stays_native_instead_of_provider(temp_config) -> None:
    temp_config.software_control.enabled = True
    temp_config.software_control.planner_routing_enabled = True
    planner = DeterministicPlanner(software_control_config=temp_config.software_control)

    decision = _plan("can you install firefox", planner=planner)

    routing = _route_state(decision)
    assert decision.request_type == "software_control_response"
    assert routing["winner"]["route_family"] == "software_control"
    assert routing["winner"]["provider_fallback_reason"] is None


def test_disabled_software_route_stays_native_unsupported_not_provider_fallback() -> None:
    planner = DeterministicPlanner()
    planner._software_control_seam.config.enabled = False
    planner._software_control_seam.config.planner_routing_enabled = False

    decision = _plan("install firefox", planner=planner)

    routing = _route_state(decision)
    assert decision.request_type == "unsupported_capability"
    assert decision.unsupported_reason is not None
    assert decision.unsupported_reason.code == "software_control_unavailable"
    assert routing["winner"]["route_family"] == "software_control"
    assert routing["winner"]["posture"] == "native_unsupported"
    assert routing["winner"]["provider_fallback_reason"] is None


def test_repair_phrase_routes_to_software_recovery_family() -> None:
    decision = _plan("fix my wifi")

    routing = _route_state(decision)
    assert decision.request_type == "repair_execution"
    assert decision.tool_requests[0].tool_name == "repair_action"
    assert routing["winner"]["route_family"] == "software_recovery"
    assert routing["winner"]["provider_fallback_reason"] is None


def test_continue_where_i_left_off_routes_to_task_continuity_family() -> None:
    decision = _plan("continue where I left off")

    routing = _route_state(decision)
    assert decision.request_type == "workspace_restore"
    assert decision.tool_requests[0].tool_name == "workspace_where_left_off"
    assert routing["winner"]["route_family"] == "task_continuity"
    assert routing["winner"]["provider_fallback_reason"] is None


def test_recent_activity_summary_routes_to_watch_runtime_family() -> None:
    decision = _plan("what did I miss?")

    routing = _route_state(decision)
    assert decision.request_type == "activity_summary"
    assert decision.tool_requests[0].tool_name == "activity_summary"
    assert routing["winner"]["route_family"] == "watch_runtime"
    assert routing["winner"]["provider_fallback_reason"] is None
