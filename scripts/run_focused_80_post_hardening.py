from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_audit
from stormhelm.core.orchestrator.command_eval import build_feature_map
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "focused-80-post-hardening"
PRIOR_FOCUSED_DIR = Path(".artifacts") / "command-usability-eval" / "preserved-focused-80-20260424-225110"
OLD_LATENCY_DIR = Path(".artifacts") / "command-usability-eval" / "latency-micro-20260424-225838"
PAYLOAD_HARDENING_DIR = Path(".artifacts") / "command-usability-eval" / "payload-routine-hardening"
PAYLOAD_WARN_BYTES = 1_000_000
PAYLOAD_FAIL_BYTES = 5_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description="Run focused-80 post-hardening checkpoint only.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    parser.add_argument("--history-strategy", choices=["isolated_session", "shared_session"], default="isolated_session")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    corpus = build_command_usability_corpus(min_cases=1000)
    full_corpus = corpus[:1000]
    focused_corpus = _focused_subset(full_corpus, limit=80)
    feature_map = build_feature_map()
    feature_audit = build_feature_audit(full_corpus)

    write_json(args.output_dir / "feature_map.json", feature_map)
    write_json(args.output_dir / "feature_map_audit.json", feature_audit)
    write_jsonl(args.output_dir / "focused_80_corpus.jsonl", [case.to_dict() for case in focused_corpus])
    write_jsonl(args.output_dir / "corpus.jsonl", [case.to_dict() for case in full_corpus])

    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy=args.history_strategy,
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(focused_corpus, results_name="focused_80_results.jsonl", resume=False)

    rows_path = args.output_dir / "focused_80_results.jsonl"
    rows = _read_jsonl(rows_path)
    diagnostics = [_payload_diagnostic(row) for row in rows]
    route_confusion = _route_confusion_matrix(rows)
    write_jsonl(args.output_dir / "focused_80_payload_diagnostics.jsonl", diagnostics)
    write_json(args.output_dir / "focused_80_route_confusion_matrix.json", route_confusion)

    checkpoint_path = args.output_dir / "focused_80_results.checkpoint.json"
    checkpoint = _read_json(checkpoint_path)
    summary = _build_summary(
        rows=rows,
        attempted=len(focused_corpus),
        result_count=len(results),
        feature_audit=feature_audit,
        checkpoint=checkpoint,
        output_dir=args.output_dir,
        timeout_seconds=args.timeout_seconds,
        process_scope=args.process_scope,
        history_strategy=args.history_strategy,
    )
    write_json(args.output_dir / "focused_80_summary.json", summary)
    (args.output_dir / "focused_80_checkpoint_report.md").write_text(_build_report(summary), encoding="utf-8")

    print(f"focused_80_results: {args.output_dir / 'focused_80_results.jsonl'}")
    print(f"focused_80_summary: {args.output_dir / 'focused_80_summary.json'}")
    print(f"focused_80_checkpoint_report: {args.output_dir / 'focused_80_checkpoint_report.md'}")
    print(f"focused_80_payload_diagnostics: {args.output_dir / 'focused_80_payload_diagnostics.jsonl'}")
    print(f"focused_80_route_confusion_matrix: {args.output_dir / 'focused_80_route_confusion_matrix.json'}")


def _focused_subset(corpus: list[Any], *, limit: int) -> list[Any]:
    if len(corpus) <= limit:
        return list(corpus)
    canonical = [case for case in corpus if "canonical" in case.tags]
    fuzzy = [case for case in corpus if {"typo", "ambiguous", "deictic", "follow_up"} & set(case.tags)]
    selected: list[Any] = []
    seen: set[str] = set()
    for case in [*canonical, *fuzzy, *corpus]:
        if case.case_id in seen:
            continue
        selected.append(case)
        seen.add(case.case_id)
        if len(selected) >= limit:
            break
    return selected


