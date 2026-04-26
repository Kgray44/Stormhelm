from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from dataclasses import replace
from pathlib import Path
from statistics import median
from typing import Any

from stormhelm.core.orchestrator.command_eval import (
    CommandEvalCase,
    ExpectedBehavior,
    ProcessIsolatedCommandUsabilityHarness,
    build_command_usability_corpus,
)
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl

from run_latency_micro_suite import build_latency_micro_cases


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "payload-routine-hardening"
RESULTS_NAME = "payload_routine_results.jsonl"
DIAGNOSTICS_NAME = "payload_guardrail_diagnostics.jsonl"
SUMMARY_NAME = "payload_routine_hardening_summary.json"
REPORT_NAME = "payload_routine_hardening_report.md"
ROUTINE_REPRO_DIR = Path(".artifacts") / "command-usability-eval" / "routine-save-repro"
PRELIM_ROUTINE_REPRO_DIR = Path(".artifacts") / "command-usability-eval" / "routine-save-repro-20260425-030425"
OLD_LATENCY_DIR = Path(".artifacts") / "command-usability-eval" / "latency-micro-20260424-225838"
INTERRUPTED_LATENCY_DIR = Path(".artifacts") / "command-usability-eval" / "latency-micro-instrumented-20260424-232011"
PAYLOAD_WARN_BYTES = 1_000_000
PAYLOAD_FAIL_BYTES = 5_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description="Run narrow payload/routine hardening regressions.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    scenarios = _build_scenarios()
    aggregate_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    scenario_summaries: list[dict[str, Any]] = []

    for scenario in scenarios:
        rows = _run_scenario(
            scenario,
            output_dir=args.output_dir,
            timeout_seconds=args.timeout_seconds,
            server_startup_timeout_seconds=args.server_startup_timeout_seconds,
        )
        aggregate_rows.extend(rows)
        diagnostics.extend(_diagnostic_row(row) for row in rows)
        write_jsonl(args.output_dir / RESULTS_NAME, aggregate_rows)
        write_jsonl(args.output_dir / DIAGNOSTICS_NAME, diagnostics)
        scenario_summaries.append(_scenario_summary(scenario, rows))

    orphan_check = _orphan_process_check_result()
    summary = _build_summary(
        rows=aggregate_rows,
        diagnostics=diagnostics,
        scenario_summaries=scenario_summaries,
        orphan_check=orphan_check,
        output_dir=args.output_dir,
        timeout_seconds=args.timeout_seconds,
    )
    write_json(args.output_dir / SUMMARY_NAME, summary)
    (args.output_dir / REPORT_NAME).write_text(_build_report(summary), encoding="utf-8")

    print(f"{RESULTS_NAME}: {args.output_dir / RESULTS_NAME}")
    print(f"{DIAGNOSTICS_NAME}: {args.output_dir / DIAGNOSTICS_NAME}")
    print(f"{SUMMARY_NAME}: {args.output_dir / SUMMARY_NAME}")
    print(f"{REPORT_NAME}: {args.output_dir / REPORT_NAME}")


