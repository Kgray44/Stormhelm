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


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "routing-remediation"
PRE_FOCUSED_DIR = Path(".artifacts") / "command-usability-eval" / "focused-80-post-hardening"
PAYLOAD_HARDENING_DIR = Path(".artifacts") / "command-usability-eval" / "payload-routine-hardening"
OLD_LATENCY_DIR = Path(".artifacts") / "command-usability-eval" / "latency-micro-20260424-225838"
ROUTINE_REPRO_DIR = Path(".artifacts") / "command-usability-eval" / "routine-save-repro"
HARD_TIMEOUT_DIR = Path(".artifacts") / "command-usability-eval" / "hard-timeout-proof-20260425-024110"
PAYLOAD_FAIL_BYTES = 5_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description="Run targeted routing remediation and focused-80 checkpoint.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    corpus = build_command_usability_corpus(min_cases=1000)
    full_corpus = corpus[:1000]
    focused_corpus = _focused_subset(full_corpus, limit=80)
    pre_rows = _read_jsonl(PRE_FOCUSED_DIR / "focused_80_results.jsonl")
    pre_summary = _read_json(PRE_FOCUSED_DIR / "focused_80_summary.json")
    census = _read_json(args.output_dir / "routing_failure_census.json")
    feature_audit = build_feature_audit(full_corpus)

    write_json(args.output_dir / "feature_map.json", build_feature_map())
    write_json(args.output_dir / "feature_map_audit.json", feature_audit)
    write_jsonl(args.output_dir / "focused_80_corpus.jsonl", [case.to_dict() for case in focused_corpus])

    targeted_ids = {
        str(row.get("test_id") or "")
        for row in pre_rows
        if row.get("score_in_pass_fail")
        and str(row.get("failure_category") or "") in {"real_routing_gap", "wrong_subsystem"}
    }
    targeted_cases = [case for case in focused_corpus if case.case_id in targeted_ids]
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    targeted_results = harness.run(targeted_cases, results_name="targeted_routing_results.jsonl", resume=False)
    targeted_rows = _read_jsonl(args.output_dir / "targeted_routing_results.jsonl")
    targeted_summary = _summary(
        rows=targeted_rows,
        attempted=len(targeted_cases),
        result_count=len(targeted_results),
        checkpoint=_read_json(args.output_dir / "targeted_routing_results.checkpoint.json"),
        output_dir=args.output_dir,
        results_name="targeted_routing_results.jsonl",
        feature_audit=feature_audit,
    )
    write_json(args.output_dir / "targeted_routing_summary.json", targeted_summary)

    focused_harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    focused_results = focused_harness.run(focused_corpus, results_name="focused_80_post_routing_results.jsonl", resume=False)
    post_rows = _read_jsonl(args.output_dir / "focused_80_post_routing_results.jsonl")
    route_confusion = _route_confusion_matrix(post_rows)
    write_json(args.output_dir / "focused_80_route_confusion_matrix.json", route_confusion)

    post_summary = _summary(
        rows=post_rows,
        attempted=len(focused_corpus),
        result_count=len(focused_results),
        checkpoint=_read_json(args.output_dir / "focused_80_post_routing_results.checkpoint.json"),
        output_dir=args.output_dir,
        results_name="focused_80_post_routing_results.jsonl",
        feature_audit=feature_audit,
    )
    post_summary["before_after"] = _comparison(pre_rows, post_rows, pre_summary)
    post_summary["routing_failure_census_summary"] = {
        "path": str(args.output_dir / "routing_failure_census.json"),
        "failure_category_counts": census.get("failure_category_counts", {}),
        "real_routing_gaps_by_expected_family": census.get("real_routing_gaps_by_expected_family", {}),
        "wrong_subsystem_by_expected_and_actual_family": census.get("wrong_subsystem_by_expected_and_actual_family", {}),
        "high_impact_clusters": census.get("high_impact_clusters", []),
    }
    post_summary["routeability_audit_summary"] = {
        key: value
        for key, value in (census.get("routeability_audit") or {}).items()
        if key in set(post_summary["failure_counts"]["raw_failure_category_counts"]) or True
    }
    post_summary["targeted_routing_summary"] = targeted_summary
    post_summary["artifacts_preserved"] = {
        "pre_focused_80": str(PRE_FOCUSED_DIR),
        "payload_routine_hardening": str(PAYLOAD_HARDENING_DIR),
        "old_latency_micro_suite": str(OLD_LATENCY_DIR),
        "routine_save_repro": str(ROUTINE_REPRO_DIR),
        "hard_timeout_proof": str(HARD_TIMEOUT_DIR),
    }
    post_summary["routing_changes_made"] = [
        "Stripped Stormhelm invocation prefixes before deterministic native matching.",
        "Expanded workspace restore/list/clear/archive/next-step ownership for focused high-confidence phrases.",
        "Added explicit filesystem path open routing before app-control launch matching.",
        "Prevented app-control from capturing conversational 'open up ...' near-misses.",
        "Normalized trusted-hook execution under the routine route family.",
        "Normalized power projection under the power route family.",
        "Added current-browser-page phrasing to watch-runtime browser context.",
        "Added row-level route decline/native-candidate/generic-provider telemetry fields.",
    ]
    post_summary["deliberately_not_changed"] = [
        "No provider-first fuzzy interpretation was added.",
        "No scaffold-only trusted-hook registration route was enabled.",
        "No payload guardrails or active-context compaction were weakened.",
        "No software-control approval/trust policy was loosened.",
        "The historical routine_save blocker label remains preserved.",
    ]
    post_summary["recommendation"] = _recommendation(post_summary)
    write_json(args.output_dir / "focused_80_post_routing_summary.json", post_summary)
    (args.output_dir / "focused_80_post_routing_report.md").write_text(_report(post_summary), encoding="utf-8")

    print(f"targeted_routing_results: {args.output_dir / 'targeted_routing_results.jsonl'}")
    print(f"targeted_routing_summary: {args.output_dir / 'targeted_routing_summary.json'}")
    print(f"focused_80_post_routing_results: {args.output_dir / 'focused_80_post_routing_results.jsonl'}")
    print(f"focused_80_post_routing_summary: {args.output_dir / 'focused_80_post_routing_summary.json'}")
    print(f"focused_80_post_routing_report: {args.output_dir / 'focused_80_post_routing_report.md'}")
    print(f"focused_80_route_confusion_matrix: {args.output_dir / 'focused_80_route_confusion_matrix.json'}")


