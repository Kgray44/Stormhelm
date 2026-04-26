from __future__ import annotations

from stormhelm.core.orchestrator.intent_frame import IntentFrameExtractor


def _extract(message: str, *, active_context: dict[str, object] | None = None):
    return IntentFrameExtractor().extract(
        message,
        active_context=active_context or {},
        active_request_state={},
        recent_tool_results=[],
    )


def test_intent_frame_extracts_core_operation_target_and_risk() -> None:
    cases = [
        ("what is 7 * 8", "question", "calculate", "unknown", "read_only"),
        ("open https://example.com/status", "command", "open", "url", "external_browser_open"),
        (r"read C:\Stormhelm\README.md", "command", "inspect", "file", "read_only"),
        ("quit Notepad", "command", "quit", "app", "external_app_open"),
        ("install Slack", "command", "install", "software_package", "software_lifecycle"),
        ("which wifi am I on", "status_check", "status", "system_resource", "read_only"),
    ]
    for prompt, speech_act, operation, target_type, risk_class in cases:
        frame = _extract(prompt)

        assert frame.speech_act == speech_act, prompt
        assert frame.operation == operation, prompt
        assert frame.target_type == target_type, prompt
        assert frame.risk_class == risk_class, prompt
        assert frame.generic_provider_allowed is False, prompt


def test_intent_frame_marks_deictic_context_status() -> None:
    missing = _extract("open that website")

    assert missing.operation == "open"
    assert missing.target_type == "website"
    assert missing.context_reference == "that"
    assert missing.context_status == "missing"
    assert missing.clarification_needed is True
    assert missing.native_owner_hint == "browser_destination"

    available = _extract(
        "open that website",
        active_context={
            "recent_entities": [
                {
                    "kind": "page",
                    "title": "Stormhelm docs",
                    "url": "https://docs.example.com/stormhelm",
                    "freshness": "current",
                }
            ]
        },
    )

    assert available.context_status == "available"
    assert available.target_type == "website"
    assert available.extracted_entities["selected_context"]["value"] == "https://docs.example.com/stormhelm"


def test_intent_frame_rejects_conceptual_near_misses() -> None:
    neural = _extract("which neural network architecture is better")

    assert neural.speech_act == "comparison"
    assert neural.operation == "compare"
    assert neural.target_type == "unknown"
    assert neural.native_owner_hint is None
    assert neural.generic_provider_allowed is True

    selection_concept = _extract("what is selected text in HTML")

    assert selection_concept.operation == "explain"
    assert selection_concept.target_type == "unknown"
    assert selection_concept.native_owner_hint is None
    assert selection_concept.generic_provider_allowed is True