def _build_scenarios() -> list[dict[str, Any]]:
    corpus = build_command_usability_corpus(min_cases=1000)
    lookup = {case.case_id: case for case in corpus}
    old_micro_cases = build_latency_micro_cases(lookup, repeats=5)

    routine_source = lookup["routine_save_canonical_00"]
    no_context = replace(
        routine_source,
        case_id="payload_hardening_no_context_routine_save",
        session_id="payload-routine-no-context",
        active_request_state={},
        expected=ExpectedBehavior(
            route_family="routine",
            subsystem="routine",
            tools=(),
            clarification="expected",
            result_state="needs_clarification",
            response_terms=("need", "steps"),
            latency_ms_max=60_000,
        ),
        tags=(*routine_source.tags, "payload_routine_hardening", "no_context"),
        notes="No-context routine save must route natively and clarify instead of falling to provider.",
    )
    active_context = replace(
        routine_source,
        case_id="payload_hardening_active_state_routine_save",
        session_id="payload-routine-active",
        expected=ExpectedBehavior(
            route_family="routine",
            subsystem="routine",
            tools=("routine_save",),
            clarification="none",
            result_state="dry_run_or_completed",
            response_terms=("routine",),
            latency_ms_max=60_000,
        ),
        tags=(*routine_source.tags, "payload_routine_hardening", "active_state"),
        notes="Active routine save should keep the native routine_save dry-run path.",
    )

    workspace_source = lookup["workspace_assemble_canonical_00"]
    workspace_cap = _with_latency_guard(
        replace(
            workspace_source,
            case_id="payload_hardening_workspace_assemble_cap",
            session_id="payload-workspace-cap",
            tags=(*workspace_source.tags, "payload_routine_hardening", "payload_cap"),
            notes="Single workspace assemble payload cap regression.",
        )
    )
    prefix_cases = tuple(
        _with_latency_guard(
            replace(
                case,
                case_id=f"payload_hardening_prefix_{index:02d}_{case.case_id}",
                session_id="payload-prefix-contamination",
                tags=(*case.tags, "payload_routine_hardening", "prefix_contamination"),
            )
        )
        for index, case in enumerate(old_micro_cases[:5])
    )
    prefix_target = replace(
        no_context,
        case_id="payload_hardening_prefix_after_workspace_routine_save",
        session_id="payload-prefix-contamination",
        tags=(*no_context.tags, "prefix_contamination"),
        notes="Routine save after workspace prefix should not inherit giant payloads or fall to provider.",
    )

    return [
        {
            "name": "routine_save_preconditions",
            "process_scope": "per_case",
            "history_strategy": "isolated_session",
            "cases": (no_context, active_context),
        },
        {
            "name": "workspace_payload_cap",
            "process_scope": "per_case",
            "history_strategy": "isolated_session",
            "cases": (workspace_cap,),
        },
        {
            "name": "prefix_contamination_regression",
            "process_scope": "per_run",
            "history_strategy": "shared_session",
            "cases": (*prefix_cases, prefix_target),
        },
    ]


def _with_latency_guard(case: CommandEvalCase) -> CommandEvalCase:
    return replace(
        case,
        expected=replace(case.expected, latency_ms_max=60_000),
    )


def _run_scenario(
    scenario: dict[str, Any],
    *,
    output_dir: Path,
    timeout_seconds: float,
    server_startup_timeout_seconds: float,
) -> list[dict[str, Any]]:
    scenario_dir = output_dir / "scenario-runs" / str(scenario["name"])
    scenario_dir.mkdir(parents=True, exist_ok=True)
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=scenario_dir,
        per_test_timeout_seconds=timeout_seconds,
        server_startup_timeout_seconds=server_startup_timeout_seconds,
        process_scope=str(scenario["process_scope"]),
        history_strategy=str(scenario["history_strategy"]),
    )
    results = harness.run(list(scenario["cases"]), results_name=f"{scenario['name']}.jsonl")
    rows: list[dict[str, Any]] = []
    for result in results:
        row = result.to_dict()
        row["scenario_label"] = scenario["name"]
        row["process_isolated"] = True
        row["hard_timeout_seconds"] = timeout_seconds
        row["durable_row_written"] = True
        row["payload_guardrail_pass"] = _payload_guardrail_pass(row)
        row["routine_precondition_pass"] = _routine_precondition_pass(row)
        rows.append(row)
    return rows


def _payload_guardrail_pass(row: dict[str, Any]) -> bool:
    if row.get("status") == "hard_timeout":
        return False
    return int(row.get("response_json_bytes") or 0) < PAYLOAD_FAIL_BYTES


def _routine_precondition_pass(row: dict[str, Any]) -> bool:
    if "routine_save" not in str(row.get("test_id") or ""):
        return True
    if row.get("actual_route_family") != "routine":
        return False
    if row.get("provider_called"):
        return False
    if "no_context" in str(row.get("test_id") or "") or "prefix_after_workspace" in str(row.get("test_id") or ""):
        return row.get("result_state") in {"needs_clarification", "blocked_missing_context"}
    return "routine_save" in (row.get("actual_tool") or [])