def _focused_subset(corpus: list[Any], *, limit: int) -> list[Any]:
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


def _summary(
    *,
    rows: list[dict[str, Any]],
    attempted: int,
    result_count: int,
    checkpoint: dict[str, Any],
    output_dir: Path,
    results_name: str,
    feature_audit: dict[str, Any],
) -> dict[str, Any]:
    failed = [row for row in rows if not row.get("passed")]
    scored = [row for row in rows if row.get("score_in_pass_fail")]
    scored_failed = [row for row in scored if not row.get("passed")]
    excluded = [row for row in rows if not row.get("score_in_pass_fail")]
    latencies = [float(row.get("latency_ms") or 0.0) for row in rows]
    payloads = [float(row.get("response_json_bytes") or 0.0) for row in rows]
    route_matrix = _route_confusion_matrix(rows)
    safety = {
        "provider_calls": sum(1 for row in rows if row.get("provider_called")),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout" or row.get("result_state") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
        "orphan_process_check": _orphan_process_check_result(),
    }
    failure_counts = {
        "raw_failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in failed).items())),
        "scored_failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in scored_failed).items())),
        "excluded_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in excluded if not row.get("passed")).items())),
    }
    return {
        "attempted": attempted,
        "completed": len(rows),
        "harness_result_count": result_count,
        "durable_rows": _line_count(output_dir / results_name),
        "completed_equals_durable_rows": len(rows) == _line_count(output_dir / results_name),
        "checkpoint_rows": int(checkpoint.get("completed") or 0),
        "checkpoint": checkpoint,
        "safety": safety,
        "raw_counts": {"pass": sum(1 for row in rows if row.get("passed")), "fail": len(failed), "excluded": len(excluded)},
        "scored_counts": {"pass": sum(1 for row in scored if row.get("passed")), "fail": len(scored_failed), "excluded": len(excluded)},
        "failure_counts": failure_counts,
        "route_family_coverage": {
            "expected": dict(sorted(Counter(str(row.get("expected_route_family") or "") for row in rows).items())),
            "actual": dict(sorted(Counter(str(row.get("actual_route_family") or "") for row in rows).items())),
        },
        "expected_vs_actual_route_confusion_matrix": route_matrix,
        "generic_provider_fallback_count_by_expected_family": dict(sorted(Counter(str(row.get("expected_route_family") or "") for row in rows if row.get("actual_route_family") == "generic_provider").items())),
        "latency_summary_ms": _stats(latencies),
        "slowest_20": [_compact(row) for row in sorted(rows, key=lambda row: float(row.get("latency_ms") or 0.0), reverse=True)[:20]],
        "payload_summary": {
            "response_json_bytes": _stats(payloads),
            "max_workspace_item_count": max([int(row.get("workspace_item_count") or 0) for row in rows], default=0),
            "payload_guardrail_failures": [_compact(row) for row in rows if int(row.get("response_json_bytes") or 0) > PAYLOAD_FAIL_BYTES or row.get("failure_category") == "payload_guardrail_failure"],
            "top_largest_payload_rows": [_compact(row) for row in sorted(rows, key=lambda row: int(row.get("response_json_bytes") or 0), reverse=True)[:20]],
        },
        "routine_save_behavior": _routine_summary(rows),
        "remaining_real_routing_gaps": [_failure(row) for row in scored_failed if row.get("failure_category") == "real_routing_gap"],
        "remaining_wrong_subsystem_failures": [_failure(row) for row in scored_failed if row.get("failure_category") == "wrong_subsystem"],
        "remaining_corpus_expectation_bugs": [_failure(row) for row in scored_failed if row.get("failure_category") == "corpus_expectation_bug"],
        "remaining_feature_map_scaffold_exclusions": [_failure(row) for row in excluded],
        "missing_telemetry_summary": _missing_telemetry(rows, feature_audit),
    }


