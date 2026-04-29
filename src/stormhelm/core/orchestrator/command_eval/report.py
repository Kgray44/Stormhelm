from __future__ import annotations

import json
from collections import Counter
from collections import defaultdict
from pathlib import Path
from typing import Any

from .models import CommandEvalCase
from .models import CommandEvalResult
from .models import STAGE_LATENCY_FIELDS
from .models import json_ready


_L44_INLINE_CORRECT_ROUTES = {
    "browser_destination",
    "calculations",
    "trust_approvals",
    "voice_control",
}

_L44_EXPECTED_HANDLER_STATUS = {
    "workspace.assemble_deep": {
        "route_family": "workspace_operations",
        "desired_status": "converted",
        "current_async_status": "continuation_handler_implemented",
    },
    "workspace.restore_deep": {
        "route_family": "workspace_operations",
        "desired_status": "converted",
        "current_async_status": "continuation_handler_implemented",
    },
    "software_control.verify_operation": {
        "route_family": "software_control",
        "desired_status": "converted",
        "current_async_status": "continuation_handler_implemented",
    },
    "software_recovery.run_recovery_plan": {
        "route_family": "software_recovery",
        "desired_status": "converted",
        "current_async_status": "continuation_handler_implemented",
    },
    "discord_relay.dispatch_approved_preview": {
        "route_family": "discord_relay",
        "desired_status": "converted",
        "current_async_status": "continuation_handler_implemented",
    },
    "network.run_live_diagnosis": {
        "route_family": "network",
        "desired_status": "converted",
        "current_async_status": "continuation_handler_implemented",
    },
    "screen_awareness.verify_change": {
        "route_family": "screen_awareness",
        "desired_status": "candidate",
        "current_async_status": "continuation_handler_missing",
        "missing_reason": "no_clean_worker_seam",
    },
    "software_control.execute_approved_operation": {
        "route_family": "software_control",
        "desired_status": "later",
        "current_async_status": "needs_trust_seam_first",
        "missing_reason": "unsafe_without_trust_boundary",
    },
}

_L44_ROUTE_DESIRED_STATUS = {
    "browser_destination": "inline",
    "calculations": "inline",
    "discord_relay": "converted_dispatch_only",
    "network": "converted_live_diagnosis",
    "provider_fallback": "provider_wait",
    "screen_awareness": "candidate",
    "software_control": "converted_verify_only",
    "software_recovery": "converted",
    "trust_approvals": "inline",
    "voice_control": "inline",
    "workspace_operations": "converted_deep_work",
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_ready(payload), indent=2, sort_keys=True, default=str), encoding="utf-8")


def write_jsonl(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(json_ready(row), sort_keys=True, default=str) + "\n")


def build_summary(results: list[CommandEvalResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    scored_results = [result for result in results if result.score_in_pass_fail]
    scored_passed = sum(1 for result in scored_results if result.passed)
    by_expected = Counter(result.case.expected.route_family for result in results)
    by_actual = Counter(result.observation.actual_route_family or "<none>" for result in results)
    latency: dict[str, list[float]] = defaultdict(list)
    for result in results:
        latency[result.case.expected.route_family].append(result.observation.latency_ms)
    latency_summary = {
        family: {
            "count": len(values),
            "min_ms": round(min(values), 3),
            "max_ms": round(max(values), 3),
            "avg_ms": round(sum(values) / len(values), 3),
        }
        for family, values in sorted(latency.items())
        if values
    }
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for result in results:
        confusion[result.case.expected.route_family][result.observation.actual_route_family or "<none>"] += 1
    false_success = [
        result
        for result in results
        if not result.assertions["no_overclaim"].passed
        or (
            result.observation.result_state in {"completed", "dry_run"}
            and not result.assertions["route_family"].passed
        )
    ]
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0,
        "scored_total": len(scored_results),
        "scored_passed": scored_passed,
        "scored_failed": len(scored_results) - scored_passed,
        "scored_pass_rate": round(scored_passed / len(scored_results), 4) if scored_results else 0,
        "expected_route_family_counts": dict(sorted(by_expected.items())),
        "actual_route_family_counts": dict(sorted(by_actual.items())),
        "confusion_matrix": {expected: dict(actuals) for expected, actuals in sorted(confusion.items())},
        "latency_by_route_family": latency_summary,
        "false_success_or_false_verification_count": len(false_success),
        "failure_category_counts": dict(sorted(Counter(result.failure_category for result in results).items())),
    }


def build_checkpoint_summary(results: list[CommandEvalResult], *, feature_audit: dict[str, Any] | None = None) -> dict[str, Any]:
    scored = [result for result in results if result.score_in_pass_fail]
    failures = [result for result in scored if not result.passed]
    all_failures = [result for result in results if not result.passed]
    excluded_failures = [result for result in all_failures if not result.score_in_pass_fail]
    latencies = sorted(float(result.observation.latency_ms) for result in results)
    pass_fail_by_family: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "failed": 0, "excluded": 0})
    fallback_by_expected = Counter()
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    missing_telemetry_rows: list[dict[str, Any]] = []
    for result in results:
        family = result.case.expected.route_family
        if not result.score_in_pass_fail:
            pass_fail_by_family[family]["excluded"] += 1
        elif result.passed:
            pass_fail_by_family[family]["passed"] += 1
        else:
            pass_fail_by_family[family]["failed"] += 1
        if result.observation.actual_route_family == "generic_provider":
            fallback_by_expected[family] += 1
        if result.observation.actual_subsystem != result.case.expected.subsystem:
            confusion[result.case.expected.subsystem][result.observation.actual_subsystem or "<none>"] += 1
        missing_telemetry_rows.extend(_missing_telemetry_classifications(result, feature_audit=feature_audit))
    raw_failure_category_counts = Counter(result.failure_category for result in all_failures)
    scored_failure_category_counts = Counter(result.failure_category for result in failures)
    excluded_category_counts = Counter(result.failure_category for result in excluded_failures)
    return {
        "completed_requests": len(results),
        "durable_assertion_rows": len(results),
        "raw_passed": sum(1 for result in results if result.passed),
        "raw_failed": sum(1 for result in results if not result.passed),
        "scored_total": len(scored),
        "scored_passed": sum(1 for result in scored if result.passed),
        "scored_failed": len(failures),
        "excluded_from_scoring": len(results) - len(scored),
        "pass_fail_by_route_family": {family: dict(counts) for family, counts in sorted(pass_fail_by_family.items())},
        "generic_fallback_count_by_expected_family": dict(sorted(fallback_by_expected.items())),
        "wrong_subsystem_confusion_matrix": {expected: dict(actuals) for expected, actuals in sorted(confusion.items())},
        "failure_category_counts": dict(sorted(raw_failure_category_counts.items())),
        "raw_failure_category_counts": dict(sorted(raw_failure_category_counts.items())),
        "scored_failure_category_counts": dict(sorted(scored_failure_category_counts.items())),
        "excluded_category_counts": dict(sorted(excluded_category_counts.items())),
        "failure_category_accounting_note": (
            "raw_failure_category_counts includes every failed durable row; "
            "scored_failure_category_counts includes only rows included in pass/fail scoring; "
            "excluded_category_counts covers failed rows excluded by the feature-map audit."
        ),
        "latency_ms": {
            "min": _percentile(latencies, 0.0),
            "p50": _percentile(latencies, 0.5),
            "median": _percentile(latencies, 0.5),
            "p90": _percentile(latencies, 0.9),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
            "max": _percentile(latencies, 1.0),
        },
        "stage_latency_summary": _stage_latency_summary(results),
        "kraken_latency_report": _kraken_latency_report(results),
        "unattributed_latency": {
            "top_20": _top_unattributed(results),
            "by_route_family": _unattributed_by_route_family(results),
            "repeated_case_variance": _unattributed_repeated_case_variance(results),
        },
        "slowest_20_requests": [_compact_result(result) for result in sorted(results, key=lambda item: item.observation.latency_ms, reverse=True)[:20]],
        "top_20_failures_by_severity": [_compact_failure(result) for result in sorted(all_failures, key=_failure_sort_key)[:20]],
        "first_20_failures": [_compact_failure(result) for result in all_failures[:20]],
        "missing_telemetry": {
            "missing_route_state": sum(1 for result in results if not result.observation.route_state),
            "missing_planner_obedience_for_tool_rows": sum(1 for result in results if result.observation.tool_chain and not result.observation.planner_obedience),
            "classified_rows": missing_telemetry_rows,
        },
        "feature_map_audit_summary": (feature_audit or {}).get("summary", {}),
        "recommendation": _recommendation(results),
    }


def build_checkpoint_report(
    *,
    title: str,
    results: list[CommandEvalResult],
    feature_audit: dict[str, Any] | None = None,
) -> str:
    summary = build_checkpoint_summary(results, feature_audit=feature_audit)
    lines = [
        f"# {title}",
        "",
        "## Pass/Fail Counts",
        f"- completed requests: {summary['completed_requests']}",
        f"- durable assertion rows: {summary['durable_assertion_rows']}",
        f"- scored pass/fail: {summary['scored_passed']} passed, {summary['scored_failed']} failed, {summary['excluded_from_scoring']} excluded",
        f"- raw pass/fail: {summary['raw_passed']} passed, {summary['raw_failed']} failed",
        "",
        "## Pass/Fail By Route Family",
        _format_nested_counts(summary["pass_fail_by_route_family"]),
        "",
        "## Generic Fallback Count By Expected Family",
        _format_counts(summary["generic_fallback_count_by_expected_family"]),
        "",
        "## Wrong-Subsystem Confusion Matrix",
        _format_nested_counts(summary["wrong_subsystem_confusion_matrix"]),
        "",
        "## Failure Category Accounting",
        f"- {summary['failure_category_accounting_note']}",
        "- raw failure categories:",
        _format_counts(summary["raw_failure_category_counts"]),
        "- scored failure categories:",
        _format_counts(summary["scored_failure_category_counts"]),
        "- excluded failure categories:",
        _format_counts(summary["excluded_category_counts"]),
        "",
        "## Top 20 Failures By Severity",
        _compact_failure_table(summary["top_20_failures_by_severity"]),
        "",
        "## Latency Summary",
        _format_counts({key: round(value, 3) if value is not None else None for key, value in summary["latency_ms"].items()}),
        "",
        "## Per-Stage Latency Summary",
        _format_nested_counts(summary["stage_latency_summary"]),
        "",
        "## Kraken Latency Report",
        _format_kraken_latency_report(summary["kraken_latency_report"]),
        "",
        "## Slowest 20 Requests",
        _compact_result_table(summary["slowest_20_requests"]),
        "",
        "## Unattributed Latency",
        "Top 20 rows by `unattributed_latency_ms`:",
        _compact_result_table(summary["unattributed_latency"]["top_20"]),
        "",
        "Route-family unattributed latency summary:",
        _format_nested_counts(summary["unattributed_latency"]["by_route_family"]),
        "",
        "Repeated-case unattributed variance:",
        _format_nested_counts(summary["unattributed_latency"]["repeated_case_variance"]),
        "",
        "## Missing Telemetry Summary",
        _format_counts({key: value for key, value in summary["missing_telemetry"].items() if key != "classified_rows"}),
        "",
        "### Missing Telemetry Classifications",
        _missing_telemetry_table(summary["missing_telemetry"].get("classified_rows", [])),
        "",
        "## Feature-Map Audit Summary",
        _format_counts(summary["feature_map_audit_summary"].get("classification_counts", {})),
        f"- included in scoring: {summary['feature_map_audit_summary'].get('include_in_scoring_count', 0)}",
        f"- excluded from scoring: {summary['feature_map_audit_summary'].get('excluded_from_scoring_count', 0)}",
        "",
        "## Recommendation",
        f"- {summary['recommendation']}",
    ]
    return "\n".join(lines).strip() + "\n"


