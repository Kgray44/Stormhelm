from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from stormhelm.core.orchestrator.command_eval import CommandEvalCase
from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_audit
from stormhelm.core.orchestrator.command_eval import build_feature_map
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl

from run_latency_micro_suite import build_latency_micro_cases


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "routine-save-repro"
RESULTS_NAME = "routine_save_repro_results.jsonl"
SUMMARY_NAME = "routine_save_repro_summary.json"
REPORT_NAME = "routine_save_reproduction_report.md"
MATRIX_NAME = "routine_save_native_vs_fallback_matrix.json"
OLD_CASES_NAME = "recovered_old_routine_save_cases.json"
OLD_MICRO_DIR = Path(".artifacts") / "command-usability-eval" / "latency-micro-20260424-225838"
INTERRUPTED_MICRO_DIR = Path(".artifacts") / "command-usability-eval" / "latency-micro-instrumented-20260424-232011"


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    cases: tuple[CommandEvalCase, ...]
    history_strategy: str
    process_scope: str
    runtime_seed_label: str
    runtime_seed_dir: Path | None
    dimensions: dict[str, Any]
    prefix_search: bool = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce the old routine_save native-route latency under hard timeout.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--native-repetitions", type=int, default=3)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    preserve_dir = _preserve_inputs(args.output_dir)

    corpus = build_command_usability_corpus(min_cases=1000)
    case_lookup = {case.case_id: case for case in corpus}
    old_micro_cases = build_latency_micro_cases(case_lookup, repeats=5)
    old_evidence_rows = _old_native_routine_save_rows(OLD_MICRO_DIR / "latency_micro_results.jsonl")
    recovered_cases = _recover_old_routine_save_cases(case_lookup, old_micro_cases, old_evidence_rows)
    write_json(args.output_dir / OLD_CASES_NAME, recovered_cases)

    scenarios = _build_reproduction_matrix(case_lookup, old_micro_cases, old_evidence_rows)
    write_json(args.output_dir / "feature_map.json", build_feature_map())
    write_json(args.output_dir / "feature_map_audit.json", build_feature_audit([case for scenario in scenarios for case in scenario.cases]))
    write_jsonl(args.output_dir / "routine_save_reproduction_corpus.jsonl", [_scenario_case_row(scenario, case) for scenario in scenarios for case in scenario.cases])

    aggregate_rows: list[dict[str, Any]] = []
    scenario_summaries: list[dict[str, Any]] = []
    first_native_scenario: Scenario | None = None
    first_native_rows: list[dict[str, Any]] = []
    repeat_source_scenario: Scenario | None = None
    prefix_native_reproduced = False

    for scenario in scenarios:
        if scenario.prefix_search and prefix_native_reproduced:
            scenario_summaries.append(_skipped_scenario_summary(scenario, "earlier_prefix_reproduced_native_routine_save"))
            continue
        result_rows = _run_scenario(
            scenario,
            output_dir=args.output_dir,
            timeout_seconds=args.timeout_seconds,
            server_startup_timeout_seconds=args.server_startup_timeout_seconds,
        )
        aggregate_rows.extend(result_rows)
        _write_repro_results(args.output_dir, aggregate_rows)
        summary = _scenario_summary(scenario, result_rows)
        scenario_summaries.append(summary)
        native_rows = [row for row in result_rows if _is_routine_save_attempt(row) and row.get("actual_route_family") == "routine"]
        if native_rows and first_native_scenario is None:
            first_native_scenario = scenario
            first_native_rows = native_rows
        if any(_routine_save_classification(row) in {"native_routine_save_reproduced_slow", "native_routine_save_hard_timeout"} for row in native_rows):
            repeat_source_scenario = repeat_source_scenario or scenario
        if scenario.prefix_search and any(_routine_save_classification(row) in {"native_routine_save_reproduced_slow", "native_routine_save_hard_timeout"} for row in native_rows):
            prefix_native_reproduced = True

    repeat_rows: list[dict[str, Any]] = []
    if repeat_source_scenario is None:
        repeat_source_scenario = first_native_scenario
    if repeat_source_scenario is not None and args.native_repetitions > 0:
        repeat_scenarios = _build_native_repeat_scenarios(repeat_source_scenario, repetitions=max(1, min(5, args.native_repetitions)))
        for scenario in repeat_scenarios:
            result_rows = _run_scenario(
                scenario,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout_seconds,
                server_startup_timeout_seconds=args.server_startup_timeout_seconds,
            )
            repeat_rows.extend(result_rows)
            aggregate_rows.extend(result_rows)
            _write_repro_results(args.output_dir, aggregate_rows)
            scenario_summaries.append(_scenario_summary(scenario, result_rows))

    orphan_check = _orphan_process_check_result()
    aggregate_rows = _finalize_rows(aggregate_rows, orphan_check=orphan_check, output_dir=args.output_dir)
    diagnostics_rows = [row for row in aggregate_rows if _is_routine_save_attempt(row)]
    _write_repro_results(args.output_dir, aggregate_rows)
    write_jsonl(args.output_dir / "routine_save_reproduction_diagnostics.jsonl", diagnostics_rows)
    native_vs_fallback = _native_vs_fallback_matrix(diagnostics_rows)
    write_json(args.output_dir / MATRIX_NAME, native_vs_fallback)

    summary = _build_summary(
        rows=aggregate_rows,
        scenario_summaries=scenario_summaries,
        old_evidence_rows=old_evidence_rows,
        first_native_rows=first_native_rows,
        repeat_rows=repeat_rows,
        preserve_dir=preserve_dir,
        output_dir=args.output_dir,
        timeout_seconds=args.timeout_seconds,
        recovered_cases=recovered_cases,
        native_vs_fallback=native_vs_fallback,
        orphan_check=orphan_check,
    )
    write_json(args.output_dir / SUMMARY_NAME, summary)
    (args.output_dir / REPORT_NAME).write_text(
        _build_report(summary),
        encoding="utf-8",
    )

    print(f"{RESULTS_NAME}: {args.output_dir / RESULTS_NAME}")
    print(f"{SUMMARY_NAME}: {args.output_dir / SUMMARY_NAME}")
    print(f"{REPORT_NAME}: {args.output_dir / REPORT_NAME}")