def _diagnostic_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario_label": row.get("scenario_label"),
        "test_id": row.get("test_id"),
        "input": row.get("input"),
        "status": row.get("status"),
        "actual_route_family": row.get("actual_route_family"),
        "actual_tool": row.get("actual_tool"),
        "result_state": row.get("result_state"),
        "provider_called": row.get("provider_called"),
        "external_action_performed": row.get("external_action_performed"),
        "response_json_bytes": row.get("response_json_bytes"),
        "workspace_item_count": row.get("workspace_item_count"),
        "active_context_bytes": row.get("active_context_bytes"),
        "active_context_item_count": row.get("active_context_item_count"),
        "truncated_workspace_items": row.get("truncated_workspace_items"),
        "largest_payload_fields": row.get("largest_payload_fields"),
        "payload_guardrail_triggered": row.get("payload_guardrail_triggered"),
        "payload_guardrail_reason": row.get("payload_guardrail_reason"),
        "payload_guardrail_pass": row.get("payload_guardrail_pass"),
        "routine_precondition_pass": row.get("routine_precondition_pass"),
        "latency_ms": row.get("latency_ms"),
        "route_handler_ms": row.get("route_handler_ms"),
        "response_serialization_ms": row.get("response_serialization_ms"),
        "route_handler_subspans": row.get("route_handler_subspans"),
    }


def _scenario_summary(scenario: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "scenario_label": scenario["name"],
        "case_count": len(scenario["cases"]),
        "completed_rows": len(rows),
        "status_counts": dict(Counter(str(row.get("status") or "") for row in rows)),
        "actual_route_counts": dict(Counter(str(row.get("actual_route_family") or "") for row in rows)),
        "max_response_json_bytes": max([int(row.get("response_json_bytes") or 0) for row in rows] or [0]),
        "max_workspace_item_count": max([int(row.get("workspace_item_count") or 0) for row in rows] or [0]),
        "payload_guardrail_failures": [
            row.get("test_id") for row in rows if not bool(row.get("payload_guardrail_pass"))
        ],
        "routine_precondition_failures": [
            row.get("test_id") for row in rows if not bool(row.get("routine_precondition_pass"))
        ],
        "latency_summary_ms": _stats([float(row.get("latency_ms") or 0.0) for row in rows]),
    }