def build_findings_report(
    *,
    feature_map_path: Path,
    corpus_path: Path,
    focused_results_path: Path,
    full_results_path: Path,
    results: list[CommandEvalResult],
) -> str:
    summary = build_summary(results)
    failures = [result for result in results if not result.passed]
    routing_failures = [result for result in failures if not result.assertions["route_family"].passed]
    wrong_tool = [result for result in failures if not result.assertions["tool_chain"].passed]
    clarification = [result for result in failures if not result.assertions["clarification"].passed]
    approval = [result for result in failures if not result.assertions["approval"].passed]
    no_overclaim = [result for result in failures if not result.assertions["no_overclaim"].passed]
    fuzzy = [result for result in failures if {"typo", "casual", "near_miss", "cross_family"} & set(result.case.tags)]
    deictic = [result for result in failures if {"deictic", "follow_up", "correction"} & set(result.case.tags)]
    lines = [
        "# Stormhelm Command Usability And Routing Evaluation",
        "",
        "## 1. Executive Summary",
        f"- Total cases: {summary['total']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        f"- Pass rate: {summary['pass_rate']:.2%}",
        f"- False-success / false-verification candidates: {summary['false_success_or_false_verification_count']}",
        "",
        "## 2. Coverage Summary",
        f"- Feature map: `{feature_map_path}`",
        f"- Corpus: `{corpus_path}`",
        f"- Focused results: `{focused_results_path}`",
        f"- Full results: `{full_results_path}`",
        f"- Expected route families: {', '.join(summary['expected_route_family_counts'])}",
        "",
        "## 3. Feature/Subsystem Coverage Matrix",
        _format_counts(summary["expected_route_family_counts"]),
        "",
        "## 4. Pass/Fail Totals",
        _format_counts({"passed": summary["passed"], "failed": summary["failed"]}),
        "",
        "## 5. Good Findings",
        _good_findings(results),
        "",
        "## 6. Bad Findings",
        _failure_table(failures[:40]),
        "",
        "## 7. Routing Failures",
        _failure_table(routing_failures[:40]),
        "",
        "## 8. Wrong-Tool / Wrong-Subsystem Failures",
        _failure_table(wrong_tool[:40]),
        "",
        "## 9. Fuzzy-Language Weaknesses",
        _failure_table(fuzzy[:40]),
        "",
        "## 10. Clarification Failures",
        _failure_table(clarification[:40]),
        "",
        "## 11. Deictic/Follow-Up Failures",
        _failure_table(deictic[:40]),
        "",
        "## 12. Result-State And Truthfulness Failures",
        _failure_table(no_overclaim[:40]),
        "",
        "## 13. Chain-Order Failures",
        _failure_table(wrong_tool[:40]),
        "",
        "## 14. Latency/Performance Findings",
        _latency_findings(summary["latency_by_route_family"]),
        "",
        "## 15. UI-Facing Response/Copy Issues",
        _copy_findings(failures),
        "",
        "## 16. Telemetry/Debug Gaps",
        _telemetry_findings(results),
        "",
        "## 17. Safety/Approval/Policy Issues",
        _failure_table(approval[:40]),
        "",
        "## 18. Top Recommended Fixes",
        _recommended_fixes(routing_failures, wrong_tool, clarification, deictic, no_overclaim),
        "",
        "## 19. Suggested Regression Suite",
        _suggested_regression_suite(failures),
        "",
        "## 20. Full Request-Level Appendix",
        "The complete machine-readable appendix is in the full results JSONL. Representative failures are listed above with IDs, expected and actual route/tool state, response, latency, severity, likely fix area, and reproduction path.",
    ]
    return "\n".join(lines).strip() + "\n"


def write_artifacts(
    *,
    output_dir: Path,
    feature_map: dict[str, Any],
    corpus: list[CommandEvalCase],
    focused_results: list[CommandEvalResult],
    full_results: list[CommandEvalResult],
    feature_audit: dict[str, Any] | None = None,
) -> dict[str, Path]:
    paths = {
        "feature_map": output_dir / "feature_map.json",
        "corpus": output_dir / "corpus.jsonl",
        "focused_results": output_dir / "focused_results.jsonl",
        "full_results": output_dir / "full_results.jsonl",
        "summary": output_dir / "summary.json",
        "findings": output_dir / "final_findings.md",
        "feature_audit": output_dir / "feature_map_audit.json",
        "focused_checkpoint_summary": output_dir / "focused_checkpoint_summary.json",
        "focused_checkpoint_report": output_dir / "focused_checkpoint_report.md",
        "full_checkpoint_summary": output_dir / "full_checkpoint_summary.json",
        "full_checkpoint_report": output_dir / "full_checkpoint_report.md",
    }
    write_json(paths["feature_map"], feature_map)
    if feature_audit is not None:
        write_json(paths["feature_audit"], feature_audit)
    write_jsonl(paths["corpus"], [case.to_dict() for case in corpus])
    write_jsonl(paths["focused_results"], [result.to_dict() for result in focused_results])
    write_jsonl(paths["full_results"], [result.to_dict() for result in full_results])
    summary = build_summary(full_results)
    write_json(paths["summary"], summary)
    write_json(paths["focused_checkpoint_summary"], build_checkpoint_summary(focused_results, feature_audit=feature_audit))
    paths["focused_checkpoint_report"].write_text(
        build_checkpoint_report(
            title="Stormhelm Focused Command Evaluation Checkpoint",
            results=focused_results,
            feature_audit=feature_audit,
        ),
        encoding="utf-8",
    )
    write_json(paths["full_checkpoint_summary"], build_checkpoint_summary(full_results, feature_audit=feature_audit))
    paths["full_checkpoint_report"].write_text(
        build_checkpoint_report(
            title="Stormhelm Command Evaluation Checkpoint",
            results=full_results,
            feature_audit=feature_audit,
        ),
        encoding="utf-8",
    )
    paths["findings"].write_text(
        build_findings_report(
            feature_map_path=paths["feature_map"],
            corpus_path=paths["corpus"],
            focused_results_path=paths["focused_results"],
            full_results_path=paths["full_results"],
            results=full_results,
        ),
        encoding="utf-8",
    )
    return paths


def _format_counts(counts: dict[str, Any]) -> str:
    if not counts:
        return "- No data."
    return "\n".join(f"- {key}: {value}" for key, value in counts.items())


def _format_nested_counts(counts: dict[str, dict[str, Any]]) -> str:
    if not counts:
        return "- No data."
    return "\n".join(f"- {key}: {dict(value)}" for key, value in counts.items())