def _preserve_inputs(output_dir: Path) -> Path:
    preserve_dir = output_dir / "preserved_inputs"
    preserve_dir.mkdir(parents=True, exist_ok=True)
    copies = {
        "hard_timeout_proof_summary.json": Path(".artifacts") / "command-usability-eval" / "hard-timeout-proof-20260425-024110" / "hard_timeout_proof_summary.json",
        "latency_attribution_tiny_report.md": Path(".artifacts") / "command-usability-eval" / "latency-attribution-tiny-batch-20260425-024522" / "latency_attribution_tiny_report.md",
        "harness_hardening_report.md": Path(".artifacts") / "command-usability-eval" / "harness-hardening-20260425-024729" / "harness_hardening_report.md",
        "old_latency_triage_report.md": OLD_MICRO_DIR / "latency_triage_report.md",
        "old_latency_micro_results.jsonl": OLD_MICRO_DIR / "latency_micro_results.jsonl",
        "interrupted_latency_micro_results.jsonl": INTERRUPTED_MICRO_DIR / "latency_micro_results.jsonl",
    }
    for name, source in copies.items():
        if source.exists():
            (preserve_dir / name).write_bytes(source.read_bytes())
    return preserve_dir


def _recover_old_routine_save_cases(
    case_lookup: dict[str, CommandEvalCase],
    old_micro_cases: list[CommandEvalCase],
    old_evidence_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    old_row_by_id = {str(row.get("test_id") or ""): row for row in old_evidence_rows}
    old_order = [case.case_id for case in old_micro_cases]
    first_index = next((index for index, case_id in enumerate(old_order) if case_id.startswith("routine_save_")), -1)
    recovered: list[dict[str, Any]] = []
    wanted_prefixes = ("routine_save_canonical_00", "routine_save_command_mode_00")
    for index, case in enumerate(old_micro_cases):
        if not case.case_id.startswith(wanted_prefixes):
            continue
        source_case_id = case.case_id.rsplit("_rep", 1)[0]
        old_row = old_row_by_id.get(case.case_id, {})
        recovered.append(
            {
                "test_id": case.case_id,
                "source_case_id": source_case_id,
                "prompt_input_text": old_row.get("input") or case.message,
                "expected_route_family": case.expected.route_family,
                "expected_subsystem": case.expected.subsystem,
                "expected_tool": list(case.expected.tools),
                "corpus_metadata": case.to_dict(),
                "mode_label": "command_mode" if "command_mode" in case.case_id else "canonical",
                "session_strategy_used_in_old_run": str(old_row.get("history_strategy") or "isolated_session"),
                "old_session_id": old_row.get("session_id"),
                "case_ordering_index_zero_based": index,
                "case_ordering_index_one_based": index + 1,
                "previous_case_count_before_this_case": index,
                "old_actual_route_family": old_row.get("actual_route_family"),
                "old_actual_subsystem": old_row.get("actual_subsystem"),
                "old_actual_tool": old_row.get("actual_tool"),
                "old_total_latency_ms": old_row.get("total_latency_ms"),
                "old_route_handler_ms": old_row.get("route_handler_ms"),
                "old_response_serialization_ms": old_row.get("response_serialization_ms"),
                "old_provider_called": old_row.get("provider_called"),
                "old_external_action_performed": old_row.get("external_action_performed"),
            }
        )
    return {
        "recovered_at": datetime.now().isoformat(),
        "old_micro_suite_dir": str(OLD_MICRO_DIR),
        "old_results_path": str(OLD_MICRO_DIR / "latency_micro_results.jsonl"),
        "old_runtime_db_path": str(OLD_MICRO_DIR / "runtime" / "stormhelm.db"),
        "old_runtime_dir": str(OLD_MICRO_DIR / "runtime"),
        "old_checkpoint_paths": [str(path) for path in OLD_MICRO_DIR.glob("*checkpoint*.json")],
        "old_micro_case_count": len(old_micro_cases),
        "first_routine_save_index_zero_based": first_index,
        "previous_cases_before_first_routine_save": old_order[:first_index] if first_index >= 0 else [],
        "recovered_cases": recovered,
        "available_source_case_definitions": {
            case_id: case_lookup[case_id].to_dict()
            for case_id in ("routine_save_canonical_00", "routine_save_command_mode_00")
            if case_id in case_lookup
        },
    }


def _build_reproduction_matrix(
    case_lookup: dict[str, CommandEvalCase],
    old_micro_cases: list[CommandEvalCase],
    old_evidence_rows: list[dict[str, Any]],
) -> list[Scenario]:
    old_runtime = OLD_MICRO_DIR / "runtime"
    scenarios: list[Scenario] = []
    canonical = case_lookup["routine_save_canonical_00"]
    command = case_lookup["routine_save_command_mode_00"]
    old_first_session_id = _old_session_id(old_evidence_rows, "routine_save_canonical_00_rep01")

    for source, label in ((canonical, "canonical"), (command, "command_mode")):
        scenarios.extend(
            [
                _single_target_scenario(
                    source,
                    name=f"clean_isolated_per_case_no_active_{label}",
                    runtime_seed_label="clean",
                    runtime_seed_dir=None,
                    active_mode="cleared",
                    process_scope="per_case",
                    history_strategy="isolated_session",
                ),
                _single_target_scenario(
                    source,
                    name=f"clean_isolated_per_case_exact_active_{label}",
                    runtime_seed_label="clean",
                    runtime_seed_dir=None,
                    active_mode="exact_old_metadata",
                    process_scope="per_case",
                    history_strategy="isolated_session",
                ),
            ]
        )

    scenarios.extend(
        [
            _single_target_scenario(
                canonical,
                name="oldseed_isolated_per_case_no_active_canonical",
                runtime_seed_label="copied_old_runtime",
                runtime_seed_dir=old_runtime,
                active_mode="cleared",
                process_scope="per_case",
                history_strategy="isolated_session",
            ),
            _single_target_scenario(
                canonical,
                name="oldseed_isolated_per_case_exact_active_canonical",
                runtime_seed_label="copied_old_runtime",
                runtime_seed_dir=old_runtime,
                active_mode="exact_old_metadata",
                process_scope="per_case",
                history_strategy="isolated_session",
            ),
            _sequence_scenario(
                sources=(case_lookup["routine_execute_canonical_00"], canonical),
                name="clean_shared_per_run_prior_routine_execute_no_active",
                runtime_seed_label="clean",
                runtime_seed_dir=None,
                target_active_mode="cleared",
            ),
            _sequence_scenario(
                sources=(case_lookup["workspace_save_canonical_00"], canonical),
                name="clean_shared_per_run_prior_workspace_save_no_active",
                runtime_seed_label="clean",
                runtime_seed_dir=None,
                target_active_mode="cleared",
            ),
            _sequence_scenario(
                sources=(case_lookup["maintenance_canonical_00"], canonical),
                name="clean_shared_per_run_prior_maintenance_no_active",
                runtime_seed_label="clean",
                runtime_seed_dir=None,
                target_active_mode="cleared",
            ),
            _sequence_scenario(
                sources=(case_lookup["workspace_assemble_canonical_00"], case_lookup["workspace_save_canonical_00"], case_lookup["maintenance_canonical_00"], case_lookup["routine_execute_canonical_00"], canonical),
                name="clean_shared_per_run_setup_stack_no_active",
                runtime_seed_label="clean",
                runtime_seed_dir=None,
                target_active_mode="cleared",
            ),
            _sequence_scenario(
                sources=(case_lookup["maintenance_canonical_00"], canonical),
                name="oldseed_shared_per_run_prior_maintenance_no_active",
                runtime_seed_label="copied_old_runtime",
                runtime_seed_dir=old_runtime,
                target_active_mode="cleared",
            ),
        ]
    )
    if old_first_session_id:
        scenarios.extend(
            [
                _single_target_scenario(
                    replace(canonical, session_id=old_first_session_id),
                    name="oldseed_old_session_id_no_active_canonical",
                    runtime_seed_label="copied_old_runtime",
                    runtime_seed_dir=old_runtime,
                    active_mode="cleared",
                    process_scope="per_case",
                    history_strategy="shared_session",
                ),
                _single_target_scenario(
                    replace(canonical, session_id=old_first_session_id),
                    name="oldseed_old_session_id_exact_active_canonical",
                    runtime_seed_label="copied_old_runtime",
                    runtime_seed_dir=old_runtime,
                    active_mode="exact_old_metadata",
                    process_scope="per_case",
                    history_strategy="shared_session",
                ),
            ]
        )

    target_index = next(index for index, case in enumerate(old_micro_cases) if case.case_id == "routine_save_canonical_00_rep01")
    target = old_micro_cases[target_index]
    for prefix_size in (0, 5, 10, 20):
        prefix = tuple(old_micro_cases[:prefix_size])
        scenarios.append(
            _sequence_scenario(
                sources=(*prefix, target),
                name=f"prefix_first_{prefix_size}_before_routine_save",
                runtime_seed_label="clean",
                runtime_seed_dir=None,
                target_active_mode="exact_old_metadata",
                prefix_search=True,
            )
        )
    return scenarios


def _single_target_scenario(
    source: CommandEvalCase,
    *,
    name: str,
    runtime_seed_label: str,
    runtime_seed_dir: Path | None,
    active_mode: str,
    process_scope: str,
    history_strategy: str,
) -> Scenario:
    case = _clone_case(source, scenario_name=name, index=0, session_id=f"session-{name}", active_mode=active_mode)
    return Scenario(
        name=name,
        cases=(case,),
        history_strategy=history_strategy,
        process_scope=process_scope,
        runtime_seed_label=runtime_seed_label,
        runtime_seed_dir=runtime_seed_dir if runtime_seed_dir and runtime_seed_dir.exists() else None,
        dimensions={
            "runtime_db": runtime_seed_label,
            "session": "isolated" if history_strategy == "isolated_session" else "reused",
            "process": process_scope,
            "prior_routine_execute": False,
            "prior_workspace_save": False,
            "prior_setup_requests": [],
            "target_active_request_state": active_mode,
            "prompt_source": source.case_id,
        },
    )


def _sequence_scenario(
    *,
    sources: tuple[CommandEvalCase, ...],
    name: str,
    runtime_seed_label: str,
    runtime_seed_dir: Path | None,
    target_active_mode: str,
    prefix_search: bool = False,
) -> Scenario:
    session_id = f"session-{name}"
    cloned: list[CommandEvalCase] = []
    last_index = len(sources) - 1
    for index, source in enumerate(sources):
        active_mode = target_active_mode if index == last_index and source.expected.route_family == "routine" and "routine_save" in source.expected.tools else "source"
        cloned.append(_clone_case(source, scenario_name=name, index=index, session_id=session_id, active_mode=active_mode))
    prior_ids = [source.case_id for source in sources[:-1]]
    return Scenario(
        name=name,
        cases=tuple(cloned),
        history_strategy="shared_session",
        process_scope="per_run",
        runtime_seed_label=runtime_seed_label,
        runtime_seed_dir=runtime_seed_dir if runtime_seed_dir and runtime_seed_dir.exists() else None,
        dimensions={
            "runtime_db": runtime_seed_label,
            "session": "reused",
            "process": "small_batch_per_process",
            "prior_routine_execute": any("routine_execute" in source.case_id for source in sources[:-1]),
            "prior_workspace_save": any("workspace_save" in source.case_id for source in sources[:-1]),
            "prior_setup_requests": prior_ids,
            "target_active_request_state": target_active_mode,
            "prompt_source": sources[-1].case_id,
        },
        prefix_search=prefix_search,
    )


def _clone_case(
    source: CommandEvalCase,
    *,
    scenario_name: str,
    index: int,
    session_id: str,
    active_mode: str,
) -> CommandEvalCase:
    if active_mode == "cleared":
        active_request_state: dict[str, Any] = {}
    else:
        active_request_state = dict(source.active_request_state)
    return replace(
        source,
        case_id=f"{scenario_name}_{index:02d}_{source.case_id}",
        session_id=session_id,
        active_request_state=active_request_state,
        tags=tuple(dict.fromkeys((*source.tags, "routine_save_repro", active_mode))),
        notes=f"Routine save reproduction scenario {scenario_name}; source case {source.case_id}.",
    )


def _run_scenario(
    scenario: Scenario,
    *,
    output_dir: Path,
    timeout_seconds: float,
    server_startup_timeout_seconds: float,
) -> list[dict[str, Any]]:
    scenario_dir = output_dir / "scenarios" / scenario.name
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=scenario_dir,
        per_test_timeout_seconds=timeout_seconds,
        history_strategy=scenario.history_strategy,
        server_startup_timeout_seconds=server_startup_timeout_seconds,
        process_scope="per_run" if scenario.process_scope in {"per_run", "small_batch_per_process"} else "per_case",
        runtime_seed_dir=scenario.runtime_seed_dir,
    )
    results = harness.run(list(scenario.cases), results_name="results.jsonl")
    rows = []
    for result in results:
        row = result.to_dict()
        row["scenario_name"] = scenario.name
        row["scenario_label"] = scenario.name
        row["scenario_dimensions"] = scenario.dimensions
        row["reproduction_dimension_summary"] = scenario.dimensions
        row["runtime_seed_label"] = scenario.runtime_seed_label
        row["runtime_seed_dir"] = str(scenario.runtime_seed_dir or "")
        row["scenario_result_path"] = str(scenario_dir / "results.jsonl")
        row["process_isolated"] = True
        row["hard_timeout_seconds"] = timeout_seconds
        row["prompt"] = row.get("input", "")
        row["old_case_source"] = _old_case_source(row, scenario)
        row.update(_routine_save_diagnostics(row, scenario))
        row.update(_generic_row_diagnostics(row))
        row["routine_save_repro_classification"] = _routine_save_classification(row)
        rows.append(row)
    return rows