def _comparison(pre_rows: list[dict[str, Any]], post_rows: list[dict[str, Any]], pre_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "pre_summary_path": str(PRE_FOCUSED_DIR / "focused_80_summary.json"),
        "pass_fail_before": pre_summary.get("scored_counts") or _counts(pre_rows),
        "pass_fail_after": _counts(post_rows),
        "scored_failures_before": (pre_summary.get("scored_counts") or {}).get("fail"),
        "scored_failures_after": _counts(post_rows)["fail"],
        "real_routing_gap_before": (pre_summary.get("scored_failure_category_counts") or {}).get("real_routing_gap", 0),
        "real_routing_gap_after": sum(1 for row in post_rows if row.get("score_in_pass_fail") and not row.get("passed") and row.get("failure_category") == "real_routing_gap"),
        "wrong_subsystem_before": (pre_summary.get("scored_failure_category_counts") or {}).get("wrong_subsystem", 0),
        "wrong_subsystem_after": sum(1 for row in post_rows if row.get("score_in_pass_fail") and not row.get("passed") and row.get("failure_category") == "wrong_subsystem"),
        "generic_provider_fallback_before": sum(1 for row in pre_rows if row.get("actual_route_family") == "generic_provider"),
        "generic_provider_fallback_after": sum(1 for row in post_rows if row.get("actual_route_family") == "generic_provider"),
        "latency_before_ms": pre_summary.get("latency_summary") or _stats([float(row.get("latency_ms") or 0.0) for row in pre_rows]),
        "latency_after_ms": _stats([float(row.get("latency_ms") or 0.0) for row in post_rows]),
        "payload_max_before": ((pre_summary.get("payload_summary") or {}).get("response_json_bytes") or {}).get("max"),
        "payload_max_after": _stats([float(row.get("response_json_bytes") or 0.0) for row in post_rows])["max"],
        "payload_guardrail_failures_before": len(((pre_summary.get("payload_summary") or {}).get("payload_guardrail_failures") or [])),
        "payload_guardrail_failures_after": sum(1 for row in post_rows if row.get("failure_category") == "payload_guardrail_failure" or int(row.get("response_json_bytes") or 0) > PAYLOAD_FAIL_BYTES),
        "routine_save_before": (pre_summary.get("routine_save_behavior") or {}),
        "routine_save_after": _routine_summary(post_rows),
    }


