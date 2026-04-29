from __future__ import annotations

import json
from pathlib import Path

from stormhelm.core import subsystem_continuations
from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.subsystem_continuations import SubsystemContinuationRegistry
from stormhelm.core.subsystem_continuations import default_subsystem_continuation_registry


def _cases_by_id(case_ids: list[str]):
    corpus = build_command_usability_corpus(min_cases=1000)
    by_id = {case.case_id: case for case in corpus}
    return [by_id[case_id] for case_id in case_ids]


def _run_process_isolated_cases(tmp_path: Path, case_ids: list[str], *, synthetic_block_seconds: float = 0.0):
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=tmp_path,
        per_test_timeout_seconds=1.0 if synthetic_block_seconds else 10.0,
        server_startup_timeout_seconds=10.0,
        synthetic_block_seconds=synthetic_block_seconds,
        process_scope="per_case",
    )
    return harness.run(_cases_by_id(case_ids), results_name="results.jsonl")


def test_handler_status_helper_is_defined_before_registry_uses_it() -> None:
    helper_line = subsystem_continuations._handler_status_for.__code__.co_firstlineno
    registry_line = SubsystemContinuationRegistry.register.__code__.co_firstlineno

    assert helper_line < registry_line


def test_default_continuation_registry_starts_with_handler_statuses() -> None:
    registry = default_subsystem_continuation_registry()
    description = registry.describe("workspace.assemble_deep")

    assert registry.has_handler("workspace.assemble_deep")
    assert description["implemented"] is True
    assert description["handler_name"] == "_run_workspace_assemble"
    assert description["missing_reason"] == ""


def test_process_isolated_startup_routes_affected_power_resource_context_cases(tmp_path: Path) -> None:
    results = _run_process_isolated_cases(
        tmp_path,
        [
            "power_status_canonical_00",
            "resource_status_canonical_00",
            "resource_diagnosis_canonical_00",
            "power_status_ambiguous_00",
        ],
    )

    assert len(results) == 4
    assert (tmp_path / "results.jsonl").exists()
    for result in results:
        row = result.to_dict()
        assert row["hard_timeout"] is False
        assert row["process_killed"] is False
        assert row["routing_engine"] != "legacy_planner"
        assert row["routing_engine"] != "route_spine"
        assert row["actual_route_family"] != "generic_provider"
        assert row["provider_call_count"] == 0
        assert row["openai_call_count"] == 0
        assert row["llm_call_count"] == 0
        assert row["embedding_call_count"] == 0
        assert row["external_action_performed"] is False
        assert row["failure_category"] != "payload_guardrail_failure"


def test_synthetic_blocker_still_writes_durable_hard_timeout_row(tmp_path: Path) -> None:
    results = _run_process_isolated_cases(
        tmp_path,
        ["calculations_canonical_00"],
        synthetic_block_seconds=2.0,
    )
    rows = [
        json.loads(line)
        for line in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(results) == 1
    assert len(rows) == 1
    assert rows[0]["durable_row_written"] is True
    assert rows[0]["hard_timeout"] is True
    assert rows[0]["process_killed"] is True
    assert rows[0]["actual_route_family"] == "hard_timeout"
    assert rows[0]["failure_category"] == "hard_timeout"