def _routine_save_diagnostics(row: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    if not _is_routine_save_attempt(row):
        return {}
    planner_debug = _planner_debug(row)
    route_state = row.get("route_state") if isinstance(row.get("route_state"), dict) else {}
    semantic = planner_debug.get("semantic_parse_proposal") if isinstance(planner_debug.get("semantic_parse_proposal"), dict) else {}
    structured = planner_debug.get("structured_query") if isinstance(planner_debug.get("structured_query"), dict) else {}
    execution_plan = planner_debug.get("execution_plan") if isinstance(planner_debug.get("execution_plan"), dict) else {}
    slots = structured.get("slots") if isinstance(structured.get("slots"), dict) else {}
    if not slots and isinstance(semantic.get("slots"), dict):
        slots = semantic.get("slots") or {}
    tool_args = execution_plan.get("tool_arguments") if isinstance(execution_plan.get("tool_arguments"), dict) else {}
    if not tool_args and isinstance(slots.get("tool_arguments"), dict):
        tool_args = slots.get("tool_arguments") or {}
    deictic_binding = route_state.get("deictic_binding") if isinstance(route_state.get("deictic_binding"), dict) else {}
    normalized = route_state.get("normalized_summary") if isinstance(route_state.get("normalized_summary"), dict) else {}
    if not normalized and isinstance(planner_debug.get("normalized_command"), dict):
        normalized = planner_debug.get("normalized_command") or {}
    case_payload = row.get("case") if isinstance(row.get("case"), dict) else {}
    active_state = case_payload.get("active_request_state") if isinstance(case_payload.get("active_request_state"), dict) else {}
    raw_tokens = normalized.get("tokens") if isinstance(normalized.get("tokens"), list) else []
    tokens = {str(item).lower() for item in raw_tokens}
    missing_preconditions = []
    if "this" in tokens and not deictic_binding.get("resolved"):
        missing_preconditions.append(str(deictic_binding.get("unresolved_reason") or "unresolved_deictic_reference"))
    if not active_state and scenario.dimensions.get("target_active_request_state") == "cleared":
        missing_preconditions.append("no_seeded_active_request_state")
    registry_summary = _routine_registry_state_summary(row, scenario)
    extracted_target = {
        "execution_kind": tool_args.get("execution_kind"),
        "parameters": tool_args.get("parameters"),
        "subject": execution_plan.get("subject") or slots.get("subject"),
    }
    return {
        "native_routine_matcher_inputs": {
            "normalized_text": normalized.get("normalized_text"),
            "tokens": normalized.get("tokens"),
            "active_request_state": active_state,
            "deictic_binding": deictic_binding,
            "request_decomposition": route_state.get("decomposition"),
        },
        "extracted_routine_intent": semantic.get("requested_action") or structured.get("requested_action") or execution_plan.get("plan_type"),
        "extracted_routine_name": tool_args.get("routine_name"),
        "extracted_routine_target": extracted_target,
        "extracted_action": _routine_action(semantic, structured, execution_plan, row),
        "extracted_routine_action": _routine_action(semantic, structured, execution_plan, row),
        "extracted_routine_name_or_target": tool_args.get("routine_name") or extracted_target,
        "extracted_entities": {
            "slots": slots,
            "tool_arguments": tool_args,
            "target_slots": row.get("target_slots") or {},
        },
        "missing_preconditions": missing_preconditions,
        "handler_selected": ",".join(row.get("actual_tool") or ()) or str(row.get("actual_route_family") or ""),
        "selected_handler": ",".join(row.get("actual_tool") or ()) or str(row.get("actual_route_family") or ""),
        "routine_save_tool_selected": "routine_save" in set(row.get("actual_tool") or ()),
        "prior_turns_in_session": scenario.dimensions.get("prior_setup_requests") or [],
        "session_state_summary": active_state,
        "runtime_db_state_summary": {
            "seed": scenario.runtime_seed_label,
            "seed_dir": str(scenario.runtime_seed_dir or ""),
        },
        **registry_summary,
    }


def _routine_action(
    semantic: dict[str, Any],
    structured: dict[str, Any],
    execution_plan: dict[str, Any],
    row: dict[str, Any],
) -> str:
    action = str(semantic.get("requested_action") or structured.get("requested_action") or execution_plan.get("request_type") or "").lower()
    if "save" in action:
        return "save"
    if "execute" in action or "run" in action:
        return "execute"
    tools = set(row.get("actual_tool") or ())
    if "routine_save" in tools:
        return "save"
    if "routine_execute" in tools:
        return "execute"
    return "unknown"


def _generic_row_diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    route_state = row.get("route_state") if isinstance(row.get("route_state"), dict) else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    subspans = row.get("route_handler_subspans") if isinstance(row.get("route_handler_subspans"), dict) else {}
    case_payload = row.get("case") if isinstance(row.get("case"), dict) else {}
    active_state = case_payload.get("active_request_state") if isinstance(case_payload.get("active_request_state"), dict) else {}
    diagnostics = {
        "provider_fallback_reason": winner.get("provider_fallback_reason") or row.get("fallback_reason") or "",
        "trust_state": active_state.get("trust") if isinstance(active_state.get("trust"), dict) else {},
        "result_field_count": int(row.get("serialized_result_field_count") or len(row)),
        "payload_field_count": len(row.get("observation") or {}) if isinstance(row.get("observation"), dict) else 0,
        "largest_payload_fields": _largest_payload_fields(row),
        "routine_lookup_ms": float(subspans.get("routine_lookup_ms") or 0.0),
        "routine_match_ms": float(subspans.get("routine_match_ms") or 0.0),
        "routine_persistence_read_ms": float(subspans.get("routine_persistence_read_ms") or 0.0),
        "routine_persistence_write_ms": float(subspans.get("routine_persistence_write_ms") or 0.0),
        "routine_job_create_ms": float(subspans.get("routine_job_create_ms") or 0.0),
        "routine_job_wait_ms": float(subspans.get("routine_job_wait_ms") or 0.0),
        "routine_event_emit_ms": float(subspans.get("routine_event_emit_ms") or 0.0),
        "routine_dto_build_ms": float(subspans.get("routine_dto_build_ms") or 0.0),
        "routine_response_build_ms": float(subspans.get("routine_response_build_ms") or 0.0),
        "routine_background_task_drain_ms": float(subspans.get("routine_background_task_drain_ms") or 0.0),
    }
    return diagnostics


def _largest_payload_fields(row: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    sizes: list[dict[str, Any]] = []
    for key, value in row.items():
        if key in {"stdout_tail", "stderr_tail"}:
            continue
        try:
            size = len(json.dumps(value, sort_keys=True, default=str))
        except (TypeError, ValueError):
            size = len(str(value))
        sizes.append({"field": key, "bytes": size})
    return sorted(sizes, key=lambda item: int(item["bytes"]), reverse=True)[:limit]


def _routine_registry_state_summary(row: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    scenario_path = Path(str(row.get("scenario_result_path") or "")).parent
    registry_paths = sorted(scenario_path.glob("runtime/**/power/registry.json"))
    routines: list[dict[str, Any]] = []
    registry_state = "registry_absent"
    for registry_path in registry_paths:
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            registry_state = "registry_unreadable"
            continue
        for item in payload.get("routines") or []:
            if isinstance(item, dict):
                routines.append(item)
        registry_state = "registry_present"
    name = str(row.get("extracted_routine_name") or "cleanup").lower()
    matches = [
        {
            "name": item.get("name"),
            "title": item.get("title"),
            "execution_kind": item.get("execution_kind"),
        }
        for item in routines
        if name and name in str(item.get("name") or item.get("title") or "").lower()
    ]
    route_state = row.get("route_state") if isinstance(row.get("route_state"), dict) else {}
    deictic = route_state.get("deictic_binding") if isinstance(route_state.get("deictic_binding"), dict) else {}
    case_payload = row.get("case") if isinstance(row.get("case"), dict) else {}
    active_state = case_payload.get("active_request_state") if isinstance(case_payload.get("active_request_state"), dict) else {}
    return {
        "routine_registry_state_summary": {
            "registry_files": [str(path) for path in registry_paths],
            "state": registry_state,
            "runtime_seed": scenario.runtime_seed_label,
        },
        "routine_count": len(routines),
        "matching_routine_candidates": matches,
        "routine_storage_path": str(registry_paths[0]) if registry_paths else str((scenario_path / "runtime" / "<child>" / "power" / "registry.json")),
        "routine_persistence_state": registry_state,
        "routine_context_available": bool(deictic.get("resolved")) or bool(active_state),
        "prior_routine_turns_count": sum(1 for item in scenario.dimensions.get("prior_setup_requests") or [] if "routine" in str(item)),
        "prior_workspace_turns_count": sum(1 for item in scenario.dimensions.get("prior_setup_requests") or [] if "workspace" in str(item)),
    }


def _routine_save_classification(row: dict[str, Any]) -> str:
    if row.get("status") == "hard_timeout":
        if row.get("expected_route_family") == "routine":
            return "native_routine_save_hard_timeout"
        return "harness_failure"
    if row.get("actual_route_family") == "harness_error":
        return "harness_failure"
    if not _is_routine_save_attempt(row):
        return "inconclusive"
    actual_tools = set(row.get("actual_tool") or ())
    native = row.get("actual_route_family") == "routine" and "routine_save" in actual_tools and not row.get("provider_called")
    if native:
        latency = float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0)
        return "native_routine_save_reproduced_slow" if latency >= 10000.0 else "native_routine_save_reproduced_fast"
    if row.get("actual_route_family") == "generic_provider":
        return "generic_provider_fallback"
    if row.get("actual_route_family"):
        return "wrong_native_route"
    return "inconclusive"


def _planner_debug(row: dict[str, Any]) -> dict[str, Any]:
    observation = row.get("observation") if isinstance(row.get("observation"), dict) else {}
    planner_debug = observation.get("planner_debug") if isinstance(observation.get("planner_debug"), dict) else {}
    if planner_debug:
        return planner_debug
    return row.get("planner_debug") if isinstance(row.get("planner_debug"), dict) else {}


def _is_routine_save_attempt(row: dict[str, Any]) -> bool:
    expected_tools = set(row.get("expected_tool") or ())
    input_text = str(row.get("input") or "").lower()
    return "routine_save" in expected_tools or "save this as a routine" in input_text


def _scenario_summary(scenario: Scenario, rows: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = [row for row in rows if _is_routine_save_attempt(row)]
    return {
        "scenario_name": scenario.name,
        "dimensions": scenario.dimensions,
        "completed_requests": len(rows),
        "durable_rows": _line_count(Path(rows[0]["scenario_result_path"])) if rows else 0,
        "routine_save_attempts": len(attempts),
        "actual_routes": dict(Counter(str(row.get("actual_route_family") or "") for row in attempts)),
        "actual_tools": dict(Counter(",".join(row.get("actual_tool") or ()) or "<none>" for row in attempts)),
        "provider_calls": sum(1 for row in rows if row.get("provider_called")),
        "external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout"),
        "latency_ms": _stats([float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0) for row in attempts]),
    }


def _old_case_source(row: dict[str, Any], scenario: Scenario) -> str:
    prompt_source = str(scenario.dimensions.get("prompt_source") or "")
    if prompt_source:
        return prompt_source
    test_id = str(row.get("test_id") or "")
    for marker in ("routine_save_canonical_00", "routine_save_command_mode_00"):
        if marker in test_id:
            return marker
    return ""


def _write_repro_results(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    write_jsonl(output_dir / RESULTS_NAME, rows)


def _finalize_rows(rows: list[dict[str, Any]], *, orphan_check: str, output_dir: Path) -> list[dict[str, Any]]:
    durable_rows = _line_count(output_dir / RESULTS_NAME)
    completed_count = len(rows)
    finalized: list[dict[str, Any]] = []
    for row in rows:
        updated = dict(row)
        updated["completed_count"] = completed_count
        updated["durable_row_written"] = True
        updated["durable_rows_at_finalize"] = durable_rows
        updated["orphan_process_check_result"] = orphan_check
        updated["routine_save_repro_classification"] = _routine_save_classification(updated)
        updated["largest_payload_fields"] = _largest_payload_fields(updated)
        finalized.append(updated)
    return finalized


def _orphan_process_check_result() -> str:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'serve_command_eval_core.py' } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as error:
        return f"orphan_check_failed: {error}"
    output = (completed.stdout or "").strip()
    if not output:
        return "no_command_eval_child_processes_found"
    return f"possible_orphans: {output[:1000]}"


def _native_vs_fallback_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matrix: dict[str, Any] = {
        "counts": dict(Counter(str(row.get("routine_save_repro_classification") or "inconclusive") for row in rows)),
        "rows": [],
    }
    for row in rows:
        matrix["rows"].append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt") or row.get("input"),
                "scenario_label": row.get("scenario_label"),
                "classification": row.get("routine_save_repro_classification"),
                "expected_route_family": row.get("expected_route_family"),
                "actual_route_family": row.get("actual_route_family"),
                "expected_tool": row.get("expected_tool"),
                "actual_tool": row.get("actual_tool"),
                "provider_called": row.get("provider_called"),
                "fallback_reason": row.get("fallback_reason"),
                "provider_fallback_reason": row.get("provider_fallback_reason"),
                "route_scores": row.get("route_scores"),
                "missing_preconditions": row.get("missing_preconditions"),
                "selected_handler": row.get("selected_handler"),
                "total_latency_ms": row.get("total_latency_ms"),
                "unattributed_latency_ms": row.get("unattributed_latency_ms"),
                "routine_lookup_ms": row.get("routine_lookup_ms"),
                "routine_match_ms": row.get("routine_match_ms"),
                "routine_persistence_read_ms": row.get("routine_persistence_read_ms"),
                "routine_persistence_write_ms": row.get("routine_persistence_write_ms"),
                "routine_job_create_ms": row.get("routine_job_create_ms"),
                "routine_job_wait_ms": row.get("routine_job_wait_ms"),
                "routine_event_emit_ms": row.get("routine_event_emit_ms"),
                "routine_dto_build_ms": row.get("routine_dto_build_ms"),
                "routine_response_build_ms": row.get("routine_response_build_ms"),
                "routine_background_task_drain_ms": row.get("routine_background_task_drain_ms"),
                "response_json_bytes": row.get("response_json_bytes"),
                "workspace_item_count": row.get("workspace_item_count"),
            }
        )
    return matrix


