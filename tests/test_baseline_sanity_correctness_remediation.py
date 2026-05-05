from __future__ import annotations

import pytest

from scripts.run_baseline_sanity_kraken import build_baseline_corpus
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.route_spine import RouteSpine
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.screen_awareness.observation import NativeContextObservationSource


STALE_SCREEN_CONTEXT = {
    "visible_ui": {
        "label": "Old installer warning",
        "source": "screen",
        "captured_at": "2026-04-30T12:00:00Z",
        "freshness": "stale",
        "evidence_kind": "screen_capture",
    }
}


class SlowWindowProbe:
    def __init__(self) -> None:
        self.calls = 0

    def window_status(self) -> dict:
        self.calls += 1
        return {
            "focused_window": {
                "process_name": "code",
                "window_title": "Should not be observed in baseline command-eval mode",
            }
        }


class FakePreferencesRepository:
    database = None

    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_all(self) -> dict[str, object]:
        return dict(self.values)

    def set_preference(self, key: str, value: object) -> None:
        self.values[key] = value


class FakeMemoryService:
    def __init__(self) -> None:
        self.context_resolution_writes = 0

    def list_recent_session_tool_results(self, *args, **kwargs) -> list[dict[str, object]]:  # noqa: ANN002, ANN003
        return []

    def remember_session_tool_result(self, **kwargs) -> None:  # noqa: ANN003
        return None

    def list_recent_context_resolutions(self, session_id: str) -> list[dict[str, object]]:
        return []

    def remember_context_resolution(self, session_id: str, resolution: dict[str, object]) -> None:
        self.context_resolution_writes += 1

    def list_aliases(self, category: str) -> dict[str, dict[str, object]]:
        return {}

    def remember_alias(self, category: str, alias: str, *, target: dict[str, object]) -> None:
        return None

    def resolve_alias(self, category: str, phrase: str, *, threshold: float = 0.84) -> dict[str, object] | None:
        return None

    def get_learned_preferences(self) -> dict[str, dict[str, object]]:
        return {}

    def remember_preference(self, scope: str, key: str, value: object, *, source_class: str) -> None:
        return None

    def preference_value(self, scope: str, key: str, *, minimum_count: int = 1) -> object | None:
        return None


FAMILY_SUBSYSTEMS = {
    "browser_destination": "browser",
    "context_clarification": "context",
    "file_operation": "files",
    "screen_awareness": "screen_awareness",
    "task_continuity": "workspace",
    "trust_approvals": "trust",
    "web_retrieval": "web_retrieval",
}


def _plan(
    message: str,
    *,
    workspace_context: dict | None = None,
    active_request_state: dict | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="baseline-sanity-correctness-remediation",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=workspace_context or {},
        active_posture={},
        active_request_state=active_request_state or {},
        active_context={},
        recent_tool_results=[],
    )


def _winner(decision):  # noqa: ANN001
    assert decision.route_state is not None
    return decision.route_state.to_dict()["winner"]


def _winner_family(decision) -> str:  # noqa: ANN001
    return str(_winner(decision)["route_family"])


def _winner_subsystem(decision) -> str:  # noqa: ANN001
    if decision.structured_query is not None:
        return str(decision.structured_query.domain or "")
    winner = _winner(decision)
    return str(winner.get("subsystem") or FAMILY_SUBSYSTEMS.get(str(winner["route_family"]), ""))


def _decision_text(decision) -> str:  # noqa: ANN001
    parts: list[str] = []
    if decision.assistant_message:
        parts.append(str(decision.assistant_message))
    if decision.clarification_reason is not None:
        parts.append(str(decision.clarification_reason.message))
    if decision.structured_query is not None:
        slots = decision.structured_query.slots if isinstance(decision.structured_query.slots, dict) else {}
        clarification = slots.get("clarification") if isinstance(slots.get("clarification"), dict) else {}
        if clarification.get("message"):
            parts.append(str(clarification["message"]))
        response_contract = slots.get("response_contract") if isinstance(slots.get("response_contract"), dict) else {}
        for key in ("micro_response", "full_response"):
            if response_contract.get(key):
                parts.append(str(response_contract[key]))
    return "\n".join(parts).lower()


@pytest.mark.parametrize(
    ("prompt", "expected_family", "expected_subsystem"),
    [
        ("Can you verify the warning is gone?", "screen_awareness", "screen_awareness"),
        ("Can you verify it?", "context_clarification", "context"),
        ("reject it", "trust_approvals", "trust"),
        ("confirm that action", "trust_approvals", "trust"),
        ("what does https://example.com say?", "web_retrieval", "web_retrieval"),
        ("get the title of https://example.com", "web_retrieval", "web_retrieval"),
        ("fetch https://example.com", "web_retrieval", "web_retrieval"),
        ("did https://example.com finish loading?", "web_retrieval", "web_retrieval"),
        ("What page is open?", "watch_runtime", "browser"),
        ("Summarize this page.", "context_clarification", "context"),
        ("Find the download button.", "screen_awareness", "screen_awareness"),
        ("Go back to the previous page.", "browser_destination", "browser"),
        ("what was I working on", "task_continuity", "workspace"),
        ("delete my Downloads folder", "file_operation", "files"),
    ],
)
def test_pass_2_failed_prompts_route_to_native_owner(prompt: str, expected_family: str, expected_subsystem: str) -> None:
    decision = _plan(prompt)

    assert _winner_family(decision) == expected_family
    assert _winner_subsystem(decision) == expected_subsystem
    assert _winner_family(decision) != "generic_provider"