def _format_kraken_latency_report(report: dict[str, Any]) -> str:
    if not report:
        return "- No data."
    lines = [
        f"- total_latency_ms: {report.get('total_latency_ms', {})}",
        f"- budget_exceeded_count: {report.get('budget_exceeded_count', 0)}",
        f"- budget_exceeded_continuing_count: {report.get('budget_exceeded_continuing_count', 0)}",
        f"- hard_timeout_count: {report.get('hard_timeout_count', 0)}",
        f"- provider_call_count: {report.get('provider_call_count', 0)}",
        f"- partial_response_count: {report.get('partial_response_count', 0)}",
        f"- async_initial_response_count: {report.get('async_initial_response_count', 0)}",
        f"- progress_event_count: {report.get('progress_event_count', 0)}",
        f"- job_required_count: {report.get('job_required_count', 0)}",
        f"- task_required_count: {report.get('task_required_count', 0)}",
        f"- event_progress_required_count: {report.get('event_progress_required_count', 0)}",
        f"- converted_subsystem_route_count: {report.get('converted_subsystem_route_count', 0)}",
        f"- conversion_count_by_route_family: {report.get('conversion_count_by_route_family', {})}",
        f"- expected_conversion_missing_count: {report.get('expected_conversion_missing_count', 0)}",
        f"- implemented_handler_count: {report.get('implemented_handler_count', 0)}",
        f"- handler_count_by_route_family: {report.get('handler_count_by_route_family', {})}",
        f"- missing_handler_count_by_reason: {report.get('missing_handler_count_by_reason', {})}",
        f"- conversion_success_count: {report.get('conversion_success_count', 0)}",
        f"- unsafe_claim_count_by_handler: {report.get('unsafe_claim_count_by_handler', {})}",
        f"- p95_continuation_runtime_by_handler: {report.get('p95_continuation_runtime_by_handler', {})}",
        f"- p95_inline_front_half_ms: {report.get('p95_inline_front_half_ms')}",
        f"- p95_worker_back_half_ms: {report.get('p95_worker_back_half_ms')}",
        f"- p95_continuation_queue_wait_ms: {report.get('p95_continuation_queue_wait_ms')}",
        f"- p95_continuation_run_ms: {report.get('p95_continuation_run_ms')}",
        f"- voice_first_audio_ms: {report.get('voice_first_audio_ms', {})}",
        f"- voice_core_to_first_audio_ms: {report.get('voice_core_to_first_audio_ms', {})}",
        f"- voice_streaming_enabled_count: {report.get('voice_streaming_enabled_count', 0)}",
        f"- voice_streaming_transport_kind_counts: {report.get('voice_streaming_transport_kind_counts', {})}",
        f"- voice_streaming_path_used_count: {report.get('voice_streaming_path_used_count', 0)}",
        f"- voice_buffered_projection_count: {report.get('voice_buffered_projection_count', 0)}",
        f"- normal_path_streaming_miss_count: {report.get('normal_path_streaming_miss_count', 0)}",
        f"- voice_first_chunk_before_complete_count: {report.get('voice_first_chunk_before_complete_count', 0)}",
        f"- voice_streaming_fallback_count: {report.get('voice_streaming_fallback_count', 0)}",
        f"- voice_prewarm_used_count: {report.get('voice_prewarm_used_count', 0)}",
        f"- voice_partial_playback_count: {report.get('voice_partial_playback_count', 0)}",
        f"- by_async_strategy: {report.get('by_async_strategy', {})}",
        f"- queue_wait_ms: {report.get('queue_wait_ms', {})}",
        f"- job_run_ms: {report.get('job_run_ms', {})}",
        f"- job_total_ms: {report.get('job_total_ms', {})}",
        f"- subsystem_cap_wait_ms: {report.get('subsystem_cap_wait_ms', {})}",
        f"- worker_lane_counts: {report.get('worker_lane_counts', {})}",
        f"- scheduler_strategy_counts: {report.get('scheduler_strategy_counts', {})}",
        f"- scheduler_pressure_state_counts: {report.get('scheduler_pressure_state_counts', {})}",
        f"- queue_wait_budget_exceeded_count: {report.get('queue_wait_budget_exceeded_count', 0)}",
        f"- subsystem_cap_wait_count: {report.get('subsystem_cap_wait_count', 0)}",
        f"- retry_policy_counts: {report.get('retry_policy_counts', {})}",
        f"- retry_count_total: {report.get('retry_count_total', 0)}",
        f"- saturation_event_count: {report.get('saturation_event_count', 0)}",
        f"- starvation_warning_count: {report.get('starvation_warning_count', 0)}",
        f"- async_strategy_by_worker_lane: {report.get('async_strategy_by_worker_lane', {})}",
        f"- background_job_impact_summary: {report.get('background_job_impact_summary', {})}",
        f"- fail_fast_count: {report.get('fail_fast_count', 0)}",
        f"- route_triage_ms: {report.get('route_triage_ms', {})}",
        f"- fast_path_hit_rate: {report.get('fast_path_hit_rate', 0)}",
        f"- fast_path_correctness_rate: {report.get('fast_path_correctness_rate', 0)}",
        f"- snapshot_hit_rate: {report.get('snapshot_hit_rate', 0)}",
        f"- snapshot_miss_count_by_family: {report.get('snapshot_miss_count_by_family', {})}",
        f"- stale_cautious_use_count: {report.get('stale_cautious_use_count', 0)}",
        f"- heavy_context_avoidance_count: {report.get('heavy_context_avoidance_count', 0)}",
        f"- snapshot_hit_vs_miss_latency: {report.get('snapshot_hit_vs_miss_latency', {})}",
        f"- invalidation_events_count: {report.get('invalidation_events_count', 0)}",
        f"- provider_fallback_suppressed_count: {report.get('provider_fallback_suppressed_count', 0)}",
        f"- native_route_protection_count: {report.get('native_route_protection_count', 0)}",
        f"- heavy_context_loaded_count_by_route_family: {report.get('heavy_context_loaded_count_by_route_family', {})}",
        f"- by_route_family: {report.get('by_route_family', {})}",
        f"- by_longest_stage: {report.get('by_longest_stage', {})}",
        f"- by_execution_mode: {report.get('by_execution_mode', {})}",
        f"- budget_exceeded_by_execution_mode: {report.get('budget_exceeded_by_execution_mode', {})}",
        f"- fail_fast_reasons: {report.get('fail_fast_reasons', {})}",
        "- top_10_slowest_rows:",
    ]
    for row in report.get("top_10_slowest_rows", [])[:10]:
        if not isinstance(row, dict):
            continue
        lines.append(
            "  - `{test_id}` {total_latency_ms} ms | {actual_route_family} | "
            "longest={longest_stage} {longest_stage_ms} ms | budget={budget_label} exceeded={budget_exceeded}".format(
                **{
                    "test_id": row.get("test_id", ""),
                    "total_latency_ms": row.get("total_latency_ms", 0),
                    "actual_route_family": row.get("actual_route_family", ""),
                    "longest_stage": row.get("longest_stage", ""),
                    "longest_stage_ms": row.get("longest_stage_ms", 0),
                    "budget_label": row.get("budget_label", ""),
                    "budget_exceeded": row.get("budget_exceeded", False),
                }
            )
        )
    for label in (
        "top_slow_instant_routes",
        "top_slow_plan_first_routes",
        "top_slow_async_first_acknowledgements",
        "sync_blocked_async_expected_rows",
        "top_slow_rows_with_snapshot_misses",
        "slowest_continuation_rows",
        "missing_conversion_rows",
        "unsafe_claim_rows",
    ):
        lines.append(f"- {label}:")
        for row in report.get(label, [])[:10]:
            if not isinstance(row, dict):
                continue
            lines.append(
                "  - `{test_id}` {total_latency_ms} ms | mode={execution_mode} | "
                "first_feedback={first_feedback_ms} ms | route={actual_route_family} | "
                "partial={partial_response_returned} async_expected={async_expected} "
                "fail_fast={fail_fast_reason}".format(
                    **{
                        "test_id": row.get("test_id", ""),
                        "total_latency_ms": row.get("total_latency_ms", 0),
                        "execution_mode": row.get("execution_mode", ""),
                        "first_feedback_ms": row.get("first_feedback_ms", ""),
                        "actual_route_family": row.get("actual_route_family", ""),
                        "partial_response_returned": row.get("partial_response_returned", False),
                        "async_expected": row.get("async_expected", False),
                        "fail_fast_reason": row.get("fail_fast_reason", ""),
                    }
                )
            )
    return "\n".join(lines)