def _skipped_scenario_summary(scenario: Scenario, reason: str) -> dict[str, Any]:
    return {
        "scenario_name": scenario.name,
        "dimensions": scenario.dimensions,
        "skipped": True,
        "skip_reason": reason,
        "completed_requests": 0,
        "durable_rows": 0,
    }


def _build_native_repeat_scenarios(first_native_scenario: Scenario, *, repetitions: int) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for repetition in range(1, repetitions + 1):
        cloned = tuple(
            replace(
                case,
                case_id=f"native_repeat_{repetition:02d}_{case.case_id}",
                session_id=f"session-native-repeat-{repetition:02d}",
                notes=f"Native routine_save repetition {repetition} from scenario {first_native_scenario.name}.",
            )
            for case in first_native_scenario.cases
        )
        scenarios.append(
            Scenario(
                name=f"native_repeat_{repetition:02d}_from_{first_native_scenario.name}",
                cases=cloned,
                history_strategy=first_native_scenario.history_strategy,
                process_scope=first_native_scenario.process_scope,
                runtime_seed_label=first_native_scenario.runtime_seed_label,
                runtime_seed_dir=first_native_scenario.runtime_seed_dir,
                dimensions={**first_native_scenario.dimensions, "native_repeat": repetition, "source_scenario": first_native_scenario.name},
            )
        )
    return scenarios