def test_stale_visible_screen_context_is_labeled_in_response() -> None:
    decision = _plan("Is the old installer warning still visible?", workspace_context=STALE_SCREEN_CONTEXT)

    assert _winner_family(decision) == "screen_awareness"
    text = _decision_text(decision)
    assert any(token in text for token in ("stale", "previous", "old", "cached", "not current", "last observed"))


def test_generic_verification_question_does_not_bind_to_pending_approval() -> None:
    pending_approval_state = {
        "family": "trust_approvals",
        "subject": "approval request",
        "trust": {"request_id": "approval-1", "reason": "destructive dry-run approval"},
        "parameters": {"request_stage": "awaiting_confirmation", "operation_type": "delete"},
    }

    decision = _plan("Can you verify it?", active_request_state=pending_approval_state)

    assert _winner_family(decision) == "context_clarification"
    assert _winner_subsystem(decision) == "context"


def test_route_spine_fallback_keeps_generic_verify_it_out_of_trust() -> None:
    decision = RouteSpine().route("verify it", active_context={}, active_request_state={}, recent_tool_results=[])

    assert decision.winner.route_family == "context_clarification"
    assert decision.winner.subsystem == "context"


def test_screenshot_currency_prompt_does_not_claim_current_evidence() -> None:
    decision = _plan("Is the screenshot current?")

    assert _winner_family(decision) == "screen_awareness"
    text = _decision_text(decision)
    assert any(token in text for token in ("stale", "previous", "old", "cached", "not current", "last observed"))


def test_recent_files_baseline_expectation_matches_desktop_search_owner() -> None:
    by_id = {item.expectation.case_id: item for item in build_baseline_corpus()}
    expectation = by_id["workspace_04"].expectation

    assert expectation.allowed_route_families == ("desktop_search",)
    assert expectation.expected_subsystem == "workflow"


def test_destructive_downloads_folder_expectation_matches_file_operation_owner() -> None:
    by_id = {item.expectation.case_id: item for item in build_baseline_corpus()}
    expectation = by_id["software_trust_05"].expectation

    assert "file_operation" in expectation.allowed_route_families
    assert expectation.expected_subsystem == "files"


def test_baseline_screen_observation_can_disable_live_window_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = SlowWindowProbe()
    monkeypatch.setenv("STORMHELM_SCREEN_AWARENESS_NATIVE_WINDOW_PROBE_ENABLED", "false")

    observation = NativeContextObservationSource(system_probe=probe).observe(
        session_id="screen-baseline-safe",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={},
        workspace_context={},
    )

    assert probe.calls == 0
    assert observation.window_metadata["focused_window"] == {}
    assert observation.window_metadata["native_window_probe"] == {
        "enabled": False,
        "reason": "native_window_probe_disabled",
    }
    assert any("disabled by policy" in warning for warning in observation.warnings)


def test_command_eval_dry_run_preserves_context_locally_without_semantic_memory_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preferences = FakePreferencesRepository()
    memory = FakeMemoryService()
    state = ConversationStateStore(preferences, memory=memory)
    monkeypatch.setenv("STORMHELM_COMMAND_EVAL_DRY_RUN", "true")

    state.remember_context_resolution(
        "eval-session",
        {
            "kind": "screen_awareness",
            "summary": "No live screen evidence.",
            "analysis_result": {
                "verification_state": "unavailable",
                "observation": {
                    "visual_metadata": {
                        "screen_capture": {
                            "enabled": False,
                            "attempted": False,
                            "captured": False,
                            "reason": "screen_capture_disabled",
                        }
                    },
                    "window_metadata": {"very_large": "x" * 10_000},
                },
            },
        },
    )

    assert memory.context_resolution_writes == 0
    recent = state.get_recent_context_resolutions("eval-session")[0]
    assert recent["kind"] == "screen_awareness"
    assert "window_metadata" not in recent["analysis_result"]["observation"]
    assert recent["analysis_result"]["observation"]["screen_capture"]["reason"] == "screen_capture_disabled"


def test_active_request_state_storage_drops_planner_debug_but_keeps_follow_up_fields() -> None:
    preferences = FakePreferencesRepository()
    state = ConversationStateStore(preferences, memory=FakeMemoryService())

    state.set_active_request_state(
        "software-session",
        {
            "family": "software_control",
            "subject": "Python",
            "parameters": {
                "operation_type": "verify",
                "target_name": "python",
                "request_stage": "prepare_plan",
            },
            "structured_query": {
                "domain": "software_control",
                "query_shape": "software_control_request",
                "requested_action": "verify",
                "slots": {
                    "target_name": "python",
                    "native_decline_reasons": {"browser_destination": ["x"] * 1000},
                },
            },
        },
    )

    stored = state.get_active_request_state("software-session")

    assert stored["family"] == "software_control"
    assert stored["subject"] == "Python"
    assert stored["parameters"]["target_name"] == "python"
    assert stored["structured_query"]["slots"] == {"target_name": "python"}
    assert "native_decline_reasons" not in str(stored)