def _build_summary(
    *,
    rows: list[dict[str, Any]],
    attempted: int,
    result_count: int,
    feature_audit: dict[str, Any],
    checkpoint: dict[str, Any],
    output_dir: Path,
    timeout_seconds: float,
    process_scope: str,
    history_strategy: str,
) -> dict[str, Any]:
    scored = [row for row in rows if row.get("score_in_pass_fail")]
    failed = [row for row in rows if not row.get("passed")]
    scored_failed = [row for row in scored if not row.get("passed")]
    excluded = [row for row in rows if not row.get("score_in_pass_fail")]
    excluded_failed = [row for row in excluded if not row.get("passed")]
    latencies = [float(row.get("latency_ms") or 0.0) for row in rows]
    response_sizes = [float(row.get("response_json_bytes") or 0.0) for row in rows]
    workspace_counts = [int(row.get("workspace_item_count") or 0) for row in rows]
    route_confusion = _route_confusion_matrix(rows)
    wrong_subsystem_rows = [
        _compact_row(row)
        for row in rows
        if str(row.get("expected_subsystem") or "") != str(row.get("actual_subsystem") or "")
    ]
    provider_calls = sum(1 for row in rows if row.get("provider_called"))
    external_actions = sum(1 for row in rows if row.get("external_action_performed"))
    hard_timeouts = [row for row in rows if row.get("status") == "hard_timeout" or row.get("result_state") == "hard_timeout"]
    payload_failures = [
        _compact_row(row)
        for row in rows
        if int(row.get("response_json_bytes") or 0) > PAYLOAD_FAIL_BYTES
        or str(row.get("failure_category") or "") == "payload_guardrail_failure"
    ]
    payload_warnings = [_compact_row(row) for row in rows if int(row.get("response_json_bytes") or 0) > PAYLOAD_WARN_BYTES]
    routine_rows = [row for row in rows if "routine_save" in str(row.get("test_id") or "") or "routine_save" in [str(tool) for tool in row.get("actual_tool") or []]]
    prior_rows = _read_jsonl(PRIOR_FOCUSED_DIR / "focused_results.jsonl")
    old_latency_rows = _old_routine_save_latency_rows()
    summary = {
        "run_context": {
            "output_dir": str(output_dir),
            "process_isolated": True,
            "input_boundary": "POST /chat/send",
            "process_scope": process_scope,
            "history_strategy": history_strategy,
            "timeout_seconds": timeout_seconds,
            "dry_run": True,
            "provider_disabled": True,
            "real_external_actions_disabled": True,
        },
        "artifact_preservation": {
            "payload_routine_hardening": str(PAYLOAD_HARDENING_DIR),
            "prior_focused_80": str(PRIOR_FOCUSED_DIR),
            "old_95_case_latency_micro_suite": str(OLD_LATENCY_DIR),
        },
        "attempted_requests": attempted,
        "completed_requests": len(rows),
        "harness_result_count": result_count,
        "durable_rows": _line_count(output_dir / "focused_80_results.jsonl"),
        "completed_equals_durable_rows": len(rows) == _line_count(output_dir / "focused_80_results.jsonl"),
        "checkpoint": checkpoint,
        "checkpoint_rows": int(checkpoint.get("completed") or 0),
        "safety": {
            "provider_calls": provider_calls,
            "real_external_actions": external_actions,
            "hard_timeouts": len(hard_timeouts),
            "process_kills": sum(1 for row in rows if row.get("process_killed")),
            "orphan_process_check": _orphan_process_check_result(),
        },
        "raw_counts": {
            "pass": sum(1 for row in rows if row.get("passed")),
            "fail": sum(1 for row in rows if not row.get("passed")),
            "excluded": len(excluded),
        },
        "scored_counts": {
            "pass": sum(1 for row in scored if row.get("passed")),
            "fail": len(scored_failed),
            "excluded": len(excluded),
        },
        "excluded_cases": [
            {
                "test_id": row.get("test_id"),
                "expected_route_family": row.get("expected_route_family"),
                "expected_tool": row.get("expected_tool"),
                "reason": row.get("scoring_note"),
                "failure_category": row.get("failure_category"),
            }
            for row in excluded
        ],
        "raw_failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in failed).items())),
        "scored_failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in scored_failed).items())),
        "excluded_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in excluded_failed).items())),
        "failure_category_accounting_note": (
            "Raw counts include every failed durable row; scored counts include only rows included by the feature-map audit; "
            "excluded counts include failed rows excluded from normal scoring."
        ),
        "route_family_coverage": {
            "expected": dict(sorted(Counter(str(row.get("expected_route_family") or "") for row in rows).items())),
            "actual": dict(sorted(Counter(str(row.get("actual_route_family") or "") for row in rows).items())),
        },
        "expected_vs_actual_route_confusion_matrix": route_confusion,
        "generic_fallback_count_by_expected_family": dict(sorted(Counter(str(row.get("expected_route_family") or "") for row in rows if row.get("actual_route_family") == "generic_provider").items())),
        "wrong_subsystem_table": wrong_subsystem_rows,
        "top_20_failures_by_severity": [_failure_row(row) for row in sorted(failed, key=_failure_sort_key)[:20]],
        "latency_summary": _stats(latencies),
        "slowest_20": [_compact_row(row) for row in sorted(rows, key=lambda row: float(row.get("latency_ms") or 0.0), reverse=True)[:20]],
        "payload_summary": {
            "response_json_bytes": _stats(response_sizes),
            "max_workspace_item_count": max(workspace_counts) if workspace_counts else 0,
            "payload_guardrail_failures": payload_failures,
            "payload_warning_rows_above_1mb": payload_warnings,
            "top_largest_payload_rows": [_compact_row(row) for row in sorted(rows, key=lambda row: int(row.get("response_json_bytes") or 0), reverse=True)[:20]],
        },
        "routine_save_behavior": _routine_save_summary(routine_rows, old_latency_rows),
        "missing_telemetry_summary": _missing_telemetry_summary(rows, feature_audit),
        "comparison_against_prior_focused_isolated_rerun": _comparison(prior_rows, rows),
        "feature_map_audit_summary": feature_audit.get("summary", {}),
    }
    summary["recommendation"] = _recommendation(summary)
    return summary