def _build_summary(
    *,
    rows: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    scenario_summaries: list[dict[str, Any]],
    orphan_check: str,
    output_dir: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    final_repro = _read_json(ROUTINE_REPRO_DIR / "routine_save_repro_summary.json")
    prelim_repro = _read_json(PRELIM_ROUTINE_REPRO_DIR / "routine_save_reproduction_summary.json")
    old_native_rows = _old_routine_save_rows(OLD_LATENCY_DIR / "latency_micro_results.jsonl")
    interrupted_top_rows = _top_latency_rows(INTERRUPTED_LATENCY_DIR / "latency_micro_results.jsonl", limit=5)
    old_payload_rows = _top_payload_rows(ROUTINE_REPRO_DIR / "routine_save_repro_results.jsonl", limit=5)
    response_sizes = [int(row.get("response_json_bytes") or 0) for row in rows]
    latencies = [float(row.get("latency_ms") or 0.0) for row in rows]
    routine_rows = [row for row in rows if "routine_save" in str(row.get("test_id") or "")]
    workspace_rows = [row for row in rows if str(row.get("expected_route_family") or "") == "workspace_operations"]
    summary = {
        "completed_requests": len(rows),
        "durable_rows": _line_count(output_dir / RESULTS_NAME),
        "completed_equals_durable_rows": len(rows) == _line_count(output_dir / RESULTS_NAME),
        "timeout_seconds": timeout_seconds,
        "hard_timeout_rows": sum(1 for row in rows if row.get("status") == "hard_timeout"),
        "provider_calls": sum(1 for row in rows if row.get("provider_called")),
        "external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "orphan_process_check_result": orphan_check,
        "status_counts": dict(Counter(str(row.get("status") or "") for row in rows)),
        "route_counts": dict(Counter(str(row.get("actual_route_family") or "") for row in rows)),
        "payload_guardrail_failures": [row.get("test_id") for row in rows if not bool(row.get("payload_guardrail_pass"))],
        "routine_precondition_failures": [row.get("test_id") for row in rows if not bool(row.get("routine_precondition_pass"))],
        "response_json_bytes_summary": _stats(response_sizes),
        "latency_summary_ms": _stats(latencies),
        "max_workspace_item_count": max([int(row.get("workspace_item_count") or 0) for row in rows] or [0]),
        "scenario_summaries": scenario_summaries,
        "artifact_reconciliation": {
            "preliminary_28_row_run": _repro_run_recap(prelim_repro),
            "authoritative_63_row_run": _repro_run_recap(final_repro),
            "authoritative_run_selected": "later 63-row routine-save-repro pass",
            "old_95_case_micro_suite": {
                "path": str(OLD_LATENCY_DIR / "latency_micro_results.jsonl"),
                "native_routine_save_rows": len(old_native_rows),
                "latency_summary_ms": _stats([float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0) for row in old_native_rows]),
                "top_rows": [_compact_evidence_row(row) for row in old_native_rows[:10]],
            },
            "interrupted_latency_evidence": [_compact_evidence_row(row) for row in interrupted_top_rows],
        },
        "old_payload_growth_evidence": [_compact_payload_evidence(row) for row in old_payload_rows],
        "before_after_payload_table": _before_after_payload_table(old_payload_rows, diagnostics),
        "before_after_latency_table": _before_after_latency_table(old_native_rows, routine_rows, workspace_rows),
        "root_cause_hypothesis": (
            "The old routine_save latency remains a known unreproduced product-latency blocker. "
            "The bounded reproduction evidence points to workspace response/state payload growth and deictic context carryover "
            "as the risk source, not routine persistence alone."
        ),
        "remaining_known_blockers": [
            "known_unreproduced_product_latency_blocker: old native routine_save 43s-75s profile remains historical evidence",
        ],
        "focused_80_readiness": _focused_80_readiness(rows),
        "recommendation": _recommendation(rows),
        "results_path": str(output_dir / RESULTS_NAME),
        "diagnostics_path": str(output_dir / DIAGNOSTICS_NAME),
    }
    return summary


def _repro_run_recap(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {"available": False}
    return {
        "available": True,
        "completed_requests": summary.get("completed_requests"),
        "durable_rows": summary.get("durable_rows"),
        "provider_calls": summary.get("provider_calls"),
        "external_actions": summary.get("external_actions"),
        "hard_timeout_rows": summary.get("total_hard_timeout_rows") or summary.get("hard_timeout_attempts"),
        "routine_save_attempts": summary.get("routine_save_attempts"),
        "routine_save_actual_routes": summary.get("routine_save_actual_routes"),
        "native_routine_save_latency_summary_ms": summary.get("native_routine_save_latency_summary_ms"),
        "blocker_status": summary.get("blocker_status"),
        "recommendation": summary.get("recommendation"),
    }


def _focused_80_readiness(rows: list[dict[str, Any]]) -> str:
    if any(row.get("status") == "hard_timeout" for row in rows):
        return "not_ready_hard_timeout_in_narrow_suite"
    if any(row.get("provider_called") for row in rows):
        return "not_ready_provider_called_in_dry_run_suite"
    if any(row.get("external_action_performed") for row in rows):
        return "not_ready_external_action_detected"
    if any(not row.get("payload_guardrail_pass") for row in rows):
        return "not_ready_payload_guardrail_failed"
    if any(not row.get("routine_precondition_pass") for row in rows):
        return "not_ready_routine_precondition_failed"
    return "safe_to_run_focused_80_under_hard_timeout_with_routine_save_blocker_label_preserved"


def _recommendation(rows: list[dict[str, Any]]) -> str:
    readiness = _focused_80_readiness(rows)
    if readiness.startswith("safe_to_run"):
        return "Proceed to focused-80 under the process-isolated hard-timeout harness, preserving routine_save as a known historical blocker."
    return "Do not proceed to focused-80 until the narrow hardening failures listed in this report are fixed."


def _old_routine_save_rows(path: Path) -> list[dict[str, Any]]:
    rows = [
        row
        for row in _read_jsonl(path)
        if str(row.get("test_id") or "").startswith("routine_save") and row.get("actual_route_family") == "routine"
    ]
    return sorted(rows, key=lambda row: float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0), reverse=True)