def _missing_telemetry_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- None."
    lines: list[str] = []
    for row in rows:
        lines.append(
            "- `{case_id}` expected {expected_family} -> actual {actual_family}; surface={route_surface_type}; "
            "route_state_required={route_state_should_be_required}; planner_obedience_required={planner_obedience_should_be_required}; "
            "{reason}".format(**row)
        )
    return "\n".join(lines)


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 3)
    index = (len(values) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return round(values[lower] * (1 - fraction) + values[upper] * fraction, 3)


def _stage_latency_summary(results: list[CommandEvalResult]) -> dict[str, dict[str, float | int | None]]:
    summary: dict[str, dict[str, float | int | None]] = {}
    for field in (*STAGE_LATENCY_FIELDS, "unattributed_latency_ms"):
        values = sorted(float(result.to_dict().get(field) or 0.0) for result in results)
        if not values:
            summary[field] = {"count": 0, "min": None, "p50": None, "median": None, "p90": None, "p95": None, "p99": None, "max": None}
            continue
        summary[field] = {
            "count": len(values),
            "min": _percentile(values, 0.0),
            "p50": _percentile(values, 0.5),
            "median": _percentile(values, 0.5),
            "p90": _percentile(values, 0.9),
            "p95": _percentile(values, 0.95),
            "p99": _percentile(values, 0.99),
            "max": _percentile(values, 1.0),
        }
    return summary


def _kraken_latency_report(results: list[CommandEvalResult]) -> dict[str, Any]:
    rows = [
        result.to_dict() if hasattr(result, "to_dict") else dict(result)
        for result in results
    ]
    total_values = [float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0) for row in rows]
    by_route: dict[str, list[float]] = defaultdict(list)
    by_longest_stage: dict[str, list[float]] = defaultdict(list)
    by_execution_mode: dict[str, list[float]] = defaultdict(list)
    by_async_strategy: dict[str, list[float]] = defaultdict(list)
    async_strategy_by_worker_lane: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    queue_wait_values: list[float] = []
    job_run_values: list[float] = []
    job_total_values: list[float] = []
    subsystem_cap_wait_values: list[float] = []
    worker_lane_counts: Counter[str] = Counter()
    scheduler_strategy_counts: Counter[str] = Counter()
    scheduler_pressure_counts: Counter[str] = Counter()
    retry_policy_counts: Counter[str] = Counter()
    cancellation_state_counts: Counter[str] = Counter()
    yield_state_counts: Counter[str] = Counter()
    restart_recovery_state_counts: Counter[str] = Counter()
    queue_wait_budget_exceeded_count = 0
    subsystem_cap_wait_count = 0
    retry_count_total = 0
    triage_values: list[float] = []
    heavy_context_by_route: dict[str, int] = defaultdict(int)
    budget_by_execution_mode: Counter[str] = Counter()
    fast_path_rows = 0
    fast_path_correct = 0
    snapshot_hit_rows = 0
    snapshot_miss_by_family: Counter[str] = Counter()
    snapshot_hit_latencies: list[float] = []
    snapshot_miss_latencies: list[float] = []
    cache_benefit_by_route: Counter[str] = Counter()
    stale_cautious_use_count = 0
    heavy_context_avoidance_count = 0
    invalidation_events_count = 0
    async_initial_response_count = 0
    progress_event_count = 0
    job_required_count = 0
    task_required_count = 0
    event_progress_required_count = 0
    saturation_event_count = 0
    starvation_warning_count = 0
    background_job_rows = 0
    background_job_latency: list[float] = []
    converted_subsystem_route_count = 0
    conversion_by_route: Counter[str] = Counter()
    expected_conversion_missing_count = 0
    inline_front_half_values: list[float] = []
    worker_back_half_values: list[float] = []
    continuation_queue_wait_values: list[float] = []
    continuation_run_values: list[float] = []
    continuation_total_values: list[float] = []
    implemented_handler_count = 0
    handler_count_by_route: Counter[str] = Counter()
    missing_handler_by_reason: Counter[str] = Counter()
    conversion_success_count = 0
    unsafe_claim_by_handler: Counter[str] = Counter()
    continuation_runtime_by_handler: dict[str, list[float]] = defaultdict(list)
    voice_first_audio_values: list[float] = []
    voice_core_to_first_audio_values: list[float] = []
    voice_streaming_enabled_count = 0
    voice_transport_counts: Counter[str] = Counter()
    voice_streaming_path_used_count = 0
    voice_buffered_projection_count = 0
    normal_path_streaming_miss_count = 0
    voice_first_chunk_before_complete_count = 0
    voice_fallback_count = 0
    voice_prewarm_used_count = 0
    voice_partial_playback_count = 0
    for row in rows:
        total = float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0)
        route = str(row.get("actual_route_family") or row.get("expected_route_family") or "unknown")
        stage = str(row.get("longest_stage") or "unknown")
        execution_mode = str(row.get("execution_mode") or "unknown")
        async_strategy = str(row.get("async_strategy") or "")
        if not async_strategy and (row.get("subsystem_continuation_created") or row.get("direct_subsystem_async_converted")):
            async_strategy = "create_job"
        async_strategy = async_strategy or "none"
        worker_lane = str(row.get("worker_lane") or "unknown")
        by_route[route].append(total)
        by_longest_stage[stage].append(total)
        by_execution_mode[execution_mode].append(total)
        by_async_strategy[async_strategy].append(total)
        async_strategy_by_worker_lane[async_strategy][worker_lane].append(total)
        worker_lane_counts[worker_lane] += 1
        queue_wait_values.append(float(row.get("queue_wait_ms") or 0.0))
        job_run_values.append(float(row.get("job_run_ms") or 0.0))
        job_total_values.append(float(row.get("job_total_ms") or 0.0))
        subsystem_cap_wait = float(row.get("subsystem_cap_wait_ms") or 0.0)
        subsystem_cap_wait_values.append(subsystem_cap_wait)
        if subsystem_cap_wait > 0:
            subsystem_cap_wait_count += 1
        if row.get("queue_wait_budget_exceeded"):
            queue_wait_budget_exceeded_count += 1
        scheduler_strategy = str(row.get("scheduler_strategy") or "unknown")
        scheduler_strategy_counts[scheduler_strategy] += 1
        pressure_state = str(row.get("scheduler_pressure_state") or "unknown")
        scheduler_pressure_counts[pressure_state] += 1
        retry_policy = str(row.get("retry_policy") or "none")
        retry_policy_counts[retry_policy] += 1
        retry_count_total += int(row.get("retry_count") or 0)
        cancellation_state_counts[str(row.get("cancellation_state") or "unknown")] += 1
        yield_state_counts[str(row.get("yield_state") or "unknown")] += 1
        restart_recovery_state_counts[str(row.get("restart_recovery_state") or "unknown")] += 1
        if float(row.get("worker_saturation_percent") or 0.0) >= 100.0:
            saturation_event_count += 1
        if row.get("starvation_detected"):
            starvation_warning_count += 1
        if int(row.get("background_job_count") or 0) > 0 or worker_lane == "background":
            background_job_rows += 1
            background_job_latency.append(total)
        triage_ms = float(row.get("route_triage_ms") or 0.0)
        if triage_ms >= 0:
            triage_values.append(triage_ms)
        if row.get("heavy_context_loaded"):
            heavy_context_by_route[route] += 1
        if row.get("fast_path_used"):
            fast_path_rows += 1
            likely = row.get("likely_route_families") if isinstance(row.get("likely_route_families"), list) else []
            if route in likely:
                fast_path_correct += 1
        if row.get("budget_exceeded"):
            budget_by_execution_mode[execution_mode] += 1
        if row.get("snapshot_hot_path_hit"):
            snapshot_hit_rows += 1
            snapshot_hit_latencies.append(total)
        miss_reason = row.get("snapshot_miss_reason") if isinstance(row.get("snapshot_miss_reason"), dict) else {}
        if miss_reason:
            snapshot_miss_latencies.append(total)
            for family in miss_reason:
                snapshot_miss_by_family[str(family)] += 1
        if row.get("stale_snapshot_used_cautiously"):
            stale_cautious_use_count += 1
        if row.get("heavy_context_avoided_by_snapshot"):
            heavy_context_avoidance_count += 1
            cache_benefit_by_route[route] += 1
        invalidation_events_count += int(row.get("invalidation_count") or 0)
        if row.get("async_initial_response_returned") or row.get("returned_before_subsystem_completion"):
            async_initial_response_count += 1
        progress_event_count += int(row.get("progress_event_count") or 0)
        if row.get("job_required"):
            job_required_count += 1
        if row.get("task_required"):
            task_required_count += 1
        if row.get("event_progress_required"):
            event_progress_required_count += 1
        if row.get("direct_subsystem_async_converted"):
            converted_subsystem_route_count += 1
            conversion_by_route[route] += 1
            conversion_success_count += 1
        if row.get("async_conversion_expected") and not row.get("direct_subsystem_async_converted"):
            expected_conversion_missing_count += 1
        if row.get("voice_streaming_tts_enabled"):
            voice_streaming_enabled_count += 1
        voice_transport = str(row.get("voice_streaming_transport_kind") or "")
        if voice_transport:
            voice_transport_counts[voice_transport] += 1
        if row.get("voice_stream_used_by_normal_path"):
            voice_streaming_path_used_count += 1
        elif row.get("voice_streaming_tts_enabled") and str(
            row.get("route_family") or row.get("actual_route_family") or ""
        ) == "voice_control":
            normal_path_streaming_miss_count += 1
        if voice_transport == "buffered_chunk_projection":
            voice_buffered_projection_count += 1
        if row.get("voice_first_chunk_before_complete"):
            voice_first_chunk_before_complete_count += 1
        voice_first_audio = float(row.get("voice_first_audio_ms") or 0.0)
        if voice_first_audio > 0:
            voice_first_audio_values.append(voice_first_audio)
        voice_core_to_first_audio = float(row.get("voice_core_to_first_audio_ms") or 0.0)
        if voice_core_to_first_audio > 0:
            voice_core_to_first_audio_values.append(voice_core_to_first_audio)
        if row.get("voice_streaming_fallback_used"):
            voice_fallback_count += 1
        if row.get("voice_prewarm_used"):
            voice_prewarm_used_count += 1
        if row.get("voice_partial_playback"):
            voice_partial_playback_count += 1
        inline_front_half_values.append(float(row.get("inline_front_half_ms") or 0.0))
        worker_back_half_values.append(float(row.get("worker_back_half_ms") or 0.0))
        continuation_queue_wait_values.append(float(row.get("continuation_queue_wait_ms") or 0.0))
        continuation_run_values.append(float(row.get("continuation_run_ms") or 0.0))
        continuation_total_values.append(float(row.get("continuation_total_ms") or 0.0))
        handler = str(row.get("subsystem_continuation_handler") or row.get("subsystem_continuation_kind") or "")
        if handler:
            continuation_runtime_by_handler[handler].append(float(row.get("continuation_total_ms") or 0.0))
        handler_implemented = _l44_inferred_handler_implemented(row, handler)
        if handler_implemented:
            implemented_handler_count += 1
            handler_count_by_route[route] += 1
        missing_reason = str(row.get("subsystem_continuation_handler_missing_reason") or "")
        if missing_reason:
            missing_handler_by_reason[missing_reason] += 1
        if row.get("subsystem_continuation_created") and row.get("returned_before_subsystem_completion") and str(row.get("result_state") or "").lower() in {"completed", "verified"}:
            unsafe_claim_by_handler[handler or "unknown"] += 1
    return {
        "total_latency_ms": _value_summary(total_values),
        "by_route_family": {
            route: _value_summary(values)
            for route, values in sorted(by_route.items())
        },
        "by_longest_stage": {
            stage: _value_summary(values)
            for stage, values in sorted(by_longest_stage.items())
        },
        "by_execution_mode": {
            mode: _value_summary(values)
            for mode, values in sorted(by_execution_mode.items())
        },
        "by_async_strategy": {
            strategy: _value_summary(values)
            for strategy, values in sorted(by_async_strategy.items())
        },
        "queue_wait_ms": _value_summary(queue_wait_values),
        "job_run_ms": _value_summary(job_run_values),
        "job_total_ms": _value_summary(job_total_values),
        "subsystem_cap_wait_ms": _value_summary(subsystem_cap_wait_values),
        "worker_lane_counts": dict(sorted(worker_lane_counts.items())),
        "scheduler_strategy_counts": dict(sorted(scheduler_strategy_counts.items())),
        "scheduler_pressure_state_counts": dict(sorted(scheduler_pressure_counts.items())),
        "queue_wait_budget_exceeded_count": queue_wait_budget_exceeded_count,
        "subsystem_cap_wait_count": subsystem_cap_wait_count,
        "retry_policy_counts": dict(sorted(retry_policy_counts.items())),
        "retry_count_total": retry_count_total,
        "cancellation_state_counts": dict(sorted(cancellation_state_counts.items())),
        "yield_state_counts": dict(sorted(yield_state_counts.items())),
        "restart_recovery_state_counts": dict(sorted(restart_recovery_state_counts.items())),
        "saturation_event_count": saturation_event_count,
        "starvation_warning_count": starvation_warning_count,
        "async_strategy_by_worker_lane": {
            strategy: {
                lane: _value_summary(values)
                for lane, values in sorted(lane_values.items())
            }
            for strategy, lane_values in sorted(async_strategy_by_worker_lane.items())
        },
        "background_job_impact_summary": {
            "rows_with_background_jobs": background_job_rows,
            "latency_ms": _value_summary(background_job_latency),
        },
        "route_triage_ms": _value_summary(triage_values),
        "fast_path_hit_rate": round(fast_path_rows / len(rows), 4) if rows else 0.0,
        "fast_path_correctness_rate": round(fast_path_correct / fast_path_rows, 4) if fast_path_rows else 0.0,
        "snapshot_hit_rate": round(snapshot_hit_rows / len(rows), 4) if rows else 0.0,
        "snapshot_miss_count_by_family": dict(sorted(snapshot_miss_by_family.items())),
        "stale_cautious_use_count": stale_cautious_use_count,
        "heavy_context_avoidance_count": heavy_context_avoidance_count,
        "snapshot_hit_vs_miss_latency": {
            "hit": _value_summary(snapshot_hit_latencies),
            "miss": _value_summary(snapshot_miss_latencies),
        },
        "top_slow_rows_with_snapshot_misses": [
            _compact_latency_row(row)
            for row in sorted(
                rows,
                key=lambda item: float(item.get("total_latency_ms") or item.get("latency_ms") or 0.0),
                reverse=True,
            )
            if isinstance(row.get("snapshot_miss_reason"), dict) and row.get("snapshot_miss_reason")
        ][:10],
        "top_route_families_benefiting_from_cache": dict(sorted(cache_benefit_by_route.items())),
        "invalidation_events_count": invalidation_events_count,
        "budget_exceeded_by_execution_mode": dict(sorted(budget_by_execution_mode.items())),
        "budget_exceeded_count": sum(1 for row in rows if row.get("budget_exceeded")),
        "budget_exceeded_continuing_count": sum(1 for row in rows if row.get("budget_exceeded_continuing")),
        "hard_timeout_count": sum(1 for row in rows if row.get("hard_timeout") or row.get("process_killed")),
        "provider_call_count": sum(int(row.get("provider_call_count") or 0) for row in rows),
        "partial_response_count": sum(1 for row in rows if row.get("partial_response_returned")),
        "async_initial_response_count": async_initial_response_count,
        "progress_event_count": progress_event_count,
        "job_required_count": job_required_count,
        "task_required_count": task_required_count,
        "event_progress_required_count": event_progress_required_count,
        "converted_subsystem_route_count": converted_subsystem_route_count,
        "conversion_count_by_route_family": dict(sorted(conversion_by_route.items())),
        "expected_conversion_missing_count": expected_conversion_missing_count,
        "implemented_handler_count": implemented_handler_count,
        "handler_count_by_route_family": dict(sorted(handler_count_by_route.items())),
        "missing_handler_count_by_reason": dict(sorted(missing_handler_by_reason.items())),
        "conversion_success_count": conversion_success_count,
        "conversion_expected_but_missing_count": expected_conversion_missing_count,
        "unsafe_claim_count_by_handler": dict(sorted(unsafe_claim_by_handler.items())),
        "p95_continuation_runtime_by_handler": {
            handler: _percentile(values, 0.95)
            for handler, values in sorted(continuation_runtime_by_handler.items())
        },
        "p95_inline_front_half_ms": _percentile(inline_front_half_values, 0.95),
        "p95_worker_back_half_ms": _percentile(worker_back_half_values, 0.95),
        "p95_continuation_queue_wait_ms": _percentile(continuation_queue_wait_values, 0.95),
        "p95_continuation_run_ms": _percentile(continuation_run_values, 0.95),
        "p95_continuation_total_ms": _percentile(continuation_total_values, 0.95),
        "voice_first_audio_ms": _value_summary(voice_first_audio_values),
        "voice_core_to_first_audio_ms": _value_summary(voice_core_to_first_audio_values),
        "voice_streaming_enabled_count": voice_streaming_enabled_count,
        "voice_streaming_transport_kind_counts": dict(sorted(voice_transport_counts.items())),
        "voice_streaming_path_used_count": voice_streaming_path_used_count,
        "voice_buffered_projection_count": voice_buffered_projection_count,
        "normal_path_streaming_miss_count": normal_path_streaming_miss_count,
        "voice_first_chunk_before_complete_count": voice_first_chunk_before_complete_count,
        "voice_streaming_fallback_count": voice_fallback_count,
        "voice_prewarm_used_count": voice_prewarm_used_count,
        "voice_partial_playback_count": voice_partial_playback_count,
        "fail_fast_count": sum(1 for row in rows if row.get("fail_fast_reason")),
        "heavy_context_loaded_count_by_route_family": dict(sorted(heavy_context_by_route.items())),
        "provider_fallback_suppressed_count": sum(1 for row in rows if row.get("provider_fallback_suppressed_reason")),
        "native_route_protection_count": sum(
            1
            for row in rows
            if row.get("provider_fallback_suppressed_reason") == "native_route_triage"
        ),
        "top_10_slowest_rows": [
            _compact_latency_row(row)
            for row in sorted(
                rows,
                key=lambda item: float(item.get("total_latency_ms") or item.get("latency_ms") or 0.0),
                reverse=True,
            )[:10]
        ],
        "top_route_handler_offenders": _top_stage_offenders(rows, "route_handler_ms"),
        "top_planner_offenders": _top_stage_offenders(rows, "planner_route_ms"),
        "top_response_serialization_offenders": _top_stage_offenders(rows, "response_serialization_ms"),
        "top_rows_by_queue_wait": [
            _compact_latency_row(row)
            for row in sorted(rows, key=lambda item: float(item.get("queue_wait_ms") or 0.0), reverse=True)
            if float(row.get("queue_wait_ms") or 0.0) > 0
        ][:10],
        "top_rows_by_job_runtime": [
            _compact_latency_row(row)
            for row in sorted(rows, key=lambda item: float(item.get("job_run_ms") or 0.0), reverse=True)
            if float(row.get("job_run_ms") or 0.0) > 0
        ][:10],
        "slowest_continuation_rows": [
            _compact_latency_row(row)
            for row in sorted(rows, key=lambda item: float(item.get("continuation_total_ms") or 0.0), reverse=True)
            if row.get("subsystem_continuation_created")
        ][:10],
        "slowest_rows_by_handler": {
            handler: [
                _compact_latency_row(row)
                for row in sorted(
                    [
                        item
                        for item in rows
                        if str(item.get("subsystem_continuation_handler") or item.get("subsystem_continuation_kind") or "") == handler
                    ],
                    key=lambda item: float(item.get("continuation_total_ms") or 0.0),
                    reverse=True,
                )[:10]
            ]
            for handler in sorted(continuation_runtime_by_handler)
        },
        "missing_conversion_rows": [
            _compact_latency_row(row)
            for row in rows
            if row.get("async_conversion_expected") and not row.get("direct_subsystem_async_converted")
        ][:10],
        "unsafe_claim_rows": [
            _compact_latency_row(row)
            for row in rows
            if row.get("subsystem_continuation_created")
            and row.get("returned_before_subsystem_completion")
            and str(row.get("result_state") or "").lower() in {"completed", "verified"}
        ][:10],
        "slow_planner_rows_with_triage": [
            _compact_latency_row(row)
            for row in sorted(rows, key=lambda item: float(item.get("planner_route_ms") or 0.0), reverse=True)
            if float(row.get("route_triage_ms") or 0.0) > 0
        ][:10],
        "top_rows_where_triage_likely_helped": [
            _compact_latency_row(row)
            for row in sorted(rows, key=lambda item: int(item.get("planner_candidates_pruned_count") or 0), reverse=True)
            if row.get("fast_path_used") or int(row.get("planner_candidates_pruned_count") or 0) > 0
        ][:10],
        "top_rows_where_triage_was_wrong_or_ambiguous": [
            _compact_latency_row(row)
            for row in rows
            if row.get("fast_path_used")
            and str(row.get("actual_route_family") or "") not in (row.get("likely_route_families") or [])
        ][:10],
        "top_slow_instant_routes": _top_mode_rows(rows, "instant"),
        "top_slow_plan_first_routes": _top_mode_rows(rows, "plan_first"),
        "top_slow_async_first_acknowledgements": _top_mode_rows(rows, "async_first", sort_field="first_feedback_ms"),
        "sync_blocked_async_expected_rows": [
            _compact_latency_row(row)
            for row in rows
            if row.get("async_expected")
            and not row.get("async_continuation")
            and float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0) > 2500
        ][:10],
        "known_slow_lanes": dict(
            sorted(
                Counter(
                    label
                    for row in rows
                    for label in row.get("known_lane_labels", [])
                    if isinstance(label, str) and label
                ).items()
            )
        ),
        "l44_async_validation": build_l44_async_validation_report(rows),
    }