def _report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Focused-80 Post-Routing-Remediation Report",
            "",
            "## 1. Executive Summary",
            f"- attempted/completed/durable: {summary['attempted']} / {summary['completed']} / {summary['durable_rows']}",
            f"- scored counts: {summary['scored_counts']}",
            f"- recommendation: {summary['recommendation']}",
            "",
            "## 2. Safety Summary",
            _fmt(summary["safety"]),
            "",
            "## 3. Harness Durability",
            f"- attempted: {summary['attempted']}",
            f"- completed: {summary['completed']}",
            f"- durable rows: {summary['durable_rows']}",
            f"- completed equals durable rows: {summary['completed_equals_durable_rows']}",
            f"- checkpoint rows: {summary['checkpoint_rows']}",
            "",
            "## 4. What Failed Before",
            _fmt(summary["before_after"]),
            "",
            "## 5. Failure Census Summary",
            _fmt(summary["routing_failure_census_summary"]),
            "",
            "## 6. Routeability Audit Summary",
            _fmt(summary["routeability_audit_summary"]),
            "",
            "## 7. What Routing Changes Were Made",
            _list(summary["routing_changes_made"]),
            "",
            "## 8. What Was Deliberately Not Changed",
            _list(summary["deliberately_not_changed"]),
            "",
            "## 9. Targeted Routing Test Results",
            _fmt(summary["targeted_routing_summary"]),
            "",
            "## 10. Focused-80 Post-Routing-Remediation Results",
            f"- raw counts: {summary['raw_counts']}",
            f"- scored counts: {summary['scored_counts']}",
            f"- failure counts: {summary['failure_counts']}",
            "",
            "## 11. Before/After Comparison",
            _fmt(summary["before_after"]),
            "",
            "## 12. Remaining Real Routing Gaps",
            _rows(summary["remaining_real_routing_gaps"]),
            "",
            "## 13. Remaining Wrong-Subsystem Failures",
            _rows(summary["remaining_wrong_subsystem_failures"]),
            "",
            "## 14. Remaining Corpus Expectation Bugs",
            _rows(summary["remaining_corpus_expectation_bugs"]),
            "",
            "## 15. Remaining Feature-Map/Scaffold Exclusions",
            _rows(summary["remaining_feature_map_scaffold_exclusions"]),
            "",
            "## 16. Missing Telemetry Summary",
            _fmt(summary["missing_telemetry_summary"]),
            "",
            "## 17. Recommendation",
            f"- {summary['recommendation']}",
        ]
    ).strip() + "\n"


def _recommendation(summary: dict[str, Any]) -> str:
    if summary["attempted"] != summary["durable_rows"] or not summary["completed_equals_durable_rows"]:
        return "fix harness before 250"
    if any(summary["safety"][key] for key in {"provider_calls", "real_external_actions", "process_kills"}):
        return "fix safety isolation before 250"
    if summary["safety"]["orphan_process_check"] != "no_orphan_command_eval_processes_detected":
        return "fix harness process cleanup before 250"
    if summary["payload_summary"]["payload_guardrail_failures"]:
        return "fix latency/payload before 250"
    after = summary["before_after"]
    if int(after.get("real_routing_gap_after") or 0) or int(after.get("wrong_subsystem_after") or 0):
        return "fix more routing first; focused-80 improved but still has native routing failures"
    if summary["scored_counts"]["fail"]:
        return "fix corpus labels/latency issues before 250"
    return "proceed to 250 with hard-timeout containment and routine_save historical blocker label preserved"