def _top_latency_rows(path: Path, *, limit: int) -> list[dict[str, Any]]:
    return sorted(
        _read_jsonl(path),
        key=lambda row: float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0),
        reverse=True,
    )[:limit]


def _top_payload_rows(path: Path, *, limit: int) -> list[dict[str, Any]]:
    return sorted(
        _read_jsonl(path),
        key=lambda row: int(row.get("response_json_bytes") or 0),
        reverse=True,
    )[:limit]


def _compact_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "input": row.get("input"),
        "actual_route_family": row.get("actual_route_family"),
        "actual_tool": row.get("actual_tool"),
        "status": row.get("status"),
        "latency_ms": row.get("total_latency_ms") or row.get("latency_ms"),
        "route_handler_ms": row.get("route_handler_ms"),
        "response_serialization_ms": row.get("response_serialization_ms"),
        "response_json_bytes": row.get("response_json_bytes"),
        "workspace_item_count": row.get("workspace_item_count"),
    }


def _compact_payload_evidence(row: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_evidence_row(row)
    compact["scenario_label"] = row.get("scenario_label")
    compact["payload_guardrail_reason"] = row.get("payload_guardrail_reason")
    return compact


def _before_after_payload_table(old_rows: list[dict[str, Any]], diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old_top = old_rows[:3]
    new_top = sorted(diagnostics, key=lambda row: int(row.get("response_json_bytes") or 0), reverse=True)[:5]
    rows: list[dict[str, Any]] = []
    for row in old_top:
        rows.append(
            {
                "phase": "before",
                "test_id": row.get("test_id"),
                "scenario_label": row.get("scenario_label"),
                "response_json_bytes": row.get("response_json_bytes"),
                "workspace_item_count": row.get("workspace_item_count"),
            }
        )
    for row in new_top:
        rows.append(
            {
                "phase": "after",
                "test_id": row.get("test_id"),
                "scenario_label": row.get("scenario_label"),
                "response_json_bytes": row.get("response_json_bytes"),
                "workspace_item_count": row.get("workspace_item_count"),
                "payload_guardrail_pass": row.get("payload_guardrail_pass"),
            }
        )
    return rows


def _before_after_latency_table(
    old_native_rows: list[dict[str, Any]],
    routine_rows: list[dict[str, Any]],
    workspace_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "phase": "before_old_95_native_routine_save",
            "latency_summary_ms": _stats([float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0) for row in old_native_rows]),
        },
        {
            "phase": "after_targeted_routine_save",
            "latency_summary_ms": _stats([float(row.get("latency_ms") or 0.0) for row in routine_rows]),
        },
        {
            "phase": "after_targeted_workspace",
            "latency_summary_ms": _stats([float(row.get("latency_ms") or 0.0) for row in workspace_rows]),
        },
    ]


def _stats(values: list[float] | list[int]) -> dict[str, float | int]:
    if not values:
        return {"count": 0}
    ordered = sorted(float(value) for value in values)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 3),
        "median": round(float(median(ordered)), 3),
        "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "max": round(ordered[-1], 3),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _orphan_process_check_result() -> str:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*serve_command_eval_core.py*' } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=str(Path.cwd()),
        text=True,
        capture_output=True,
        timeout=20,
    )
    output = (completed.stdout or "").strip()
    if not output:
        return "no_orphan_command_eval_processes_detected"
    return f"possible_processes_detected: {output[:1000]}"