def _build_summary(
    *,
    rows: list[dict[str, Any]],
    scenario_summaries: list[dict[str, Any]],
    old_evidence_rows: list[dict[str, Any]],
    first_native_rows: list[dict[str, Any]],
    repeat_rows: list[dict[str, Any]],
    preserve_dir: Path,
    output_dir: Path,
    timeout_seconds: float,
    recovered_cases: dict[str, Any],
    native_vs_fallback: dict[str, Any],
    orphan_check: str,
) -> dict[str, Any]:
    attempts = [row for row in rows if _is_routine_save_attempt(row)]
    native_attempts = [row for row in attempts if row.get("actual_route_family") == "routine"]
    generic_attempts = [row for row in attempts if row.get("actual_route_family") == "generic_provider"]
    timeout_attempts = [row for row in attempts if row.get("status") == "hard_timeout"]
    repeated_attempts = [row for row in repeat_rows if _is_routine_save_attempt(row)]
    old_compact = [_compact_old_row(row) for row in old_evidence_rows[:10]]
    route_compare = _native_vs_generic_comparison(native_attempts, generic_attempts)
    completed = len(rows)
    durable = _line_count(output_dir / RESULTS_NAME)
    latency_values = [float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0) for row in native_attempts]
    slow_native = [row for row in native_attempts if float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0) >= 10000.0]
    old_profile_native = [
        row
        for row in native_attempts
        if float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0) >= 20000.0
        and float(row.get("response_serialization_ms") or 0.0) < 1000.0
    ]
    if old_profile_native or timeout_attempts:
        blocker_status = "native_route_latency_reproduced_or_hard_timeout_contained"
        recommendation = "fix routine_save product latency now"
    elif slow_native:
        blocker_status = "native_route_reproduced_with_bounded_slow_profile_different_from_old"
        recommendation = "proceed to focused-80 only if the risk is explicitly bounded"
    elif native_attempts:
        blocker_status = "native_route_reproduced_without_old_latency"
        recommendation = "fix routing preconditions if routine_save should not fall to generic_provider"
    else:
        blocker_status = "known_unreproduced_product_latency_blocker"
        recommendation = "mark routine_save as known contained blocker and proceed to focused-80 with that exclusion"
    return {
        "completed_requests": completed,
        "durable_rows": durable,
        "completed_equals_durable_rows": completed == durable,
        "timeout_seconds": timeout_seconds,
        "preserved_inputs_dir": str(preserve_dir),
        "recovered_old_cases_path": str(output_dir / OLD_CASES_NAME),
        "native_vs_fallback_matrix_path": str(output_dir / MATRIX_NAME),
        "orphan_process_check_result": orphan_check,
        "provider_calls": sum(1 for row in rows if row.get("provider_called")),
        "external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "routine_save_attempts": len(attempts),
        "routine_save_actual_routes": dict(Counter(str(row.get("actual_route_family") or "") for row in attempts)),
        "routine_save_actual_tools": dict(Counter(",".join(row.get("actual_tool") or ()) or "<none>" for row in attempts)),
        "routine_save_latency_summary_ms": _stats([float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0) for row in attempts]),
        "native_routine_save_latency_summary_ms": _stats(latency_values),
        "native_repeat_latency_summary_ms": _stats([float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0) for row in repeated_attempts]),
        "hard_timeout_attempts": len(timeout_attempts),
        "total_hard_timeout_rows": sum(1 for row in rows if row.get("status") == "hard_timeout"),
        "scenario_summaries": scenario_summaries,
        "old_95_case_native_evidence": old_compact,
        "old_95_case_native_latency_summary_ms": _stats([float(row.get("total_latency_ms") or 0.0) for row in old_evidence_rows]),
        "first_native_rows": [_compact_repro_row(row) for row in first_native_rows],
        "slow_native_rows": [_compact_repro_row(row) for row in slow_native[:10]],
        "timeout_rows": [_compact_repro_row(row) for row in timeout_attempts[:10]],
        "native_vs_generic_comparison": route_compare,
        "native_vs_fallback_matrix": native_vs_fallback,
        "recovered_old_case_count": len(recovered_cases.get("recovered_cases") or []),
        "old_previous_cases_before_first_routine_save_count": len(recovered_cases.get("previous_cases_before_first_routine_save") or []),
        "blocker_status": blocker_status,
        "recommendation": recommendation,
        "broad_evaluation_ready": False,
        "focused_80_readiness": "not_ready_until_routine_save_latency_or_precondition_risk_is_explicitly_bounded",
    }


