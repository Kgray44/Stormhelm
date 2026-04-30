from __future__ import annotations

from stormhelm.ui.bridge import UiBridge


def test_ui_bridge_surfaces_web_retrieval_compact_ghost_and_evidence_station(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-web-1",
                    "role": "assistant",
                    "content": "Page extracted. I did not verify the source's claims independently.",
                    "created_at": "2026-04-29T12:00:00Z",
                    "metadata": {
                        "bearing_title": "Page Extracted",
                        "micro_response": "Extracted public page evidence from example.com.",
                        "route_state": {
                            "winner": {
                                "route_family": "web_retrieval",
                                "query_shape": "web_retrieval_request",
                                "posture": "clear_winner",
                                "status": "extracted",
                            },
                            "decomposition": {"subject": "https://example.com/docs"},
                        },
                    },
                }
            ],
            "active_request_state": {
                "family": "web_retrieval",
                "subject": "https://example.com/docs",
                "request_type": "web_retrieval_response",
                "query_shape": "web_retrieval_request",
                "parameters": {
                    "request_stage": "extracted",
                    "result_state": "extracted",
                    "evidence_bundle": {
                        "result_state": "extracted",
                        "provider_chain": ["obscura"],
                        "fallback_used": False,
                        "page_count": 1,
                        "link_count": 2,
                        "claim_ceiling": "rendered_page_evidence",
                        "pages": [
                            {
                                "requested_url": "https://example.com/docs",
                                "final_url": "https://example.com/docs",
                                "provider": "obscura",
                                "status": "success",
                                "title": "Example Docs",
                                "text_chars": 4312,
                                "link_count": 2,
                                "elapsed_ms": 321.0,
                                "rendered_javascript": True,
                                "text_preview": "Example docs preview",
                                "html": "<html>must not appear in Ghost</html>",
                                "links": [
                                    {"url": "https://example.com/a", "text": "A"},
                                    {"url": "https://example.com/b", "text": "B"},
                                ],
                            }
                        ],
                        "limitations": ["not_truth_verified", "not_user_visible_screen"],
                    },
                    "trace": {
                        "selected_provider": "obscura",
                        "attempted_providers": ["obscura"],
                        "result_state": "extracted",
                        "claim_ceiling": "rendered_page_evidence",
                    },
                },
            },
        }
    )

    primary = bridge.ghostPrimaryCard
    assert primary["title"] == "Page Extracted"
    assert primary["routeLabel"] == "Web Evidence"
    assert primary["resultState"] == "extracted"
    assert "<html>" not in primary["body"]

    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    station = panels["web-evidence-station"]["stationData"]
    assert station["stationFamily"] == "web_retrieval"
    entries = {
        entry["primary"]: entry
        for section in station["sections"]
        for entry in section["entries"]
    }
    assert entries["Provider"]["secondary"] == "Obscura"
    assert entries["Claim Ceiling"]["secondary"] == "Rendered Page Evidence"
    assert entries["Links"]["secondary"] == "2"
    assert "did not verify" in entries["Limitations"]["detail"].lower()
    assert "verified" not in entries["Limitations"]["detail"].lower()
    assert "i saw your browser" not in str(primary).lower()