def _format_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- none"
    return "\n".join(f"- `{row.get('test_id')}`: {row}" for row in rows)


def _build_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Payload And Routine Hardening Report",
            "",
            "## Executive Summary",
            f"- completed requests: {summary['completed_requests']}",
            f"- durable rows: {summary['durable_rows']}",
            f"- provider calls: {summary['provider_calls']}",
            f"- real external actions: {summary['external_actions']}",
            f"- hard timeouts: {summary['hard_timeout_rows']}",
            f"- completed equals durable rows: {summary['completed_equals_durable_rows']}",
            f"- orphan process check: {summary['orphan_process_check_result']}",
            f"- focused-80 readiness: {summary['focused_80_readiness']}",
            f"- recommendation: {summary['recommendation']}",
            "",
            "## Artifact Reconciliation",
            f"- preliminary run: {summary['artifact_reconciliation']['preliminary_28_row_run']}",
            f"- authoritative run: {summary['artifact_reconciliation']['authoritative_63_row_run']}",
            f"- selected: {summary['artifact_reconciliation']['authoritative_run_selected']}",
            "",
            "## Harness Safety Recap",
            f"- timeout seconds: {summary['timeout_seconds']}",
            f"- hard-timeout rows: {summary['hard_timeout_rows']}",
            f"- provider calls: {summary['provider_calls']}",
            f"- real external actions: {summary['external_actions']}",
            f"- completed equals durable rows: {summary['completed_equals_durable_rows']}",
            f"- orphan process check: {summary['orphan_process_check_result']}",
            "",
            "## Old Catastrophic Routine_Save Evidence Recap",
            f"- old native latency summary: {summary['artifact_reconciliation']['old_95_case_micro_suite']['latency_summary_ms']}",
            _format_table(summary["artifact_reconciliation"]["old_95_case_micro_suite"]["top_rows"][:8]),
            "",
            "## Root-Cause Hypothesis After This Pass",
            f"- {summary['root_cause_hypothesis']}",
            "",
            "## Workspace Payload Growth Findings",
            _format_table(summary["old_payload_growth_evidence"]),
            "",
            "## Response And State Caps Added",
            "- Workspace Core-to-UI payloads now cap embedded item arrays and include total/displayed/truncated/omitted summaries.",
            "- Active workspace posture now stores compact item references instead of carrying unbounded item arrays.",
            "- Active task/evidence payloads now store compact result summaries instead of repeating full direct-tool response payloads.",
            "- Evaluator rows now record response bytes, active-context bytes/items, truncation, largest fields, and guardrail reasons.",
            "",
            "## Routine_Save Routing Preconditions Before/After",
            "- Before: no-context routine-save wording could fall to generic_provider.",
            "- After: routine-save wording remains in the routine family and asks for missing steps/context when no saveable active action exists.",
            "",
            "## Test Results",
            f"- status counts: {summary['status_counts']}",
            f"- route counts: {summary['route_counts']}",
            f"- payload guardrail failures: {summary['payload_guardrail_failures']}",
            f"- routine precondition failures: {summary['routine_precondition_failures']}",
            f"- scenario summaries: {summary['scenario_summaries']}",
            "",
            "## Payload-Size Before/After Table",
            _format_table(summary["before_after_payload_table"]),
            "",
            "## Latency Before/After Table",
            _format_table(summary["before_after_latency_table"]),
            "",
            "## Remaining Known Blockers",
            _format_table([{"test_id": "routine_save", "blocker": item} for item in summary["remaining_known_blockers"]]),
            "",
            "## Recommendation On Focused-80",
            f"- {summary['focused_80_readiness']}",
            f"- exact next command recommendation: `python scripts/run_command_usability_eval.py --limit 80 --process-scope per_run --per-test-timeout-seconds 60` after preserving this report and keeping routine_save marked as a historical known blocker.",
            "",
        ]
    )


if __name__ == "__main__":
    main()