def _native_vs_generic_comparison(native_rows: list[dict[str, Any]], generic_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    by_prompt_native = _first_by_prompt(native_rows)
    by_prompt_generic = _first_by_prompt(generic_rows)
    for prompt in sorted(set(by_prompt_native) & set(by_prompt_generic)):
        native = by_prompt_native[prompt]
        generic = by_prompt_generic[prompt]
        comparisons.append(
            {
                "prompt_text": prompt,
                "native": _comparison_side(native),
                "generic": _comparison_side(generic),
            }
        )
    return comparisons


def _first_by_prompt(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_prompt: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_prompt.setdefault(str(row.get("input") or ""), row)
    return by_prompt


def _comparison_side(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario": row.get("scenario_name"),
        "session_state_summary": row.get("session_state_summary"),
        "runtime_db_state_summary": row.get("runtime_db_state_summary"),
        "prior_turns_in_session": row.get("prior_turns_in_session"),
        "route_scores": row.get("route_scores"),
        "fallback_reason": row.get("fallback_reason"),
        "extracted_routine_intent": row.get("extracted_routine_intent"),
        "extracted_routine_name": row.get("extracted_routine_name"),
        "extracted_routine_target": row.get("extracted_routine_target"),
        "handler_selected": row.get("handler_selected"),
        "routine_save_tool_selected": row.get("routine_save_tool_selected"),
        "latency_spans": _latency_spans(row),
    }


def _latency_spans(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "total_latency_ms",
        "route_handler_ms",
        "routine_lookup_ms",
        "routine_persistence_read_ms",
        "routine_persistence_write_ms",
        "routine_job_create_ms",
        "routine_job_wait_ms",
        "routine_event_emit_ms",
        "routine_dto_build_ms",
        "routine_response_build_ms",
        "routine_background_task_drain_ms",
        "unattributed_latency_ms",
        "http_boundary_ms",
        "server_response_write_ms",
    )
    subspans = row.get("route_handler_subspans") if isinstance(row.get("route_handler_subspans"), dict) else {}
    spans: dict[str, Any] = {}
    for key in keys:
        spans[key] = row.get(key, subspans.get(key))
    return spans


def _compact_repro_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "input": row.get("input"),
        "scenario": row.get("scenario_name"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "expected_tool": row.get("expected_tool"),
        "actual_tool": row.get("actual_tool"),
        "result_state": row.get("result_state"),
        "status": row.get("status"),
        "process_killed": row.get("process_killed"),
        "provider_called": row.get("provider_called"),
        "latency_spans": _latency_spans(row),
        "route_scores": row.get("route_scores"),
        "fallback_reason": row.get("fallback_reason"),
        "missing_preconditions": row.get("missing_preconditions"),
    }


def _compact_old_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "input": row.get("input") or row.get("case", {}).get("message"),
        "actual_route_family": row.get("actual_route_family"),
        "actual_tool": row.get("actual_tool"),
        "provider_called": row.get("provider_called"),
        "total_latency_ms": row.get("total_latency_ms"),
        "route_handler_ms": row.get("route_handler_ms"),
        "response_serialization_ms": row.get("response_serialization_ms"),
        "job_collection_ms": row.get("job_collection_ms"),
        "memory_context_ms": row.get("memory_context_ms"),
        "route_scores": row.get("route_scores"),
    }


def _old_native_routine_save_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("test_id") or "").startswith("routine_save") and row.get("actual_route_family") == "routine":
                rows.append(row)
    return sorted(rows, key=lambda row: float(row.get("total_latency_ms") or 0.0), reverse=True)