def build_l44_async_validation_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the L4.4 audit view from already-sanitized Kraken rows."""
    safe_rows = _l44_normalize_rows(rows)
    tail_rows = classify_l44_tail_latency(safe_rows)
    return {
        "async_coverage_audit": _l44_async_coverage_audit(safe_rows),
        "tail_latency_classification": {
            "category_counts": dict(sorted(Counter(row["tail_category"] for row in tail_rows).items())),
            "top_20_slow_rows_overall": tail_rows[:20],
            "top_10_slow_rows_by_planner_time": _l44_top_by(safe_rows, "planner_route_ms"),
            "top_10_slow_rows_by_route_handler_time": _l44_top_by(safe_rows, "route_handler_ms"),
            "top_10_slow_rows_by_queue_wait": _l44_top_by(safe_rows, "queue_wait_ms"),
            "top_10_slow_rows_by_continuation_runtime": _l44_top_by(safe_rows, "continuation_total_ms"),
            "top_10_slow_rows_by_serialization": _l44_top_by(safe_rows, "response_serialization_ms"),
            "top_10_missing_conversion_rows": [
                item
                for item in tail_rows
                if item["tail_category"] in {"expected_async_missing", "handler_missing"}
            ][:10],
        },
        "truth_clamp_validation": validate_l44_truth_clamps(safe_rows),
        "scheduler_pressure_assessment": assess_l44_scheduler_pressure(safe_rows),
    }


def classify_l44_tail_latency(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _l44_normalize_rows(rows)
    classified: list[dict[str, Any]] = []
    for row in rows:
        compact = _compact_latency_row(row)
        category = _l44_tail_category(row)
        compact["tail_category"] = category
        compact["recommended_fix"] = _l44_recommended_fix(category, row)
        classified.append(compact)
    return sorted(
        classified,
        key=lambda item: float(item.get("total_latency_ms") or 0.0),
        reverse=True,
    )


def validate_l44_truth_clamps(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = _l44_normalize_rows(rows)
    unsafe_rows: list[dict[str, Any]] = []
    by_type: Counter[str] = Counter()
    by_handler: Counter[str] = Counter()
    by_route: Counter[str] = Counter()
    for row in rows:
        issues = _l44_truth_issues(row)
        if not issues:
            continue
        handler = str(row.get("subsystem_continuation_handler") or row.get("subsystem_continuation_kind") or "none")
        route = str(row.get("actual_route_family") or row.get("expected_route_family") or "unknown")
        for issue in issues:
            by_type[issue] += 1
            by_handler[handler] += 1
            by_route[route] += 1
        unsafe_rows.append(
            {
                **_compact_latency_row(row),
                "unsafe_claim_types": issues,
                "response_preview": _l44_response_text(row)[:220],
            }
        )
    return {
        "unsafe_claim_count": sum(by_type.values()),
        "unsafe_row_count": len(unsafe_rows),
        "unsafe_claim_count_by_type": dict(sorted(by_type.items())),
        "unsafe_claim_count_by_handler": dict(sorted(by_handler.items())),
        "unsafe_claim_count_by_route_family": dict(sorted(by_route.items())),
        "unsafe_claim_examples": unsafe_rows[:20],
    }


def assess_l44_scheduler_pressure(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = _l44_normalize_rows(rows)
    queue_values = [float(row.get("queue_wait_ms") or row.get("continuation_queue_wait_ms") or 0.0) for row in rows]
    run_values = [float(row.get("job_run_ms") or row.get("continuation_run_ms") or row.get("continuation_total_ms") or 0.0) for row in rows]
    saturation_count = sum(1 for row in rows if float(row.get("worker_saturation_percent") or 0.0) >= 100.0)
    starvation_count = sum(
        1
        for row in rows
        if row.get("starvation_detected")
        or (
            int(row.get("interactive_jobs_waiting") or 0) > 0
            and int(row.get("background_jobs_running") or 0) > 0
        )
    )
    by_route: Counter[str] = Counter()
    for row in rows:
        if float(row.get("queue_wait_ms") or row.get("continuation_queue_wait_ms") or 0.0) > 500.0:
            by_route[str(row.get("actual_route_family") or row.get("expected_route_family") or "unknown")] += 1
    queue_p95 = _percentile(queue_values, 0.95)
    run_p95 = _percentile(run_values, 0.95)
    if starvation_count:
        pressure = "high"
        source = "background_starvation"
        scope = "moderate"
    elif queue_p95 >= 1000.0 or saturation_count >= 3:
        pressure = "high"
        source = "queue_wait"
        scope = "moderate"
    elif queue_p95 >= 250.0 or saturation_count:
        pressure = "moderate"
        source = "queue_wait"
        scope = "light"
    elif run_p95 >= 3000.0:
        pressure = "moderate"
        source = "handler_runtime"
        scope = "light"
    else:
        pressure = "low"
        source = "none"
        scope = "none"
    if source == "none" and run_p95 >= 1500.0:
        pressure = "moderate"
        source = "handler_runtime"
        scope = "light"
    return {
        "scheduler_pressure": pressure,
        "primary_pressure_source": source,
        "recommended_l45_scope": scope,
        "queue_wait_ms": _value_summary(queue_values),
        "job_run_ms": _value_summary(run_values),
        "queue_wait_p95": queue_p95,
        "job_run_p95": run_p95,
        "worker_saturation_count": saturation_count,
        "starvation_warning_count": starvation_count,
        "top_affected_route_families": dict(by_route.most_common(10)),
    }


def _l44_normalize_rows(rows: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "to_dict") and callable(row.to_dict):
            normalized.append(dict(row.to_dict()))
        elif isinstance(row, dict):
            normalized.append(dict(row))
    return normalized


def _l44_async_coverage_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_by_route: dict[str, dict[str, Any]] = {
        route: {
            "current_async_status": "inline_correct" if route in _L44_INLINE_CORRECT_ROUTES else "async_policy_exists",
            "desired_status": desired,
            "row_count": 0,
            "converted_count": 0,
            "missing_count": 0,
            "notes": [],
        }
        for route, desired in sorted(_L44_ROUTE_DESIRED_STATUS.items())
    }
    status_by_handler: dict[str, dict[str, Any]] = {
        handler: dict(metadata, row_count=0, missing_count=0, implemented_count=0)
        for handler, metadata in sorted(_L44_EXPECTED_HANDLER_STATUS.items())
    }
    missing_reasons: Counter[str] = Counter()
    implemented_handler_count = 0
    continuation_triggered_count = 0
    expected_not_triggered_count = 0
    for row in rows:
        route = str(row.get("actual_route_family") or row.get("expected_route_family") or "unknown")
        route_entry = status_by_route.setdefault(
            route,
            {
                "current_async_status": "unknown",
                "desired_status": "unknown",
                "row_count": 0,
                "converted_count": 0,
                "missing_count": 0,
                "notes": [],
            },
        )
        route_entry["row_count"] += 1
        handler = str(row.get("subsystem_continuation_handler") or row.get("subsystem_continuation_kind") or "")
        missing_reason = str(
            row.get("subsystem_continuation_handler_missing_reason")
            or row.get("async_conversion_missing_reason")
            or ""
        )
        if row.get("subsystem_continuation_created") or row.get("direct_subsystem_async_converted"):
            continuation_triggered_count += 1
            route_entry["converted_count"] += 1
            route_entry["current_async_status"] = "continuation_triggered_correctly"
        if _l44_inferred_handler_implemented(row, handler):
            implemented_handler_count += 1
            route_entry["current_async_status"] = "continuation_handler_implemented"
        if row.get("async_conversion_expected") and not row.get("direct_subsystem_async_converted"):
            expected_not_triggered_count += 1
            if not missing_reason:
                route_entry["current_async_status"] = "continuation_expected_but_not_triggered"
        if missing_reason:
            missing_reasons[missing_reason] += 1
            route_entry["missing_count"] += 1
            route_entry["current_async_status"] = "continuation_handler_missing"
        if route in _L44_INLINE_CORRECT_ROUTES and not row.get("async_conversion_expected"):
            route_entry["current_async_status"] = "inline_correct"
        if handler:
            handler_entry = status_by_handler.setdefault(
                handler,
                {
                    "route_family": route,
                    "desired_status": "unknown",
                    "current_async_status": "unknown",
                    "row_count": 0,
                    "missing_count": 0,
                    "implemented_count": 0,
                },
            )
            handler_entry["row_count"] += 1
            if _l44_inferred_handler_implemented(row, handler):
                handler_entry["current_async_status"] = "continuation_handler_implemented"
                handler_entry["implemented_count"] += 1
            elif missing_reason:
                handler_entry["current_async_status"] = "continuation_handler_missing"
                handler_entry["missing_reason"] = missing_reason
                handler_entry["missing_count"] += 1
    classification_table = [
        {
            "route_or_subsystem": route,
            "current_async_status": data["current_async_status"],
            "desired_status": data["desired_status"],
            "row_count": data["row_count"],
            "converted_count": data["converted_count"],
            "missing_count": data["missing_count"],
        }
        for route, data in sorted(status_by_route.items())
    ]
    return {
        "status_by_route": status_by_route,
        "status_by_handler": status_by_handler,
        "classification_table": classification_table,
        "implemented_handler_count": implemented_handler_count,
        "continuation_triggered_count": continuation_triggered_count,
        "continuation_expected_but_not_triggered_count": expected_not_triggered_count,
        "missing_handler_count_by_reason": dict(sorted(missing_reasons.items())),
        "inline_correct_routes": sorted(_L44_INLINE_CORRECT_ROUTES),
    }


def _l44_tail_category(row: dict[str, Any]) -> str:
    if row.get("hard_timeout") or row.get("process_killed") or str(row.get("failure_category") or "") == "hard_timeout":
        return "harness_artifact"
    if str(row.get("subsystem_continuation_handler_missing_reason") or ""):
        return "handler_missing"
    if row.get("async_conversion_expected") and not (row.get("async_continuation") or row.get("direct_subsystem_async_converted")):
        return "expected_async_missing"
    if float(row.get("queue_wait_ms") or row.get("continuation_queue_wait_ms") or 0.0) >= 500.0:
        return "job_queue_wait_slow"
    if row.get("subsystem_continuation_created") and float(row.get("continuation_total_ms") or row.get("subsystem_continuation_total_ms") or 0.0) >= 1000.0:
        return "subsystem_continuation_runtime_slow"
    if float(row.get("job_run_ms") or 0.0) >= 1000.0:
        return "worker_runtime_slow"
    if float(row.get("planner_route_ms") or 0.0) >= 1000.0 or str(row.get("longest_stage") or "") == "planner_route_ms":
        return "planner_route_slow"
    if float(row.get("route_handler_ms") or 0.0) >= 1000.0 or str(row.get("longest_stage") or "") == "route_handler_ms":
        return "route_handler_slow"
    if (
        float(row.get("heavy_context_ms") or 0.0) >= 500.0
        or (
            str(row.get("longest_stage") or "") in {"memory_context_ms", "heavy_context_ms", "workspace_summary_ms"}
            and float(row.get("longest_stage_ms") or 0.0) >= 500.0
        )
    ):
        return "heavy_context_slow"
    if (
        isinstance(row.get("snapshot_miss_reason"), dict)
        and row.get("snapshot_miss_reason")
        and float(row.get("latency_ms") or row.get("total_latency_ms") or 0.0) >= 2500.0
    ):
        return "snapshot_miss_slow"
    if row.get("provider_called") or float(row.get("provider_call_count") or 0.0) > 0:
        return "provider_fallback_slow"
    if float(row.get("response_serialization_ms") or 0.0) >= 500.0:
        return "response_serialization_slow"
    if float(row.get("event_collection_ms") or 0.0) >= 500.0:
        return "event_collection_slow"
    if float(row.get("response_json_bytes") or 0.0) > 1_000_000:
        return "workspace_payload_large"
    if row.get("fail_fast_reason") and float(row.get("latency_ms") or row.get("total_latency_ms") or 0.0) > 2500.0:
        return "unsupported_route_waited_too_long"
    return "truthful_blocked_but_slow" if str(row.get("result_state") or "") in {"blocked", "unsupported"} else "within_expected_band"


def _l44_inferred_handler_implemented(row: dict[str, Any], handler: str) -> bool:
    if row.get("subsystem_continuation_handler_implemented"):
        return True
    if not handler:
        return False
    metadata = _L44_EXPECTED_HANDLER_STATUS.get(handler)
    if not metadata:
        return False
    if metadata.get("current_async_status") != "continuation_handler_implemented":
        return False
    return bool(row.get("subsystem_continuation_created") or row.get("direct_subsystem_async_converted"))


def _l44_recommended_fix(category: str, row: dict[str, Any]) -> str:
    if category == "planner_route_slow":
        return "inspect route triage and planner candidate pruning"
    if category == "route_handler_slow":
        return "inspect synchronous route handler stage"
    if category == "job_queue_wait_slow":
        return "evaluate L4.5 worker scheduling and queue pressure"
    if category in {"worker_runtime_slow", "subsystem_continuation_runtime_slow"}:
        return "profile continuation handler runtime before scheduler redesign"
    if category == "handler_missing":
        return str(row.get("subsystem_continuation_handler_missing_reason") or "classify missing continuation handler")
    if category == "expected_async_missing":
        return str(row.get("async_conversion_missing_reason") or "check continuation trigger metadata")
    if category == "harness_artifact":
        return "keep separate from latency budget exceedance"
    if category == "provider_fallback_slow":
        return "confirm provider fallback was expected and disabled where native route owns request"
    if category == "snapshot_miss_slow":
        return "inspect snapshot freshness and miss reasons"
    return "inspect row trace before changing behavior"


def _l44_truth_issues(row: dict[str, Any]) -> list[str]:
    text = _l44_response_text(row).lower()
    route = str(row.get("actual_route_family") or row.get("expected_route_family") or "").lower()
    handler = str(row.get("subsystem_continuation_handler") or row.get("subsystem_continuation_kind") or "").lower()
    state = str(row.get("result_state") or row.get("actual_result_state") or "").lower()
    issues: list[str] = []
    if row.get("subsystem_continuation_created") and row.get("returned_before_subsystem_completion") and state in {"completed", "verified"}:
        issues.append("initial_response_claimed_completion")
    if route == "discord_relay" and "preview" in state and any(word in text for word in ("sent", "delivered", "posted")):
        issues.append("preview_claimed_sent")
    if route == "discord_relay" and ("attempt" in state or "attempted" in text) and any(word in text for word in ("delivered", "verified delivery")):
        issues.append("dispatch_attempted_claimed_delivered")
    if route == "software_control" and state in {"planning", "plan_ready", "queued"} and any(word in text for word in ("installed", "updated", "uninstalled")):
        issues.append("software_plan_claimed_installed")
    if route == "software_control" and state == "completed_unverified" and "verified" in text:
        issues.append("completed_unverified_claimed_verified")
    if route == "software_recovery" and any(word in text for word in ("fixed", "repaired", "resolved")):
        issues.append("recovery_attempted_claimed_fixed")
    if (route == "network" or "network.run_live_diagnosis" in handler) and any(word in text for word in ("repaired", "fixed", "resolved")):
        issues.append("diagnosis_claimed_repair")
    if route == "screen_awareness" and "verified" in text and int(row.get("continuation_verification_evidence_count") or 0) <= 0:
        issues.append("screen_change_claimed_verified_without_evidence")
    if state == "completed_unverified" and "verified" in text:
        issues.append("completed_unverified_claimed_verified")
    return list(dict.fromkeys(issues))


def _l44_response_text(row: dict[str, Any]) -> str:
    if row.get("ui_response") is not None:
        return str(row.get("ui_response") or "")
    observation = row.get("observation") if isinstance(row.get("observation"), dict) else {}
    return str(observation.get("ui_response") or row.get("assistant_message") or row.get("response") or "")


def _l44_top_by(rows: list[dict[str, Any]], field: str, *, limit: int = 10) -> list[dict[str, Any]]:
    return [
        {
            **_compact_latency_row(row),
            field: row.get(field),
            "tail_category": _l44_tail_category(row),
        }
        for row in sorted(rows, key=lambda item: float(item.get(field) or 0.0), reverse=True)
        if float(row.get(field) or 0.0) > 0.0
    ][:limit]


def _compact_latency_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "prompt": row.get("prompt"),
        "status": row.get("status"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "result_state": row.get("result_state"),
        "total_latency_ms": row.get("total_latency_ms") or row.get("latency_ms"),
        "longest_stage": row.get("longest_stage"),
        "longest_stage_ms": row.get("longest_stage_ms"),
        "budget_label": row.get("budget_label"),
        "budget_exceeded": row.get("budget_exceeded"),
        "execution_mode": row.get("execution_mode"),
        "partial_response_returned": row.get("partial_response_returned"),
        "async_expected": row.get("async_expected"),
        "first_feedback_ms": row.get("first_feedback_ms"),
        "budget_exceeded_continuing": row.get("budget_exceeded_continuing"),
        "fail_fast_reason": row.get("fail_fast_reason"),
        "fast_path_used": row.get("fast_path_used"),
        "route_triage_ms": row.get("route_triage_ms"),
        "triage_confidence": row.get("triage_confidence"),
        "triage_reason_codes": row.get("triage_reason_codes"),
        "likely_route_families": row.get("likely_route_families"),
        "skipped_route_families": row.get("skipped_route_families"),
        "heavy_context_loaded": row.get("heavy_context_loaded"),
        "heavy_context_reason": row.get("heavy_context_reason"),
        "provider_fallback_suppressed_reason": row.get("provider_fallback_suppressed_reason"),
        "planner_candidates_pruned_count": row.get("planner_candidates_pruned_count"),
        "route_family_seams_evaluated": row.get("route_family_seams_evaluated"),
        "route_family_seams_skipped": row.get("route_family_seams_skipped"),
        "snapshots_checked": row.get("snapshots_checked"),
        "snapshots_used": row.get("snapshots_used"),
        "snapshots_refreshed": row.get("snapshots_refreshed"),
        "snapshots_invalidated": row.get("snapshots_invalidated"),
        "snapshot_freshness": row.get("snapshot_freshness"),
        "snapshot_hot_path_hit": row.get("snapshot_hot_path_hit"),
        "snapshot_miss_reason": row.get("snapshot_miss_reason"),
        "snapshot_age_ms": row.get("snapshot_age_ms"),
        "stale_snapshot_used_cautiously": row.get("stale_snapshot_used_cautiously"),
        "heavy_context_avoided_by_snapshot": row.get("heavy_context_avoided_by_snapshot"),
        "invalidation_count": row.get("invalidation_count"),
        "freshness_warnings": row.get("freshness_warnings"),
        "provider_called": row.get("provider_called"),
        "job_count": row.get("job_count"),
        "event_count": row.get("event_count"),
        "async_continuation": row.get("async_continuation"),
        "async_strategy": row.get("async_strategy"),
        "async_initial_response_returned": row.get("async_initial_response_returned"),
        "route_continuation_id": row.get("route_continuation_id"),
        "route_progress_stage": row.get("route_progress_stage"),
        "route_progress_status": row.get("route_progress_status"),
        "progress_event_count": row.get("progress_event_count"),
        "worker_lane": row.get("worker_lane"),
        "worker_priority": row.get("worker_priority"),
        "queue_depth_at_submit": row.get("queue_depth_at_submit"),
        "queue_wait_ms": row.get("queue_wait_ms"),
        "job_start_delay_ms": row.get("job_start_delay_ms"),
        "job_run_ms": row.get("job_run_ms"),
        "job_total_ms": row.get("job_total_ms"),
        "worker_index": row.get("worker_index"),
        "worker_capacity": row.get("worker_capacity"),
        "workers_busy_at_submit": row.get("workers_busy_at_submit"),
        "workers_idle_at_submit": row.get("workers_idle_at_submit"),
        "worker_saturation_percent": row.get("worker_saturation_percent"),
        "starvation_detected": row.get("starvation_detected"),
        "interactive_jobs_waiting": row.get("interactive_jobs_waiting"),
        "background_jobs_running": row.get("background_jobs_running"),
        "background_job_count": row.get("background_job_count"),
        "interactive_job_count": row.get("interactive_job_count"),
        "scheduler_strategy": row.get("scheduler_strategy"),
        "scheduler_pressure_state": row.get("scheduler_pressure_state"),
        "scheduler_pressure_reasons": row.get("scheduler_pressure_reasons"),
        "queue_wait_budget_ms": row.get("queue_wait_budget_ms"),
        "queue_wait_budget_exceeded": row.get("queue_wait_budget_exceeded"),
        "subsystem_cap_key": row.get("subsystem_cap_key"),
        "subsystem_cap_limit": row.get("subsystem_cap_limit"),
        "subsystem_cap_wait_ms": row.get("subsystem_cap_wait_ms"),
        "retry_policy": row.get("retry_policy"),
        "retry_count": row.get("retry_count"),
        "cancellation_state": row.get("cancellation_state"),
        "yield_state": row.get("yield_state"),
        "restart_recovery_state": row.get("restart_recovery_state"),
        "job_required": row.get("job_required"),
        "task_required": row.get("task_required"),
        "event_progress_required": row.get("event_progress_required"),
        "subsystem_continuation_created": row.get("subsystem_continuation_created"),
        "subsystem_continuation_id": row.get("subsystem_continuation_id"),
        "subsystem_continuation_kind": row.get("subsystem_continuation_kind"),
        "subsystem_continuation_stage": row.get("subsystem_continuation_stage"),
        "subsystem_continuation_status": row.get("subsystem_continuation_status"),
        "subsystem_continuation_worker_lane": row.get("subsystem_continuation_worker_lane"),
        "returned_before_subsystem_completion": row.get("returned_before_subsystem_completion"),
        "inline_front_half_ms": row.get("inline_front_half_ms"),
        "worker_back_half_ms": row.get("worker_back_half_ms"),
        "continuation_queue_wait_ms": row.get("continuation_queue_wait_ms"),
        "continuation_run_ms": row.get("continuation_run_ms"),
        "continuation_total_ms": row.get("continuation_total_ms"),
        "continuation_progress_event_count": row.get("continuation_progress_event_count"),
        "continuation_final_result_state": row.get("continuation_final_result_state"),
        "continuation_verification_state": row.get("continuation_verification_state"),
        "subsystem_continuation_handler": row.get("subsystem_continuation_handler"),
        "subsystem_continuation_handler_implemented": row.get("subsystem_continuation_handler_implemented"),
        "subsystem_continuation_handler_missing_reason": row.get("subsystem_continuation_handler_missing_reason"),
        "continuation_progress_stages": row.get("continuation_progress_stages"),
        "continuation_verification_required": row.get("continuation_verification_required"),
        "continuation_verification_attempted": row.get("continuation_verification_attempted"),
        "continuation_verification_evidence_count": row.get("continuation_verification_evidence_count"),
        "continuation_result_limitations": row.get("continuation_result_limitations"),
        "continuation_truth_clamps_applied": row.get("continuation_truth_clamps_applied"),
        "direct_subsystem_async_converted": row.get("direct_subsystem_async_converted"),
        "async_conversion_expected": row.get("async_conversion_expected"),
        "async_conversion_missing_reason": row.get("async_conversion_missing_reason"),
        "voice_anchor_state": row.get("voice_anchor_state"),
        "voice_speaking_visual_active": row.get("voice_speaking_visual_active"),
        "voice_audio_reactive_source": row.get("voice_audio_reactive_source"),
        "voice_audio_reactive_available": row.get("voice_audio_reactive_available"),
        "voice_anchor_motion_intensity": row.get("voice_anchor_motion_intensity"),
        "voice_anchor_audio_level": row.get("voice_anchor_audio_level"),
        "voice_visualizer_update_hz": row.get("voice_visualizer_update_hz"),
        "voice_anchor_user_heard_claimed": row.get("voice_anchor_user_heard_claimed"),
        "hard_timeout": row.get("hard_timeout"),
        "failure_category": row.get("failure_category"),
    }


def _top_stage_offenders(rows: list[dict[str, Any]], stage_name: str) -> list[dict[str, Any]]:
    return [
        {
            **_compact_latency_row(row),
            stage_name: row.get(stage_name),
        }
        for row in sorted(
            rows,
            key=lambda item: float(item.get(stage_name) or 0.0),
            reverse=True,
        )[:10]
        if float(row.get(stage_name) or 0.0) > 0
    ]


def _top_mode_rows(
    rows: list[dict[str, Any]],
    execution_mode: str,
    *,
    sort_field: str = "total_latency_ms",
) -> list[dict[str, Any]]:
    filtered = [
        row
        for row in rows
        if str(row.get("execution_mode") or "") == execution_mode
    ]
    return [
        _compact_latency_row(row)
        for row in sorted(
            filtered,
            key=lambda item: float(item.get(sort_field) or item.get("latency_ms") or 0.0),
            reverse=True,
        )[:10]
    ]


def _top_unattributed(results: list[CommandEvalResult]) -> list[dict[str, Any]]:
    return [
        {
            **_compact_result(result),
            "unattributed_latency_ms": result.to_dict().get("unattributed_latency_ms", 0.0),
        }
        for result in sorted(results, key=lambda item: float(item.to_dict().get("unattributed_latency_ms") or 0.0), reverse=True)[:20]
    ]


def _unattributed_by_route_family(results: list[CommandEvalResult]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for result in results:
        row = result.to_dict()
        grouped[result.case.expected.route_family].append(float(row.get("unattributed_latency_ms") or 0.0))
    return {family: _value_summary(values) for family, values in sorted(grouped.items())}


def _unattributed_repeated_case_variance(results: list[CommandEvalResult]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for result in results:
        source_id = result.case.case_id.rsplit("_rep", 1)[0]
        row = result.to_dict()
        grouped[source_id].append(float(row.get("unattributed_latency_ms") or 0.0))
    repeated = {case_id: values for case_id, values in grouped.items() if len(values) > 1}
    return {case_id: _value_summary(values, include_spread=True) for case_id, values in sorted(repeated.items())}


def _value_summary(values: list[float], *, include_spread: bool = False) -> dict[str, Any]:
    values = sorted(values)
    if not values:
        return {"count": 0, "min": None, "p50": None, "median": None, "p90": None, "p95": None, "p99": None, "max": None}
    payload: dict[str, Any] = {
        "count": len(values),
        "min": _percentile(values, 0.0),
        "p50": _percentile(values, 0.5),
        "median": _percentile(values, 0.5),
        "p90": _percentile(values, 0.9),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": _percentile(values, 1.0),
    }
    if include_spread:
        avg = sum(values) / len(values)
        payload["mean"] = round(avg, 3)
        payload["range"] = round(values[-1] - values[0], 3)
    return payload


def _missing_telemetry_classifications(
    result: CommandEvalResult,
    *,
    feature_audit: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    missing_route_state = not result.observation.route_state
    missing_planner_obedience = bool(result.observation.tool_chain and not result.observation.planner_obedience)
    if not missing_route_state and not missing_planner_obedience:
        return []
    surface_type = _route_surface_type(result, feature_audit=feature_audit)
    route_state_required = result.score_in_pass_fail and surface_type == "planner"
    planner_obedience_required = (
        result.score_in_pass_fail
        and surface_type == "planner"
        and bool(result.observation.tool_chain)
    )
    reason = _missing_telemetry_reason(
        surface_type=surface_type,
        route_state_required=route_state_required,
        planner_obedience_required=planner_obedience_required,
        missing_route_state=missing_route_state,
        missing_planner_obedience=missing_planner_obedience,
        result=result,
    )
    return [
        {
            "case_id": result.case.case_id,
            "expected_family": result.case.expected.route_family,
            "actual_family": result.observation.actual_route_family,
            "route_surface_type": surface_type,
            "missing_route_state": missing_route_state,
            "missing_planner_obedience": missing_planner_obedience,
            "route_state_should_be_required": route_state_required,
            "planner_obedience_should_be_required": planner_obedience_required,
            "reason": reason,
        }
    ]


def _route_surface_type(result: CommandEvalResult, *, feature_audit: dict[str, Any] | None) -> str:
    if not result.score_in_pass_fail:
        return "excluded"
    family = result.case.expected.route_family
    entry = ((feature_audit or {}).get("route_families") or {}).get(family, {})
    classification = str(entry.get("classification") or "").strip()
    if classification == "deprecated_or_legacy":
        return "legacy"
    if classification == "implemented_direct_only":
        return "direct"
    if family in {"time", "notes", "terminal", "development"}:
        return "direct"
    if result.observation.actual_route_family in {"time", "notes", "terminal", "development"}:
        return "direct"
    if classification in {"docs_only", "scaffold_only"}:
        return "excluded"
    return "planner"


def _missing_telemetry_reason(
    *,
    surface_type: str,
    route_state_required: bool,
    planner_obedience_required: bool,
    missing_route_state: bool,
    missing_planner_obedience: bool,
    result: CommandEvalResult,
) -> str:
    missing = []
    if missing_route_state:
        missing.append("route_state")
    if missing_planner_obedience:
        missing.append("planner_obedience")
    missing_text = " and ".join(missing)
    if surface_type == "excluded":
        return f"{missing_text} is absent on a feature-map excluded row; classify separately from scored routing failures."
    if surface_type in {"direct", "legacy"}:
        return f"{missing_text} is absent on a {surface_type} surface; planner metadata is not always emitted for this path."
    if route_state_required or planner_obedience_required:
        return f"{missing_text} is absent on a scored planner-routed row and should be treated as a telemetry gap."
    return f"{missing_text} is absent; no planner-backed tool execution was observed for actual route {result.observation.actual_route_family or '<none>'}."


def _failure_sort_key(result: CommandEvalResult) -> tuple[int, float]:
    priority = {
        "truthfulness_failure": 0,
        "harness_bug": 0,
        "real_routing_gap": 1,
        "wrong_subsystem": 1,
        "missing_telemetry": 2,
        "response_correctness_failure": 2,
        "latency_issue": 3,
        "corpus_expectation_bug": 4,
        "feature_map_overexpectation": 5,
        "passed": 9,
    }
    return (priority.get(result.failure_category, 6), -float(result.observation.latency_ms))


def _compact_failure(result: CommandEvalResult) -> dict[str, Any]:
    return {
        "test_id": result.case.case_id,
        "severity": _severity([name for name, outcome in result.assertions.items() if not outcome.passed]),
        "failure_category": result.failure_category,
        "input_request": result.case.message,
        "expected_route_family": result.case.expected.route_family,
        "actual_route_family": result.observation.actual_route_family,
        "expected_subsystem": result.case.expected.subsystem,
        "actual_subsystem": result.observation.actual_subsystem,
        "expected_tool": list(result.case.expected.tools),
        "actual_tool": list(result.observation.tool_chain),
        "result_state": result.observation.result_state,
        "ui_response": result.observation.ui_response,
        "latency_ms": result.observation.latency_ms,
        "failure_reason": result.failure_reason,
        "score_in_pass_fail": result.score_in_pass_fail,
    }


def _compact_result(result: CommandEvalResult) -> dict[str, Any]:
    return {
        "test_id": result.case.case_id,
        "input_request": result.case.message,
        "expected_route_family": result.case.expected.route_family,
        "actual_route_family": result.observation.actual_route_family,
        "latency_ms": result.observation.latency_ms,
        "unattributed_latency_ms": result.to_dict().get("unattributed_latency_ms", 0.0),
        "result_state": result.observation.result_state,
        "actual_tool": list(result.observation.tool_chain),
        "failure_category": result.failure_category,
    }


def _compact_failure_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- None."
    lines: list[str] = []
    for row in rows:
        response = str(row.get("ui_response") or "").replace("\n", " ")
        if len(response) > 180:
            response = response[:177] + "..."
        lines.append(
            "- `{test_id}` [{severity}/{failure_category}] {input_request} | expected {expected_route_family} {expected_tool} -> actual {actual_route_family} {actual_tool} | {result_state} | {latency_ms} ms | {failure_reason} | response: {response}".format(
                **row,
                response=response,
            )
        )
    return "\n".join(lines)


def _compact_result_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- None."
    return "\n".join(
        "- `{test_id}` {latency_ms} ms | unattributed {unattributed_latency_ms} ms | expected {expected_route_family} -> actual {actual_route_family} | {actual_tool} | {input_request}".format(**row)
        for row in rows
    )


def _recommendation(results: list[CommandEvalResult]) -> str:
    if not results:
        return "Fix harness first; no durable rows were produced."
    if len(results) != len({result.case.case_id for result in results}):
        return "Fix harness first; duplicate durable case IDs were detected."
    if all(result.observation.status == "hard_timeout" for result in results):
        return "Hard-timeout containment proof only; do not proceed to broader evaluation from this run."
    if not any(result.score_in_pass_fail for result in results):
        return "Do not proceed to broader evaluation from this run; it contains no scored route cases."
    latencies = sorted(result.observation.latency_ms for result in results)
    p95 = _percentile(latencies, 0.95) or 0
    timeout_count = sum(1 for result in results if result.observation.result_state == "timed_out")
    if timeout_count:
        return "Fix harness or route latency first; at least one request hit the per-test timeout."
    if p95 > 5000:
        return "Do not proceed to 250 yet; latency remains unstable above the 5s p95 guardrail."
    return "Proceed to a 250-case checkpointed evaluation; harness durability and latency are stable enough."


def _good_findings(results: list[CommandEvalResult]) -> str:
    pass_count = sum(1 for result in results if result.passed)
    routed_count = sum(1 for result in results if result.assertions["route_family"].passed)
    dry_run_count = sum(1 for result in results if result.observation.result_state == "dry_run")
    return "\n".join(
        [
            f"- {routed_count} cases matched the expected route family.",
            f"- {dry_run_count} tool-backed cases were validated without performing real-world actions.",
            f"- {pass_count} cases passed every configured assertion.",
        ]
    )


def _failure_table(results: list[CommandEvalResult]) -> str:
    if not results:
        return "- None found in this run."
    blocks: list[str] = []
    for result in results:
        failed_assertions = [name for name, outcome in result.assertions.items() if not outcome.passed]
        severity = _severity(failed_assertions)
        likely_fix = _likely_fix_area(result, failed_assertions)
        blocks.append(
            "\n".join(
                [
                    f"- test id: `{result.case.case_id}`",
                    f"  input request: {result.case.message}",
                    f"  expected behavior: route `{result.case.expected.route_family}`, tools `{list(result.case.expected.tools)}`",
                    f"  actual behavior: route `{result.observation.actual_route_family}`, subsystem `{result.observation.actual_subsystem}`",
                    f"  actual tool chain: `{list(result.observation.tool_chain)}`",
                    f"  result state: `{result.observation.result_state}`",
                    f"  UI-facing response: {result.observation.ui_response[:240]}",
                    f"  latency: {result.observation.latency_ms} ms",
                    f"  severity: {severity}",
                    f"  likely fix area: {likely_fix}",
                    f"  reproduction command or test path: `python scripts/run_command_usability_eval.py --case-id {result.case.case_id}`",
                ]
            )
        )
    return "\n".join(blocks)


def _severity(failed_assertions: list[str]) -> str:
    if "no_overclaim" in failed_assertions:
        return "P0"
    if "route_family" in failed_assertions or "tool_chain" in failed_assertions:
        return "P1"
    if "clarification" in failed_assertions or "approval" in failed_assertions:
        return "P2"
    return "P3"


def _likely_fix_area(result: CommandEvalResult, failed_assertions: list[str]) -> str:
    if "route_family" in failed_assertions:
        return "DeterministicPlanner routing candidates and route scoring."
    if "tool_chain" in failed_assertions:
        return "ExecutionPlan tool proposal and adapter binding."
    if "clarification" in failed_assertions:
        return "Clarification pressure and missing-target handling."
    if "approval" in failed_assertions:
        return "Trust/SafetyPolicy surfacing or adapter approval metadata."
    if "no_overclaim" in failed_assertions:
        return "Assistant response copy, adapter claim ceiling, or verification posture."
    return f"{result.case.expected.route_family} response contract."


def _latency_findings(latency_summary: dict[str, dict[str, Any]]) -> str:
    if not latency_summary:
        return "- No latency data."
    slow = [
        (family, data)
        for family, data in latency_summary.items()
        if float(data.get("max_ms") or 0) > 2500
    ]
    if not slow:
        return "- No route family exceeded the default 2500 ms latency band."
    return "\n".join(f"- {family}: max {data['max_ms']} ms, avg {data['avg_ms']} ms" for family, data in slow)


def _copy_findings(failures: list[CommandEvalResult]) -> str:
    copy_issues = [result for result in failures if not result.assertions["response_meaning"].passed]
    return _failure_table(copy_issues[:20]) if copy_issues else "- No response-term issues found by deterministic checks."


def _telemetry_findings(results: list[CommandEvalResult]) -> str:
    missing_route_state = [result for result in results if not result.observation.route_state]
    missing_obedience = [result for result in results if result.observation.tool_chain and not result.observation.planner_obedience]
    return "\n".join(
        [
            f"- Missing route_state cases: {len(missing_route_state)}",
            f"- Tool-backed cases missing planner_obedience: {len(missing_obedience)}",
        ]
    )


def _recommended_fixes(
    routing_failures: list[CommandEvalResult],
    wrong_tool: list[CommandEvalResult],
    clarification: list[CommandEvalResult],
    deictic: list[CommandEvalResult],
    no_overclaim: list[CommandEvalResult],
) -> str:
    recommendations: list[str] = []
    if routing_failures:
        recommendations.append("- Tighten route-family scoring for the highest-volume confusion-matrix cells.")
    if wrong_tool:
        recommendations.append("- Add planner-level contract tests for expected tool proposal order before job submission.")
    if clarification:
        recommendations.append("- Add targeted clarification triggers for ambiguous payloads, targets, and follow-up references.")
    if deictic:
        recommendations.append("- Strengthen deictic binding priority between selection, clipboard, recent entities, and active previews.")
    if no_overclaim:
        recommendations.append("- Gate UI success language on adapter execution claim ceilings and subsystem verification evidence.")
    recommendations.append("- Promote the passing canonical cases plus all observed failures into a smaller per-PR regression suite.")
    return "\n".join(recommendations)


def _suggested_regression_suite(failures: list[CommandEvalResult]) -> str:
    if not failures:
        return "- Use the focused suite plus 100 random fuzzy cases per PR."
    selected = failures[:50]
    return "\n".join(f"- `{result.case.case_id}`: {result.case.message}" for result in selected)