def test_ui_bridge_web_retrieval_fallback_and_failure_states_are_truthful(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-web-fallback",
                    "role": "assistant",
                    "content": "Obscura was unavailable, so I used the HTTP fallback.",
                    "created_at": "2026-04-29T12:00:00Z",
                    "metadata": {
                        "bearing_title": "HTTP Fallback Used",
                        "micro_response": "Obscura was unavailable, so I used the HTTP fallback.",
                        "route_state": {
                            "winner": {
                                "route_family": "web_retrieval",
                                "query_shape": "web_retrieval_request",
                                "posture": "clear_winner",
                                "status": "fallback_used",
                            },
                            "decomposition": {"subject": "https://example.com/docs"},
                        },
                    },
                }
            ],
            "active_request_state": {
                "family": "web_retrieval",
                "subject": "https://example.com/docs",
                "request_type": "web_retrieval_response",
                "parameters": {
                    "request_stage": "fallback_used",
                    "result_state": "fallback_used",
                    "evidence_bundle": {
                        "result_state": "extracted",
                        "provider_chain": ["obscura", "http"],
                        "fallback_used": True,
                        "page_count": 1,
                        "link_count": 0,
                        "claim_ceiling": "rendered_page_evidence",
                        "pages": [
                            {
                                "requested_url": "https://example.com/docs",
                                "final_url": "https://example.com/docs",
                                "provider": "http",
                                "status": "success",
                                "title": "Example Docs",
                                "text_chars": 240,
                                "link_count": 0,
                                "elapsed_ms": 120.0,
                                "confidence": "medium",
                                "limitations": ["static_http_only"],
                            }
                        ],
                    },
                    "trace": {
                        "request_id": "web-test",
                        "selected_provider": "http",
                        "attempted_providers": ["obscura", "http"],
                        "fallback_used": True,
                        "fallback_reason": "obscura:binary_missing",
                        "fallback_outcome": "http:success",
                        "result_state": "extracted",
                        "claim_ceiling": "rendered_page_evidence",
                    },
                },
            },
        }
    )

    primary = bridge.ghostPrimaryCard
    assert primary["resultState"] == "fallback_used"
    assert "fallback" in primary["body"].lower()
    assert "completed" not in primary["body"].lower()
    assert "verified" not in primary["body"].lower()

    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    station = panels["web-evidence-station"]["stationData"]
    entries = {
        entry["primary"]: entry
        for section in station["sections"]
        for entry in section["entries"]
    }
    assert entries["Fallback"]["secondary"] == "Used"
    assert entries["Fallback"]["detail"] == "obscura:binary_missing -> http:success"
    assert entries["Attempted Providers"]["secondary"] == "Obscura, Http"


def test_ui_bridge_surfaces_cdp_evidence_without_visible_screen_claims(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [
                {
                    "message_id": "assistant-cdp-1",
                    "role": "assistant",
                    "content": "Headless page inspected. This is not a visible-screen verification.",
                    "created_at": "2026-04-29T12:00:00Z",
                    "metadata": {
                        "bearing_title": "Page Inspected",
                        "micro_response": "Headless page inspected.",
                        "route_state": {
                            "winner": {"route_family": "web_retrieval", "query_shape": "web_retrieval_request", "status": "extracted"},
                            "decomposition": {"subject": "https://example.com/docs"},
                        },
                    },
                }
            ],
            "active_request_state": {
                "family": "web_retrieval",
                "subject": "https://example.com/docs",
                "request_type": "web_retrieval_response",
                "parameters": {
                    "request_stage": "extracted",
                    "result_state": "extracted",
                    "evidence_bundle": {
                        "result_state": "extracted",
                        "provider_chain": ["obscura_cdp"],
                        "fallback_used": False,
                        "page_count": 1,
                        "link_count": 4,
                        "claim_ceiling": "headless_cdp_page_evidence",
                        "pages": [
                            {
                                "requested_url": "https://example.com/docs",
                                "final_url": "https://example.com/docs",
                                "provider": "obscura_cdp",
                                "status": "success",
                                "title": "Example Docs",
                                "text_chars": 2400,
                                "link_count": 4,
                                "load_state": "loaded",
                                "network_summary": {"request_count": 7, "failed_count": 1},
                                "console_summary": {"error_count": 2},
                                "limitations": ["headless_cdp_page_evidence", "not_user_visible_screen", "not_truth_verified"],
                            }
                        ],
                        "limitations": ["headless_cdp_page_evidence", "not_user_visible_screen", "not_truth_verified"],
                    },
                    "trace": {
                        "selected_provider": "obscura_cdp",
                        "attempted_providers": ["obscura_cdp"],
                        "claim_ceiling": "headless_cdp_page_evidence",
                    },
                },
            },
        }
    )

    primary = bridge.ghostPrimaryCard
    assert primary["title"] == "Page Inspected"
    assert primary["routeLabel"] == "Web Evidence"
    assert primary["resultState"] == "extracted"
    assert "clicked" not in str(primary).lower()
    assert "verified" not in str(primary).lower()

    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    station = panels["web-evidence-station"]["stationData"]
    entries = {
        entry["primary"]: entry
        for section in station["sections"]
        for entry in section["entries"]
    }
    assert entries["Provider"]["secondary"] == "Obscura Cdp"
    assert entries["Title"]["secondary"] == "Example Docs"
    assert entries["Load State"]["secondary"] == "Loaded"
    assert entries["Network"]["secondary"] == "7 requests"
    assert entries["Console"]["secondary"] == "2 errors"
    assert entries["Claim Ceiling"]["secondary"] == "Headless Cdp Page Evidence"
    assert "not the user's visible screen" in entries["Limitations"]["detail"].lower()