def _missing_telemetry(rows: list[dict[str, Any]], feature_audit: dict[str, Any]) -> dict[str, Any]:
    classified = []
    for row in rows:
        missing_route = not bool(row.get("route_state"))
        missing_obedience = bool(row.get("actual_tool")) and not bool(row.get("planner_obedience"))
        if not missing_route and not missing_obedience:
            continue
        family = str(row.get("expected_route_family") or "")
        route_entry = dict((feature_audit.get("route_families") or {}).get(family) or {})
        surface_type = "direct" if route_entry.get("classification") == "implemented_direct_only" else "planner"
        classified.append(
            {
                "case_id": row.get("test_id"),
                "expected_family": family,
                "actual_family": row.get("actual_route_family"),
                "route_surface_type": surface_type,
                "route_state_should_be_required": surface_type == "planner",
                "planner_obedience_should_be_required": bool(row.get("actual_tool")) and surface_type == "planner",
                "reason": route_entry.get("scoring_note"),
            }
        )
    return {
        "missing_route_state": sum(1 for row in rows if not row.get("route_state")),
        "missing_planner_obedience": sum(1 for row in rows if row.get("actual_tool") and not row.get("planner_obedience")),
        "classified_rows": classified,
    }


def _route_confusion_matrix(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        matrix[str(row.get("expected_route_family") or "")][str(row.get("actual_route_family") or "")] += 1
    return {expected: dict(sorted(actuals.items())) for expected, actuals in sorted(matrix.items())}


def _routine_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    routine = [
        row for row in rows if "routine_save" in str(row.get("test_id") or "") or "routine_save" in [str(tool) for tool in row.get("actual_tool") or []]
    ]
    return {
        "rows": len(routine),
        "actual_routes": dict(sorted(Counter(str(row.get("actual_route_family") or "") for row in routine).items())),
        "latency_ms": _stats([float(row.get("latency_ms") or 0.0) for row in routine]),
        "generic_provider_fallbacks": sum(1 for row in routine if row.get("actual_route_family") == "generic_provider"),
        "historical_blocker_labels": sorted({label for row in routine for label in row.get("historical_blocker_labels") or []}),
        "old_blocker_status": "known_unreproduced_product_latency_blocker",
    }


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    scored = [row for row in rows if row.get("score_in_pass_fail")]
    return {
        "pass": sum(1 for row in scored if row.get("passed")),
        "fail": sum(1 for row in scored if not row.get("passed")),
        "excluded": sum(1 for row in rows if not row.get("score_in_pass_fail")),
    }


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "prompt": row.get("prompt") or row.get("input"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "expected_subsystem": row.get("expected_subsystem"),
        "actual_subsystem": row.get("actual_subsystem"),
        "expected_tool": row.get("expected_tool"),
        "actual_tool": row.get("actual_tool"),
        "result_state": row.get("result_state"),
        "failure_category": row.get("failure_category"),
        "latency_ms": row.get("latency_ms"),
        "response_json_bytes": row.get("response_json_bytes"),
        "workspace_item_count": row.get("workspace_item_count"),
        "historical_blocker_labels": row.get("historical_blocker_labels"),
    }


def _failure(row: dict[str, Any]) -> dict[str, Any]:
    item = _compact(row)
    item["failure_reason"] = row.get("failure_reason")
    item["route_scores"] = row.get("route_scores")
    item["fallback_reason"] = row.get("fallback_reason")
    return item


def _stats(values: list[float]) -> dict[str, Any]:
    values = sorted(float(value) for value in values)
    if not values:
        return {"count": 0, "min": None, "median": None, "p90": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "min": round(values[0], 3),
        "median": round(median(values), 3),
        "p90": _percentile(values, 0.9),
        "p95": _percentile(values, 0.95),
        "max": round(values[-1], 3),
    }


def _percentile(values: list[float], fraction: float) -> float:
    if len(values) == 1:
        return round(values[0], 3)
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * fraction))))
    return round(values[index], 3)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _orphan_process_check_result() -> str:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*serve_command_eval_core.py*' } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(["powershell", "-NoProfile", "-Command", command], text=True, capture_output=True, timeout=20)
    output = (completed.stdout or "").strip()
    return "no_orphan_command_eval_processes_detected" if not output else f"possible_processes_detected: {output[:1000]}"


def _fmt(payload: Any) -> str:
    if not payload:
        return "- none"
    if isinstance(payload, dict):
        return "\n".join(f"- {key}: {value}" for key, value in payload.items())
    return str(payload)


def _list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- none"


def _rows(rows: list[dict[str, Any]]) -> str:
    return "\n".join(f"- `{row.get('test_id') or '<row>'}`: {row}" for row in rows) if rows else "- none"


if __name__ == "__main__":
    main()