def _old_session_id(old_evidence_rows: list[dict[str, Any]], test_id: str) -> str:
    for row in old_evidence_rows:
        if str(row.get("test_id") or "") == test_id:
            return str(row.get("session_id") or "")
    return ""


def _scenario_case_row(scenario: Scenario, case: CommandEvalCase) -> dict[str, Any]:
    return {
        "scenario_name": scenario.name,
        "dimensions": scenario.dimensions,
        "case": case.to_dict(),
    }


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "min": round(ordered[0], 3),
        "median": round(median(ordered), 3),
        "p90": round(_percentile(ordered, 0.90), 3),
        "p95": round(_percentile(ordered, 0.95), 3),
        "max": round(ordered[-1], 3),
    }


def _percentile(ordered: list[float], percentile: float) -> float:
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _build_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Routine Save Native-Route Latency Reproduction",
        "",
        "## Executive Summary",
        f"- status: {summary['blocker_status']}",
        f"- recommendation: {summary['recommendation']}",
        f"- focused-80 readiness: {summary['focused_80_readiness']}",
        f"- recovered old routine_save cases: {summary['recovered_old_case_count']}",
        "",
        "## Old Evidence Recap",
        f"- old previous cases before first routine_save: {summary['old_previous_cases_before_first_routine_save_count']}",
        f"- recovered definitions: {summary['recovered_old_cases_path']}",
        f"- old native latency summary: {summary['old_95_case_native_latency_summary_ms']}",
        _format_rows(summary["old_95_case_native_evidence"]),
        "",
        "## Harness Safety Recap",
        f"- completed requests: {summary['completed_requests']}",
        f"- durable rows: {summary['durable_rows']}",
        f"- completed equals durable rows: {summary['completed_equals_durable_rows']}",
        f"- hard timeout cap seconds: {summary['timeout_seconds']}",
        f"- total hard-timeout rows: {summary.get('total_hard_timeout_rows', 0)}",
        f"- provider calls: {summary['provider_calls']}",
        f"- real external actions: {summary['external_actions']}",
        f"- orphan process check: {summary['orphan_process_check_result']}",
        f"- preserved inputs: {summary['preserved_inputs_dir']}",
        "",
        "## Reproduction Matrix Summary",
        f"- routine_save attempts: {summary['routine_save_attempts']}",
        f"- actual routes: {summary['routine_save_actual_routes']}",
        f"- actual tools: {summary['routine_save_actual_tools']}",
        f"- classification counts: {summary['native_vs_fallback_matrix'].get('counts', {})}",
        _format_scenarios(summary["scenario_summaries"]),
        "",
        "## Native Route Reproduction Status",
        f"- native routine_save latency summary: {summary['native_routine_save_latency_summary_ms']}",
        f"- native repeat latency summary: {summary['native_repeat_latency_summary_ms']}",
        "First native rows:",
        _format_rows(summary["first_native_rows"]),
        "Slow native rows:",
        _format_rows(summary["slow_native_rows"]),
        "Timeout rows:",
        _format_rows(summary["timeout_rows"]),
        "",
        "## Generic Fallback Analysis",
        _format_fallback_analysis(summary["native_vs_fallback_matrix"]),
        "",
        "## Prefix Search Results",
        _format_prefix_results(summary["scenario_summaries"]),
        "",
        "## Native-Vs-Fallback Comparison Table",
        f"- machine-readable matrix: {summary['native_vs_fallback_matrix_path']}",
        _format_rows(summary["native_vs_generic_comparison"]),
        "",
        "## Latency And Unattributed-Latency Summary",
        "Routine save latency summary:",
        _format_mapping(summary["routine_save_latency_summary_ms"]),
        "Native routine_save latency summary:",
        _format_mapping(summary["native_routine_save_latency_summary_ms"]),
        "Native repeat latency summary:",
        _format_mapping(summary["native_repeat_latency_summary_ms"]),
        "",
        "## Routine Subspan Summary",
        _format_routine_subspan_summary(summary["native_vs_fallback_matrix"]),
        "",
        "## Payload Diagnostics Summary",
        _format_payload_summary(summary["native_vs_fallback_matrix"]),
        "",
        "## Root-Cause Hypothesis",
        _interpretation(summary),
        "",
        "## Classification",
        f"- routine_save is: {summary['blocker_status']}",
        "- generic-provider routing gap is present when active/deictic context is missing.",
        "",
        "## Recommendation",
        f"- {summary['recommendation']}",
        "",
        "## Exact Next Command Recommendation",
        _next_command_recommendation(summary),
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def _format_scenarios(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- none"
    lines = []
    for row in rows:
        route_summary = row.get("actual_routes", {})
        latency = row.get("latency_ms", {})
        skipped = " skipped" if row.get("skipped") else ""
        lines.append(
            f"- {row['scenario_name']}{skipped}: requests={row.get('completed_requests', 0)}, rows={row.get('durable_rows', 0)}, "
            f"routes={route_summary}, timeouts={row.get('hard_timeouts', 0)}, latency={latency}"
        )
    return "\n".join(lines)


def _format_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- none"
    return "```json\n" + json.dumps(rows, indent=2, sort_keys=True, default=str) + "\n```"


def _format_mapping(mapping: dict[str, Any]) -> str:
    return "```json\n" + json.dumps(mapping, indent=2, sort_keys=True, default=str) + "\n```"


def _format_fallback_analysis(matrix: dict[str, Any]) -> str:
    rows = [
        row
        for row in matrix.get("rows", [])
        if row.get("classification") == "generic_provider_fallback"
    ][:20]
    if not rows:
        return "- no generic_provider fallback rows"
    compact = [
        {
            "test_id": row.get("test_id"),
            "scenario": row.get("scenario_label"),
            "fallback_reason": row.get("fallback_reason"),
            "provider_fallback_reason": row.get("provider_fallback_reason"),
            "route_scores": row.get("route_scores"),
            "missing_preconditions": row.get("missing_preconditions"),
        }
        for row in rows
    ]
    return _format_rows(compact)


def _format_prefix_results(rows: list[dict[str, Any]]) -> str:
    prefix_rows = [row for row in rows if str(row.get("scenario_name") or "").startswith("prefix_first_")]
    if not prefix_rows:
        return "- no prefix search rows"
    return _format_scenarios(prefix_rows)


def _format_routine_subspan_summary(matrix: dict[str, Any]) -> str:
    rows = [row for row in matrix.get("rows", []) if str(row.get("classification") or "").startswith("native_routine_save")]
    if not rows:
        return "- no native routine_save rows"
    compact = [
        {
            "test_id": row.get("test_id"),
            "classification": row.get("classification"),
            "total_latency_ms": row.get("total_latency_ms"),
            "unattributed_latency_ms": row.get("unattributed_latency_ms"),
            "routine_job_create_ms": row.get("routine_job_create_ms"),
            "routine_job_wait_ms": row.get("routine_job_wait_ms"),
            "routine_persistence_read_ms": row.get("routine_persistence_read_ms"),
            "routine_persistence_write_ms": row.get("routine_persistence_write_ms"),
            "routine_response_build_ms": row.get("routine_response_build_ms"),
        }
        for row in rows[:20]
    ]
    return _format_rows(compact)


def _format_payload_summary(matrix: dict[str, Any]) -> str:
    rows = sorted(
        matrix.get("rows", []),
        key=lambda row: int(row.get("response_json_bytes") or 0),
        reverse=True,
    )[:10]
    if not rows:
        return "- no payload diagnostics rows"
    compact = [
        {
            "test_id": row.get("test_id"),
            "classification": row.get("classification"),
            "response_json_bytes": row.get("response_json_bytes"),
            "workspace_item_count": row.get("workspace_item_count"),
            "total_latency_ms": row.get("total_latency_ms"),
        }
        for row in rows
    ]
    return _format_rows(compact)


def _next_command_recommendation(summary: dict[str, Any]) -> str:
    if summary["blocker_status"] == "native_route_latency_reproduced_or_hard_timeout_contained":
        return "`python scripts/reproduce_routine_save_latency.py --output-dir .artifacts/command-usability-eval/routine-save-repro --timeout-seconds 60 --native-repetitions 5` after a narrow routine_save latency fix."
    return "`python scripts/run_command_usability_eval.py --limit 80 --process-scope per_run --per-test-timeout-seconds 60` only after marking routine_save as a hard-timeout-contained known blocker or exclusion lane."


def _interpretation(summary: dict[str, Any]) -> str:
    if summary["blocker_status"] == "native_route_latency_reproduced_or_hard_timeout_contained":
        return (
            "Native routine_save is reproduced or bounded by the hard timeout. The old latency is still a product "
            "blocker; proceed to code-level latency triage before broad evaluation."
        )
    if summary["blocker_status"] == "native_route_reproduced_with_bounded_slow_profile_different_from_old":
        return (
            "Native routine_save is reproduced and one bounded slow path was observed, but it does not match the old "
            "43s-75s profile. Treat the old catastrophic latency as unresolved and run focused-80 only with routine_save "
            "risk explicitly bounded under the hard-timeout harness."
        )
    if summary["blocker_status"] == "native_route_reproduced_without_old_latency":
        return (
            "The native route now reproduces only when the old active request state is supplied, but the old 43s-75s "
            "latency did not reproduce in this matrix. The old latency is not fixed; its trigger is still unknown. "
            "The generic_provider fallbacks are explained by missing active/deictic context."
        )
    return (
        "The old native routine_save latency remains a known unreproduced product latency blocker sourced to the "
        "old 95-case micro-suite. Keep it in a contained known-blocker lane under hard timeout."
    )


if __name__ == "__main__":
    main()