def _build_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Focused-80 Post-Hardening Checkpoint",
            "",
            "## 1. Executive Summary",
            f"- attempted requests: {summary['attempted_requests']}",
            f"- completed requests: {summary['completed_requests']}",
            f"- durable rows: {summary['durable_rows']}",
            f"- scored pass/fail/excluded: {summary['scored_counts']}",
            f"- recommendation: {summary['recommendation']}",
            "",
            "## 2. Safety Summary",
            _format_dict(summary["safety"]),
            "",
            "## 3. Harness Durability",
            f"- attempted requests: {summary['attempted_requests']}",
            f"- completed requests: {summary['completed_requests']}",
            f"- durable rows: {summary['durable_rows']}",
            f"- completed equals durable rows: {summary['completed_equals_durable_rows']}",
            f"- checkpoint rows: {summary['checkpoint_rows']}",
            f"- checkpoint: {summary['checkpoint']}",
            "",
            "## 4. Raw And Scored Pass/Fail Counts",
            f"- raw: {summary['raw_counts']}",
            f"- scored: {summary['scored_counts']}",
            "",
            "## 5. Excluded Cases And Why",
            _format_rows(summary["excluded_cases"]),
            "",
            "## 6. Failure Category Counts",
            f"- note: {summary['failure_category_accounting_note']}",
            "- raw_failure_category_counts:",
            _format_dict(summary["raw_failure_category_counts"]),
            "- scored_failure_category_counts:",
            _format_dict(summary["scored_failure_category_counts"]),
            "- excluded_category_counts:",
            _format_dict(summary["excluded_category_counts"]),
            "",
            "## 7. Route-Family Coverage",
            f"- expected: {summary['route_family_coverage']['expected']}",
            f"- actual: {summary['route_family_coverage']['actual']}",
            "",
            "## 8. Expected Vs Actual Route Confusion Matrix",
            _format_nested(summary["expected_vs_actual_route_confusion_matrix"]),
            "",
            "## 9. Generic Fallback Count By Expected Family",
            _format_dict(summary["generic_fallback_count_by_expected_family"]),
            "",
            "## 10. Wrong-Subsystem Table",
            _format_rows(summary["wrong_subsystem_table"][:40]),
            "",
            "## 11. Top 20 Failures By Severity",
            _format_rows(summary["top_20_failures_by_severity"]),
            "",
            "## 12. Latency Summary",
            _format_dict(summary["latency_summary"]),
            "",
            "### Slowest 20",
            _format_rows(summary["slowest_20"]),
            "",
            "## 13. Payload Summary",
            f"- response_json_bytes: {summary['payload_summary']['response_json_bytes']}",
            f"- max workspace_item_count: {summary['payload_summary']['max_workspace_item_count']}",
            f"- payload guardrail failures: {summary['payload_summary']['payload_guardrail_failures']}",
            f"- rows above 1 MB: {summary['payload_summary']['payload_warning_rows_above_1mb']}",
            "",
            "### Top Largest Payload Rows",
            _format_rows(summary["payload_summary"]["top_largest_payload_rows"]),
            "",
            "## 14. Routine-Save Behavior Summary",
            _format_dict(summary["routine_save_behavior"]),
            "",
            "## 15. Missing Telemetry Summary",
            _format_dict({key: value for key, value in summary["missing_telemetry_summary"].items() if key != "classified_rows"}),
            "",
            "### Missing Telemetry Classifications",
            _format_rows(summary["missing_telemetry_summary"].get("classified_rows", [])[:80]),
            "",
            "## 16. Comparison Against Prior Focused Isolated Rerun",
            _format_dict(summary["comparison_against_prior_focused_isolated_rerun"]),
            "",
            "## 17. Recommendation",
            f"- {summary['recommendation']}",
        ]
    ).strip() + "\n"


