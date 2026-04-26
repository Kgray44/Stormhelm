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
            "median": _percentile(latencies, 0.5),
            "p90": _percentile(latencies, 0.9),
            "p95": _percentile(latencies, 0.95),
            "max": _percentile(latencies, 1.0),
        },
        "stage_latency_summary": _stage_latency_summary(results),
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
            summary[field] = {"count": 0, "min": None, "median": None, "p90": None, "p95": None, "max": None}
            continue
        summary[field] = {
            "count": len(values),
            "min": _percentile(values, 0.0),
            "median": _percentile(values, 0.5),
            "p90": _percentile(values, 0.9),
            "p95": _percentile(values, 0.95),
            "max": _percentile(values, 1.0),
        }
    return summary


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
        return {"count": 0, "min": None, "median": None, "p90": None, "p95": None, "max": None}
    payload: dict[str, Any] = {
        "count": len(values),
        "min": _percentile(values, 0.0),
        "median": _percentile(values, 0.5),
        "p90": _percentile(values, 0.9),
        "p95": _percentile(values, 0.95),
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
