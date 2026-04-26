from __future__ import annotations

from pathlib import Path

from stormhelm.core.orchestrator.command_eval import CommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_map
from stormhelm.core.orchestrator.command_eval.models import STAGE_LATENCY_FIELDS
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.registry import ToolRegistry


def test_command_usability_corpus_has_minimum_size_and_core_coverage() -> None:
    corpus = build_command_usability_corpus(min_cases=1000)

    assert len(corpus) >= 1000

    route_families = {case.expected.route_family for case in corpus}
    required_route_families = {
        "calculations",
        "software_control",
        "software_recovery",
        "screen_awareness",
        "discord_relay",
        "trust_approvals",
        "workspace_operations",
        "task_continuity",
        "watch_runtime",
        "browser_destination",
        "desktop_search",
        "workflow",
        "routine",
        "maintenance",
        "file_operation",
        "context_action",
        "system_control",
        "window_control",
        "app_control",
        "weather",
        "location",
        "power",
        "network",
        "resources",
        "storage",
        "machine",
        "generic_provider",
        "unsupported",
    }
    assert required_route_families <= route_families

    registry = ToolRegistry()
    register_builtin_tools(registry)
    built_tools = {tool.name for tool in registry.all_tools()}
    expected_tools = {tool for case in corpus for tool in case.expected.tools}
    assert built_tools <= expected_tools

    tags = {tag for case in corpus for tag in case.tags}
    assert {"canonical", "casual", "typo", "ambiguous", "unsupported", "deictic", "follow_up"} <= tags
    assert any(case.sequence_id for case in corpus)


def test_feature_map_includes_ui_core_boundary_tools_and_adapter_contracts() -> None:
    feature_map = build_feature_map()

    assert feature_map["input_boundary"]["endpoint"] == "POST /chat/send"
    assert "/chat/send" in feature_map["api_routes"]
    assert "/snapshot" in feature_map["api_routes"]
    assert feature_map["tools"]
    assert feature_map["subsystems"]
    assert feature_map["adapter_contracts"]["contracts"]
    assert "bridge_authority" in feature_map["ui_state_surfaces"]


def test_harness_drives_core_chat_boundary_with_safe_dry_run(tmp_path: Path) -> None:
    corpus = [
        case
        for case in build_command_usability_corpus(min_cases=1000)
        if case.case_id
        in {
            "echo_canonical_00",
            "browser_destination_canonical_00",
            "calculations_canonical_00",
        }
    ]
    assert len(corpus) == 3

    harness = CommandUsabilityHarness(output_dir=tmp_path, per_test_timeout_seconds=120)
    assert harness.per_test_timeout_seconds == 60.0
    results = harness.run(corpus)

    assert all(result.observation.input_boundary == "POST /chat/send" for result in results)
    assert all(result.observation.latency_ms >= 0 for result in results)
    assert all(result.observation.ui_response for result in results)
    for result in results:
        row = result.to_dict()
        for field in STAGE_LATENCY_FIELDS:
            assert field in row
            assert row[field] >= 0

    browser_result = next(result for result in results if result.case.case_id == "browser_destination_canonical_00")
    assert browser_result.observation.tool_chain == ("external_open_url",)
    assert browser_result.observation.tool_results[0]["data"]["dry_run"] is True
    assert "No external action was performed" in browser_result.observation.tool_results[0]["summary"]
    assert browser_result.assertions["route_family"].passed
    assert browser_result.assertions["tool_chain"].passed

    assert (tmp_path / "focused_results.jsonl").exists()
    assert (tmp_path / "focused_results.checkpoint.json").exists()
    assert len((tmp_path / "focused_results.jsonl").read_text(encoding="utf-8").splitlines()) == 3

    resumed_results = harness.run(corpus, resume=True)

    assert len(resumed_results) == 3
    assert len((tmp_path / "focused_results.jsonl").read_text(encoding="utf-8").splitlines()) == 3

    summary = build_checkpoint_summary(results)
    assert "raw_failure_category_counts" in summary
    assert "scored_failure_category_counts" in summary
    assert "excluded_category_counts" in summary