def _payload_diagnostic(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "case_index": row.get("case_index"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "status": row.get("status"),
        "result_state": row.get("result_state"),
        "latency_ms": row.get("latency_ms"),
        "response_json_bytes": row.get("response_json_bytes"),
        "workspace_item_count": row.get("workspace_item_count"),
        "active_context_bytes": row.get("active_context_bytes"),
        "active_context_item_count": row.get("active_context_item_count"),
        "truncated_workspace_items": row.get("truncated_workspace_items"),
        "payload_guardrail_triggered": row.get("payload_guardrail_triggered"),
        "payload_guardrail_reason": row.get("payload_guardrail_reason"),
        "largest_payload_fields": row.get("largest_payload_fields"),
        "payload_guardrail_failure": int(row.get("response_json_bytes") or 0) > PAYLOAD_FAIL_BYTES,
    }


def _route_confusion_matrix(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        matrix[str(row.get("expected_route_family") or "")][str(row.get("actual_route_family") or "")] += 1
    return {expected: dict(sorted(actuals.items())) for expected, actuals in sorted(matrix.items())}


def _routine_save_summary(rows: list[dict[str, Any]], old_latency_rows: list[dict[str, Any]]) -> dict[str, Any]:
    no_context = [row for row in rows if "no_context" in str(row.get("test_id") or "") or not row.get("actual_tool")]
    active = [row for row in rows if "routine_save" in [str(tool) for tool in row.get("actual_tool") or []]]
    latencies = [float(row.get("latency_ms") or 0.0) for row in rows]
    return {
        "focused_80_routine_save_rows": len(rows),
        "no_context_rows": [_compact_row(row) for row in no_context],
        "active_context_rows": [_compact_row(row) for row in active],
        "historical_blocker_labels_present": sorted({label for row in rows for label in row.get("historical_blocker_labels") or []}),
        "old_catastrophic_pattern_reappeared": any(float(row.get("latency_ms") or 0.0) >= 43_000 for row in rows),
        "focused_latency_summary_ms": _stats(latencies),
        "old_95_case_latency_summary_ms": _stats([float(row.get("latency_ms") or 0.0) for row in old_latency_rows]),
        "old_blocker_status": "known_unreproduced_product_latency_blocker",
    }


def _missing_telemetry_summary(rows: list[dict[str, Any]], feature_audit: dict[str, Any]) -> dict[str, Any]:
    classified = []
    for row in rows:
        missing_route = not bool(row.get("route_state"))
        missing_obedience = bool(row.get("actual_tool")) and not bool(row.get("planner_obedience"))
        if not missing_route and not missing_obedience:
            continue
        expected_family = str(row.get("expected_route_family") or "")
        route_entry = dict(feature_audit.get("route_families", {}).get(expected_family) or {})
        route_surface_type = _route_surface_type(route_entry)
        classified.append(
            {
                "case_id": row.get("test_id"),
                "expected_family": expected_family,
                "actual_family": row.get("actual_route_family"),
                "route_surface_type": route_surface_type,
                "route_state_missing": missing_route,
                "planner_obedience_missing": missing_obedience,
                "route_state_should_be_required": route_surface_type == "planner",
                "planner_obedience_should_be_required": bool(row.get("actual_tool")) and route_surface_type == "planner",
                "reason": route_entry.get("scoring_note") or route_entry.get("evidence_summary") or "",
            }
        )
    return {
        "missing_route_state": sum(1 for row in rows if not row.get("route_state")),
        "missing_planner_obedience": sum(1 for row in rows if row.get("actual_tool") and not row.get("planner_obedience")),
        "classified_rows": classified,
    }


def _route_surface_type(route_entry: dict[str, Any]) -> str:
    classification = str(route_entry.get("classification") or "")
    if classification == "implemented_direct_only":
        return "direct"
    if classification in {"docs_only", "scaffold_only"}:
        return "excluded"
    if "legacy" in classification:
        return "legacy"
    return "planner"


def _comparison(prior_rows: list[dict[str, Any]], current_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "prior_artifact_path": str(PRIOR_FOCUSED_DIR / "focused_results.jsonl"),
        "prior_rows": len(prior_rows),
        "current_rows": len(current_rows),
        "pass_fail_before": _pass_fail_counts(prior_rows),
        "pass_fail_after": _pass_fail_counts(current_rows),
        "latency_before_ms": _stats([float(row.get("latency_ms") or 0.0) for row in prior_rows]),
        "latency_after_ms": _stats([float(row.get("latency_ms") or 0.0) for row in current_rows]),
        "generic_fallback_before": dict(sorted(Counter(str(row.get("expected_route_family") or "") for row in prior_rows if row.get("actual_route_family") == "generic_provider").items())),
        "generic_fallback_after": dict(sorted(Counter(str(row.get("expected_route_family") or "") for row in current_rows if row.get("actual_route_family") == "generic_provider").items())),
        "payload_before_bytes": _stats([float(row.get("response_json_bytes") or 0.0) for row in prior_rows]),
        "payload_after_bytes": _stats([float(row.get("response_json_bytes") or 0.0) for row in current_rows]),
        "routine_save_before": _routine_brief(prior_rows),
        "routine_save_after": _routine_brief(current_rows),
    }


def _recommendation(summary: dict[str, Any]) -> str:
    if summary["attempted_requests"] != 80 or summary["durable_rows"] != 80:
        return "fix harness before broader evaluation"
    if not summary["completed_equals_durable_rows"] or summary["safety"]["orphan_process_check"] != "no_orphan_command_eval_processes_detected":
        return "fix harness before broader evaluation"
    if summary["safety"]["real_external_actions"] or summary["safety"]["provider_calls"]:
        return "fix safety/provider isolation before broader evaluation"
    if summary["payload_summary"]["payload_guardrail_failures"]:
        return "fix latency/payload before broader evaluation"
    scored_categories = summary["scored_failure_category_counts"]
    if scored_categories.get("real_routing_gap") or scored_categories.get("wrong_subsystem"):
        return "fix routing before 250; focused-80 is durable and safe but still exposes native routing failures"
    if scored_categories.get("corpus_expectation_bug") or scored_categories.get("feature_map_overexpectation"):
        return "fix corpus expectations before 250"
    if summary["scored_counts"]["fail"]:
        return "triage focused failures before 250"
    return "proceed to 250 with hard-timeout containment and routine_save historical blocker label preserved"


def _failure_sort_key(row: dict[str, Any]) -> tuple[int, float]:
    severity = {
        "hard_timeout": 0,
        "payload_guardrail_failure": 1,
        "truthfulness_failure": 2,
        "real_routing_gap": 3,
        "wrong_subsystem": 4,
        "latency_issue": 5,
        "missing_telemetry": 6,
        "response_correctness_failure": 7,
        "corpus_expectation_bug": 8,
        "feature_map_overexpectation": 9,
        "known_blocker_lane": 10,
        "harness_bug": 0,
    }.get(str(row.get("failure_category") or ""), 20)
    return (severity, -float(row.get("latency_ms") or 0.0))


def _failure_row(row: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_row(row)
    compact["failure_category"] = row.get("failure_category")
    compact["failure_reason"] = row.get("failure_reason")
    compact["severity"] = _failure_sort_key(row)[0]
    return compact


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "input": row.get("prompt") or row.get("input"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "expected_subsystem": row.get("expected_subsystem"),
        "actual_subsystem": row.get("actual_subsystem"),
        "expected_tool": row.get("expected_tool"),
        "actual_tool": row.get("actual_tool"),
        "result_state": row.get("result_state"),
        "status": row.get("status"),
        "latency_ms": row.get("latency_ms"),
        "response_json_bytes": row.get("response_json_bytes"),
        "workspace_item_count": row.get("workspace_item_count"),
        "payload_guardrail_reason": row.get("payload_guardrail_reason"),
        "historical_blocker_labels": row.get("historical_blocker_labels"),
    }


def _old_routine_save_latency_rows() -> list[dict[str, Any]]:
    return [
        row
        for row in _read_jsonl(OLD_LATENCY_DIR / "latency_micro_results.jsonl")
        if "routine_save" in str(row.get("test_id") or "")
    ]


def _routine_brief(rows: list[dict[str, Any]]) -> dict[str, Any]:
    routine = [row for row in rows if "routine_save" in str(row.get("test_id") or "") or "routine_save" in [str(tool) for tool in row.get("actual_tool") or []]]
    return {
        "rows": len(routine),
        "actual_routes": dict(sorted(Counter(str(row.get("actual_route_family") or "") for row in routine).items())),
        "latency_ms": _stats([float(row.get("latency_ms") or 0.0) for row in routine]),
        "generic_provider_fallbacks": sum(1 for row in routine if row.get("actual_route_family") == "generic_provider"),
    }


def _pass_fail_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "pass": sum(1 for row in rows if row.get("passed")),
        "fail": sum(1 for row in rows if not row.get("passed")),
        "excluded": sum(1 for row in rows if not row.get("score_in_pass_fail", True)),
    }


def _stats(values: list[float]) -> dict[str, Any]:
    sorted_values = sorted(float(value) for value in values)
    if not sorted_values:
        return {"count": 0, "min": None, "median": None, "p90": None, "p95": None, "max": None}
    return {
        "count": len(sorted_values),
        "min": round(sorted_values[0], 3),
        "median": round(median(sorted_values), 3),
        "p90": _percentile(sorted_values, 0.9),
        "p95": _percentile(sorted_values, 0.95),
        "max": round(sorted_values[-1], 3),
    }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)
    index = min(len(sorted_values) - 1, max(0, int(round((len(sorted_values) - 1) * fraction))))
    return round(sorted_values[index], 3)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
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


def _format_dict(payload: dict[str, Any]) -> str:
    if not payload:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in payload.items())


def _format_nested(payload: dict[str, dict[str, Any]]) -> str:
    if not payload:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in payload.items())


def _format_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- none"
    return "\n".join(f"- `{row.get('test_id') or row.get('case_id') or '<row>'}`: {row}" for row in rows)


if __name__ == "__main__":
    main()
