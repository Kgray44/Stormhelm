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
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "250-checkpoint"
FOCUSED_80_DIR = Path(".artifacts") / "command-usability-eval" / "250-readiness-cleanup"
PAYLOAD_WARN_BYTES = 1_000_000
PAYLOAD_FAIL_BYTES = 5_000_000
STYLE_ORDER = (
    "canonical",
    "command_mode",
    "casual",
    "shorthand",
    "typo",
    "indirect",
    "deictic",
    "follow_up",
    "near_miss",
    "ambiguous",
    "unsupported_probe",
    "cross_family",
    "noisy",
    "negative",
    "question",
    "polite",
    "slang",
    "terse",
    "confirm",
    "correction",
)
SEVERITY_ORDER = {
    "hard_timeout": 0,
    "payload_guardrail_failure": 1,
    "truthfulness_failure": 2,
    "real_routing_gap": 3,
    "wrong_subsystem": 4,
    "clarification_failure": 5,
    "approval_expectation_mismatch": 6,
    "response_correctness_failure": 7,
    "missing_telemetry": 8,
    "latency_issue": 9,
    "known_workspace_latency_lane": 9,
    "feature_map_overexpectation": 10,
    "corpus_expectation_bug": 11,
    "unsupported_feature_expected": 12,
    "known_blocker_lane": 13,
    "harness_bug": 14,
    "passed": 99,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the 250-case command-usability checkpoint only.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pre_orphan = _orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start 250 checkpoint with existing command-eval child process: {pre_orphan}")

    corpus = build_command_usability_corpus(min_cases=1000)
    selected = _select_250_cases(corpus)
    feature_map = build_feature_map()
    feature_audit = build_feature_audit(selected)
    write_json(args.output_dir / "feature_map.json", feature_map)
    write_json(args.output_dir / "feature_map_audit.json", feature_audit)
    write_jsonl(args.output_dir / "250_corpus.jsonl", [case.to_dict() for case in selected])

    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(selected, results_name="250_results.jsonl", resume=args.resume)
    rows = _read_jsonl(args.output_dir / "250_results.jsonl")
    checkpoint = _read_json(args.output_dir / "250_results.checkpoint.json")
    post_orphan = _orphan_process_check_result()

    summary = _summary(
        rows=rows,
        results=results,
        selected=selected,
        feature_audit=feature_audit,
        checkpoint=checkpoint,
        pre_orphan=pre_orphan,
        post_orphan=post_orphan,
        args=args,
    )
    route_confusion = _route_confusion_matrix(rows)
    latency_summary = _latency_summary(rows)
    failure_census = _failure_census(rows)
    payload_diagnostics = _payload_diagnostics(rows)
    telemetry_audit = _telemetry_gap_audit(rows)
    known_lanes = _known_lanes(rows)
    recommendation = _recommendation(summary, failure_census, known_lanes)
    summary["recommendation"] = recommendation["recommendation"]
    summary["recommendation_detail"] = recommendation

    write_json(args.output_dir / "250_summary.json", summary)
    write_jsonl(args.output_dir / "250_payload_diagnostics.jsonl", payload_diagnostics)
    write_json(args.output_dir / "250_route_confusion_matrix.json", route_confusion)
    write_json(args.output_dir / "250_latency_summary.json", latency_summary)
    write_json(args.output_dir / "250_failure_census.json", failure_census)
    (args.output_dir / "250_failure_census.md").write_text(_failure_census_markdown(failure_census), encoding="utf-8")
    (args.output_dir / "250_known_lanes_report.md").write_text(_known_lanes_markdown(known_lanes), encoding="utf-8")
    (args.output_dir / "250_telemetry_gap_audit.md").write_text(_telemetry_gap_markdown(telemetry_audit), encoding="utf-8")
    write_json(args.output_dir / "250_recommendation.json", recommendation)
    (args.output_dir / "250_checkpoint_report.md").write_text(
        _checkpoint_report(
            summary=summary,
            route_confusion=route_confusion,
            latency_summary=latency_summary,
            failure_census=failure_census,
            known_lanes=known_lanes,
            telemetry_audit=telemetry_audit,
        ),
        encoding="utf-8",
    )

    for name in (
        "250_results.jsonl",
        "250_summary.json",
        "250_checkpoint_report.md",
        "250_payload_diagnostics.jsonl",
        "250_route_confusion_matrix.json",
        "250_latency_summary.json",
        "250_failure_census.json",
        "250_failure_census.md",
        "250_known_lanes_report.md",
        "250_telemetry_gap_audit.md",
        "250_recommendation.json",
    ):
        print(f"{name}: {args.output_dir / name}")


def _select_250_cases(corpus: list[Any]) -> list[Any]:
    selected: list[Any] = []
    seen: set[str] = set()

    def add(case: Any) -> None:
        if len(selected) >= 250 or case.case_id in seen:
            return
        selected.append(case)
        seen.add(case.case_id)

    families = sorted({case.expected.route_family for case in corpus})
    for family in families:
        canonical = next((case for case in corpus if case.expected.route_family == family and _style(case) == "canonical"), None)
        if canonical is not None:
            add(canonical)

    for style in STYLE_ORDER:
        case = next((item for item in corpus if _style(item) == style), None)
        if case is not None:
            add(case)

    for style in STYLE_ORDER:
        for family in families:
            case = next((item for item in corpus if item.expected.route_family == family and _style(item) == style), None)
            if case is not None:
                add(case)

    scenario_families = sorted({_scenario_family(case.case_id) for case in corpus})
    for scenario in scenario_families:
        canonical = next((case for case in corpus if _scenario_family(case.case_id) == scenario and _style(case) == "canonical"), None)
        command_mode = next((case for case in corpus if _scenario_family(case.case_id) == scenario and _style(case) == "command_mode"), None)
        if canonical is not None:
            add(canonical)
        if command_mode is not None:
            add(command_mode)

    for style in STYLE_ORDER:
        for case in corpus:
            if _style(case) == style:
                add(case)

    for case in corpus:
        add(case)
    return selected[:250]


def _summary(
    *,
    rows: list[dict[str, Any]],
    results: list[Any],
    selected: list[Any],
    feature_audit: dict[str, Any],
    checkpoint: dict[str, Any],
    pre_orphan: str,
    post_orphan: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    failed = [row for row in rows if not row.get("passed")]
    scored = [row for row in rows if row.get("score_in_pass_fail")]
    excluded = [row for row in rows if not row.get("score_in_pass_fail")]
    scored_failed = [row for row in scored if not row.get("passed")]
    excluded_failed = [row for row in excluded if not row.get("passed")]
    known_lane_counts = Counter(label for row in rows for label in row.get("known_lane_labels") or [])
    focused_summary = _read_json(FOCUSED_80_DIR / "focused_80_250_readiness_summary.json")
    checkpoint_summary = build_checkpoint_summary(results, feature_audit=feature_audit)
    return {
        "attempted": len(selected),
        "completed": len(results),
        "durable_rows": len(rows),
        "completed_equals_durable_rows": len(results) == len(rows),
        "checkpoint_rows": int(checkpoint.get("completed") or 0),
        "resume_status": {
            "resume_requested": bool(args.resume),
            "checkpoint_done": bool(checkpoint.get("done")),
            "skipped_existing": int(checkpoint.get("skipped_existing") or 0),
            "checkpoint_path": str(args.output_dir / "250_results.checkpoint.json"),
            "report_regenerated_from_existing_rows": bool(args.resume and int(checkpoint.get("skipped_existing") or 0) == len(selected)),
            "note": (
                "Final reports were regenerated from existing durable rows; no requests were rerun."
                if args.resume and int(checkpoint.get("skipped_existing") or 0) == len(selected)
                else "Requests were executed for pending cases in this invocation."
            ),
        },
        "harness": {
            "input_boundary": "real HTTP POST /chat/send",
            "process_isolated": True,
            "hard_timeout_seconds": float(args.timeout_seconds),
            "history_strategy": "isolated_session",
            "process_scope": args.process_scope,
            "dry_run_enabled": True,
            "provider_disabled": True,
            "real_external_actions_disabled": True,
        },
        "safety": {
            "provider_calls": sum(1 for row in rows if row.get("provider_called")),
            "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
            "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout" or row.get("failure_category") == "hard_timeout"),
            "process_kills": sum(1 for row in rows if row.get("process_killed")),
            "pre_run_orphan_process_check": pre_orphan,
            "orphan_process_check": post_orphan,
        },
        "raw_counts": {
            "pass": sum(1 for row in rows if row.get("passed")),
            "fail": len(failed),
            "excluded": len(excluded),
        },
        "scored_counts": {
            "pass": sum(1 for row in scored if row.get("passed")),
            "fail": len(scored_failed),
            "excluded": len(excluded),
        },
        "failure_counts": {
            "raw_failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in failed).items())),
            "scored_failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in scored_failed).items())),
            "excluded_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in excluded_failed).items())),
            "known_lane_counts": dict(sorted(known_lane_counts.items())),
        },
        "corpus_coverage": {
            "route_family": dict(sorted(Counter(str(row.get("expected_route_family") or "") for row in rows).items())),
            "subsystem": dict(sorted(Counter(str(row.get("expected_subsystem") or "") for row in rows).items())),
            "wording_style": dict(sorted(Counter(str(row.get("wording_style") or _style_from_row(row) or "") for row in rows).items())),
            "deictic_follow_up": sum(1 for row in rows if (row.get("wording_style") or "") in {"deictic", "follow_up"}),
            "near_miss_ambiguous": sum(1 for row in rows if (row.get("wording_style") or "") in {"near_miss", "ambiguous"}),
        },
        "route_family_coverage": {
            "expected": dict(sorted(Counter(str(row.get("expected_route_family") or "") for row in rows).items())),
            "actual": dict(sorted(Counter(str(row.get("actual_route_family") or "") for row in rows).items())),
        },
        "generic_provider_fallback_count_by_expected_family": dict(
            sorted(Counter(str(row.get("expected_route_family") or "") for row in rows if row.get("actual_route_family") == "generic_provider").items())
        ),
        "latency_summary_ms": _percentiles([float(row.get("latency_ms") or row.get("total_latency_ms") or 0.0) for row in rows]),
        "payload_summary": _payload_summary(rows),
        "focused_80_readiness_comparison": _focused_comparison(focused_summary, rows),
        "checkpoint_summary": checkpoint_summary,
    }


def _failure_census(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [row for row in rows if not row.get("passed")]
    scored_failed = [row for row in failed if row.get("score_in_pass_fail")]
    by_category = defaultdict(list)
    for row in failed:
        by_category[str(row.get("failure_category") or "")].append(_failure(row))
    return {
        "total_failures": len(failed),
        "scored_failures": len(scored_failed),
        "by_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in failed).items())),
        "real_routing_gaps": [_failure(row) for row in failed if row.get("failure_category") == "real_routing_gap"],
        "wrong_subsystem": [_failure(row) for row in failed if row.get("failure_category") == "wrong_subsystem"],
        "clarification_failures": [_failure(row) for row in failed if row.get("failure_category") == "clarification_failure" or "clarification" in str(row.get("failure_reason") or "")],
        "approval_expectation_mismatches": [
            _failure(row)
            for row in failed
            if row.get("failure_category") == "approval_expectation_mismatch" or "approval" in str(row.get("failure_reason") or "")
        ],
        "truthfulness_failures": [_failure(row) for row in failed if row.get("failure_category") == "truthfulness_failure"],
        "generic_provider_fallbacks": [_failure(row) for row in rows if row.get("actual_route_family") == "generic_provider"],
        "native_capable_generic_fallback_examples": [
            _failure(row)
            for row in rows
            if row.get("actual_route_family") == "generic_provider" and row.get("score_in_pass_fail") and row.get("expected_route_family") != "generic_provider"
        ][:20],
        "top_30_failures_by_severity": [_failure(row) for row in sorted(failed, key=_failure_sort_key)[:30]],
        "by_category_examples": {category: values[:20] for category, values in sorted(by_category.items())},
    }


def _latency_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row.get("latency_ms") or row.get("total_latency_ms") or 0.0) for row in rows]
    by_family: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_family[str(row.get("expected_route_family") or "")].append(float(row.get("latency_ms") or 0.0))
    return {
        "overall_ms": _percentiles(values),
        "by_route_family_ms": {family: _percentiles(vals) for family, vals in sorted(by_family.items())},
        "slowest_20": [_failure(row) for row in sorted(rows, key=lambda item: float(item.get("latency_ms") or 0.0), reverse=True)[:20]],
        "known_workspace_latency_lane_rows": [
            _failure(row)
            for row in rows
            if "known_workspace_latency_lane" in (row.get("known_lane_labels") or [])
        ],
    }


def _payload_diagnostics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diagnostics = []
    for row in rows:
        diagnostics.append(
            {
                "run_id": row.get("run_id"),
                "test_id": row.get("test_id"),
                "expected_route_family": row.get("expected_route_family"),
                "actual_route_family": row.get("actual_route_family"),
                "response_json_bytes": row.get("response_json_bytes"),
                "workspace_item_count": row.get("workspace_item_count"),
                "active_context_bytes": row.get("active_context_bytes"),
                "active_context_item_count": row.get("active_context_item_count"),
                "truncated_workspace_items": row.get("truncated_workspace_items"),
                "payload_guardrail_triggered": row.get("payload_guardrail_triggered"),
                "payload_guardrail_reason": row.get("payload_guardrail_reason"),
                "largest_payload_fields": row.get("largest_payload_fields"),
                "above_1mb": int(row.get("response_json_bytes") or 0) > PAYLOAD_WARN_BYTES,
                "above_5mb": int(row.get("response_json_bytes") or 0) > PAYLOAD_FAIL_BYTES,
                "failure_category": row.get("failure_category"),
            }
        )
    return diagnostics


def _payload_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sizes = [float(row.get("response_json_bytes") or 0.0) for row in rows]
    payload_failures = [
        _failure(row)
        for row in rows
        if row.get("failure_category") == "payload_guardrail_failure" or int(row.get("response_json_bytes") or 0) > PAYLOAD_FAIL_BYTES
    ]
    return {
        "response_json_bytes": _percentiles(sizes),
        "rows_above_1mb": [_failure(row) for row in rows if int(row.get("response_json_bytes") or 0) > PAYLOAD_WARN_BYTES],
        "rows_above_5mb": [_failure(row) for row in rows if int(row.get("response_json_bytes") or 0) > PAYLOAD_FAIL_BYTES],
        "max_workspace_item_count": max((int(row.get("workspace_item_count") or 0) for row in rows), default=0),
        "payload_guardrail_failures": payload_failures,
        "top_largest_payload_rows": [_failure(row) for row in sorted(rows, key=lambda item: int(item.get("response_json_bytes") or 0), reverse=True)[:20]],
    }


def _known_lanes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(label for row in rows for label in row.get("known_lane_labels") or [])
    workspace_rows = [row for row in rows if "known_workspace_latency_lane" in (row.get("known_lane_labels") or [])]
    routine_rows = [row for row in rows if "known_unreproduced_product_latency_blocker" in (row.get("historical_blocker_labels") or [])]
    return {
        "counts": dict(sorted(labels.items())),
        "known_workspace_latency_lane": {
            "count": len(workspace_rows),
            "latency_ms": _percentiles([float(row.get("latency_ms") or 0.0) for row in workspace_rows]),
            "bounded": not any(row.get("failure_category") == "hard_timeout" for row in workspace_rows),
            "payload_safe": not any(row.get("failure_category") == "payload_guardrail_failure" for row in workspace_rows),
            "rows": [_failure(row) for row in workspace_rows[:50]],
        },
        "routine_save": {
            "count": len(routine_rows),
            "historical_status": "known_unreproduced_product_latency_blocker",
            "old_catastrophic_shape_reappeared": any(float(row.get("latency_ms") or 0.0) >= 43_000 for row in routine_rows),
            "rows": [_failure(row) for row in routine_rows],
        },
        "trusted_hook_register": {
            "count": sum(1 for row in rows if "trusted_hook_register_feature_map_overexpectation" in (row.get("known_lane_labels") or [])),
            "rows": [_failure(row) for row in rows if "trusted_hook_register_feature_map_overexpectation" in (row.get("known_lane_labels") or [])],
        },
    }


def _telemetry_gap_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    audited = []
    for row in rows:
        missing_route = not row.get("route_state")
        missing_obedience = bool(row.get("actual_tool")) and not row.get("planner_obedience")
        if not missing_route and not missing_obedience:
            continue
        surface = str(row.get("route_surface_type") or "")
        route_required = surface == "planner"
        planner_required = surface == "planner"
        audited.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt"),
                "expected_family": row.get("expected_route_family"),
                "actual_family": row.get("actual_route_family"),
                "route_surface_type": surface,
                "route_state_required": route_required,
                "planner_obedience_required": planner_required,
                "missing_route_state": missing_route,
                "missing_planner_obedience": missing_obedience,
                "reason": "direct/legacy route exempted" if not route_required else "planner-backed row should expose route telemetry",
            }
        )
    return {
        "missing_route_state": sum(1 for row in audited if row["missing_route_state"]),
        "missing_planner_obedience": sum(1 for row in audited if row["missing_planner_obedience"]),
        "by_surface_type": dict(sorted(Counter(str(row.get("route_surface_type") or "") for row in audited).items())),
        "rows": audited,
    }


def _route_confusion_matrix(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        matrix[str(row.get("expected_route_family") or "")][str(row.get("actual_route_family") or "")] += 1
    return {family: dict(sorted(actual.items())) for family, actual in sorted(matrix.items())}


def _recommendation(summary: dict[str, Any], failure_census: dict[str, Any], known_lanes: dict[str, Any]) -> dict[str, Any]:
    safety = summary.get("safety", {})
    payload = summary.get("payload_summary", {})
    if safety.get("real_external_actions"):
        recommendation = "block 1000 until safety issue is fixed"
    elif safety.get("provider_calls"):
        recommendation = "block 1000 until provider-disable path is fixed"
    elif safety.get("hard_timeouts") and not summary.get("completed_equals_durable_rows"):
        recommendation = "fix harness before broader evaluation"
    elif payload.get("payload_guardrail_failures"):
        recommendation = "fix payload guardrail failures before 1000"
    elif failure_census.get("real_routing_gaps") or failure_census.get("wrong_subsystem"):
        recommendation = "proceed to targeted fixes before 1000"
    elif summary.get("scored_counts", {}).get("fail"):
        recommendation = "proceed to targeted latency/expectation fixes before 1000"
    else:
        recommendation = "proceed to 1000"
    return {
        "recommendation": recommendation,
        "rationale": {
            "safety": safety,
            "scored_counts": summary.get("scored_counts"),
            "real_routing_gap_count": len(failure_census.get("real_routing_gaps") or []),
            "wrong_subsystem_count": len(failure_census.get("wrong_subsystem") or []),
            "payload_guardrail_failures": len(payload.get("payload_guardrail_failures") or []),
            "known_workspace_latency_lane": known_lanes.get("known_workspace_latency_lane", {}),
        },
    }


def _checkpoint_report(
    *,
    summary: dict[str, Any],
    route_confusion: dict[str, dict[str, int]],
    latency_summary: dict[str, Any],
    failure_census: dict[str, Any],
    known_lanes: dict[str, Any],
    telemetry_audit: dict[str, Any],
) -> str:
    lines = [
        "# Stormhelm 250-Case Command-Usability Checkpoint",
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
        _fmt({key: summary[key] for key in ("attempted", "completed", "durable_rows", "checkpoint_rows", "completed_equals_durable_rows")}),
        _fmt(summary["resume_status"]),
        "",
        "## 4. Corpus Coverage",
        "- route-family coverage:",
        _fmt(summary["corpus_coverage"]["route_family"]),
        "- subsystem coverage:",
        _fmt(summary["corpus_coverage"]["subsystem"]),
        "- wording-style coverage:",
        _fmt(summary["corpus_coverage"]["wording_style"]),
        f"- deictic/follow-up rows: {summary['corpus_coverage']['deictic_follow_up']}",
        f"- near-miss/ambiguous rows: {summary['corpus_coverage']['near_miss_ambiguous']}",
        "",
        "## 5. Raw And Scored Pass/Fail",
        f"- raw: {summary['raw_counts']}",
        f"- scored: {summary['scored_counts']}",
        f"- known-lane labels: {summary['failure_counts']['known_lane_counts']}",
        "",
        "## 6. Failure Category Counts",
        _fmt(summary["failure_counts"]),
        "",
        "## 7. Route Confusion Matrix",
        _fmt(route_confusion),
        "",
        "## 8. Generic-Provider Fallback Summary",
        _fmt(summary["generic_provider_fallback_count_by_expected_family"]),
        _section_rows("Native-capable fallback examples", failure_census["native_capable_generic_fallback_examples"]),
        "",
        "## 9. Wrong-Subsystem Summary",
        f"- count: {len(failure_census['wrong_subsystem'])}",
        _markdown_rows(failure_census["wrong_subsystem"][:20]),
        "",
        "## 10. Real Routing Gap Summary",
        f"- count: {len(failure_census['real_routing_gaps'])}",
        _markdown_rows(failure_census["real_routing_gaps"][:20]),
        "",
        "## 11. Clarification Failure Summary",
        f"- count: {len(failure_census['clarification_failures'])}",
        _markdown_rows(failure_census["clarification_failures"][:20]),
        "",
        "## 12. Approval/Trust Summary",
        f"- approval expectation mismatches: {len(failure_census['approval_expectation_mismatches'])}",
        _markdown_rows(failure_census["approval_expectation_mismatches"][:20]),
        "",
        "## 13. Truthfulness/Result-State Summary",
        f"- truthfulness failures: {len(failure_census['truthfulness_failures'])}",
        _markdown_rows(failure_census["truthfulness_failures"][:20]),
        "",
        "## 14. Latency Summary",
        _fmt(latency_summary["overall_ms"]),
        "- slowest 20:",
        _markdown_rows(latency_summary["slowest_20"]),
        "- latency by route family:",
        _fmt(latency_summary["by_route_family_ms"]),
        "",
        "## 15. Payload Summary",
        _fmt(summary["payload_summary"]),
        "",
        "## 16. Workspace Latency Lane Analysis",
        _fmt(known_lanes["known_workspace_latency_lane"]),
        "",
        "## 17. Routine-Save Summary",
        _fmt(known_lanes["routine_save"]),
        "",
        "## 18. Telemetry Gap Audit",
        _fmt({key: value for key, value in telemetry_audit.items() if key != "rows"}),
        _markdown_rows(telemetry_audit["rows"][:30]),
        "",
        "## 19. Comparison Against Focused-80 Readiness",
        _fmt(summary["focused_80_readiness_comparison"]),
        "",
        "## 20. Top 30 Failures By Severity",
        _markdown_rows(failure_census["top_30_failures_by_severity"]),
        "",
        "## 21. Good Findings",
        _good_findings(summary, failure_census),
        "",
        "## 22. Bad Findings",
        _bad_findings(summary, failure_census, known_lanes),
        "",
        "## 23. Recommendation",
        f"- {summary['recommendation']}",
    ]
    return "\n".join(lines).strip() + "\n"


def _failure_census_markdown(census: dict[str, Any]) -> str:
    lines = ["# 250 Failure Census", "", "## Counts", _fmt(census["by_category_counts"])]
    for key in ("real_routing_gaps", "wrong_subsystem", "clarification_failures", "approval_expectation_mismatches", "truthfulness_failures", "generic_provider_fallbacks"):
        lines.extend(["", f"## {key.replace('_', ' ').title()}", _markdown_rows(census.get(key, [])[:50])])
    lines.extend(["", "## Top 30 By Severity", _markdown_rows(census["top_30_failures_by_severity"])])
    return "\n".join(lines).strip() + "\n"


def _known_lanes_markdown(known_lanes: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# 250 Known Lanes Report",
            "",
            "## Counts",
            _fmt(known_lanes["counts"]),
            "",
            "## Workspace Latency Lane",
            _fmt(known_lanes["known_workspace_latency_lane"]),
            "",
            "## Routine Save Historical Blocker",
            _fmt(known_lanes["routine_save"]),
            "",
            "## Trusted Hook Register Feature-Map Overexpectation",
            _fmt(known_lanes["trusted_hook_register"]),
        ]
    ).strip() + "\n"


def _telemetry_gap_markdown(audit: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# 250 Telemetry Gap Audit",
            "",
            _fmt({key: value for key, value in audit.items() if key != "rows"}),
            "",
            "## Rows",
            _markdown_rows(audit["rows"]),
        ]
    ).strip() + "\n"


def _good_findings(summary: dict[str, Any], failure_census: dict[str, Any]) -> str:
    good = []
    if not summary["safety"]["provider_calls"] and not summary["safety"]["real_external_actions"]:
        good.append("Safety controls held: no provider calls and no real external actions.")
    if not summary["payload_summary"]["payload_guardrail_failures"]:
        good.append("Payload guardrails held; no rows exceeded 1 MB or 5 MB.")
    if not failure_census["wrong_subsystem"]:
        good.append("No wrong-subsystem failures were observed.")
    if not failure_census["real_routing_gaps"]:
        good.append("No scored real routing gaps were observed.")
    return "\n".join(f"- {item}" for item in good) if good else "- None."


def _bad_findings(summary: dict[str, Any], failure_census: dict[str, Any], known_lanes: dict[str, Any]) -> str:
    findings = []
    scored_counts = summary.get("scored_counts", {})
    if scored_counts.get("fail"):
        findings.append(f"{scored_counts['fail']} scored failures remain.")
    workspace_count = known_lanes.get("known_workspace_latency_lane", {}).get("count", 0)
    if workspace_count:
        findings.append(f"{workspace_count} rows are in the known workspace latency lane.")
    if failure_census["generic_provider_fallbacks"]:
        findings.append(f"{len(failure_census['generic_provider_fallbacks'])} generic-provider fallbacks occurred; excluded/scaffold rows must stay separated.")
    return "\n".join(f"- {item}" for item in findings) if findings else "- None."


def _focused_comparison(focused_summary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not focused_summary:
        return {}
    return {
        "focused_80_scored_counts": focused_summary.get("scored_counts"),
        "focused_80_raw_counts": focused_summary.get("raw_counts"),
        "focused_80_latency_p95_ms": (focused_summary.get("latency_summary_ms") or {}).get("p95"),
        "focused_80_payload_max_bytes": ((focused_summary.get("payload_summary") or {}).get("response_json_bytes") or {}).get("max"),
        "checkpoint_250_scored_counts": {
            "pass": sum(1 for row in rows if row.get("score_in_pass_fail") and row.get("passed")),
            "fail": sum(1 for row in rows if row.get("score_in_pass_fail") and not row.get("passed")),
            "excluded": sum(1 for row in rows if not row.get("score_in_pass_fail")),
        },
        "checkpoint_250_latency_p95_ms": _percentiles([float(row.get("latency_ms") or 0.0) for row in rows]).get("p95"),
        "checkpoint_250_payload_max_bytes": _percentiles([float(row.get("response_json_bytes") or 0.0) for row in rows]).get("max"),
    }


def _failure(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "prompt": row.get("prompt"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "expected_subsystem": row.get("expected_subsystem"),
        "actual_subsystem": row.get("actual_subsystem"),
        "expected_tool": row.get("expected_tool"),
        "actual_tool": row.get("actual_tool"),
        "result_state": row.get("actual_result_state") or row.get("result_state"),
        "failure_category": row.get("failure_category"),
        "failure_reason": row.get("failure_reason"),
        "latency_ms": row.get("latency_ms"),
        "response_json_bytes": row.get("response_json_bytes"),
        "route_scores": row.get("route_scores"),
        "fallback_reason": row.get("fallback_reason"),
        "known_lane_labels": row.get("known_lane_labels"),
        "likely_fix_area": _likely_fix_area(row),
    }


def _likely_fix_area(row: dict[str, Any]) -> str:
    category = str(row.get("failure_category") or "")
    if category in {"real_routing_gap", "wrong_subsystem"}:
        return "planner routing ownership"
    if category in {"clarification_failure", "response_correctness_failure"}:
        return "native handler response/clarification"
    if category in {"latency_issue", "known_workspace_latency_lane"}:
        return f"{row.get('expected_route_family')} latency"
    if category == "payload_guardrail_failure":
        return "payload DTO guardrails"
    if category == "missing_telemetry":
        return "route telemetry"
    if category == "feature_map_overexpectation":
        return "feature map/corpus routeability"
    return category or "unknown"


def _failure_sort_key(row: dict[str, Any]) -> tuple[int, float]:
    return (SEVERITY_ORDER.get(str(row.get("failure_category") or ""), 50), -float(row.get("latency_ms") or 0.0))


def _percentiles(values: list[float]) -> dict[str, float | int | None]:
    values = sorted(float(value or 0.0) for value in values)
    if not values:
        return {"count": 0, "min": None, "median": None, "p90": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "min": round(values[0], 3),
        "median": round(median(values), 3),
        "p90": _percentile(values, 0.90),
        "p95": _percentile(values, 0.95),
        "max": round(values[-1], 3),
    }


def _percentile(values: list[float], p: float) -> float:
    if len(values) == 1:
        return round(values[0], 3)
    index = (len(values) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return round(values[lower] * (1 - fraction) + values[upper] * fraction, 3)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _scenario_family(case_id: str) -> str:
    for style in STYLE_ORDER:
        marker = f"_{style}_"
        if marker in case_id:
            return case_id.split(marker, 1)[0]
    return case_id.rsplit("_", 2)[0]


def _style(case: Any) -> str:
    return _style_from_id_tags(case.case_id, case.tags)


def _style_from_row(row: dict[str, Any]) -> str:
    case = row.get("case") if isinstance(row.get("case"), dict) else {}
    return _style_from_id_tags(str(row.get("test_id") or ""), tuple(str(item) for item in case.get("tags") or ()))


def _style_from_id_tags(case_id: str, tags: tuple[str, ...]) -> str:
    for style in STYLE_ORDER:
        if f"_{style}_" in case_id:
            return style
    for style in STYLE_ORDER:
        if style in tags:
            return style
    return ""


def _section_rows(title: str, rows: list[dict[str, Any]]) -> str:
    return f"### {title}\n{_markdown_rows(rows)}"


def _fmt(payload: Any) -> str:
    if not payload:
        return "- none"
    if isinstance(payload, dict):
        lines = []
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, sort_keys=True, default=str)
                if len(rendered) > 1200:
                    rendered = rendered[:1200] + "... <truncated>"
                lines.append(f"- {key}: {rendered}")
            else:
                lines.append(f"- {key}: {value}")
        return "\n".join(lines)
    if isinstance(payload, list):
        return _markdown_rows(payload)
    return str(payload)


def _markdown_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- none"
    lines = []
    for row in rows:
        rendered = json.dumps(row, sort_keys=True, default=str)
        if len(rendered) > 1400:
            rendered = rendered[:1400] + "... <truncated>"
        lines.append(f"- `{row.get('test_id') or row.get('case_id') or '<row>'}`: {rendered}")
    return "\n".join(lines)


def _orphan_process_check_result() -> str:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -like 'python*' -and ($_.CommandLine -like '*serve_command_eval_core.py*' -or $_.CommandLine -like '*run_250_checkpoint.py*') } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(["powershell", "-NoProfile", "-Command", command], text=True, capture_output=True, timeout=60)
    output = (completed.stdout or "").strip()
    # Ignore the current report process; this check is mainly for lingering child Core servers.
    if "serve_command_eval_core.py" not in output:
        return "no_orphan_command_eval_processes_detected"
    return f"possible_processes_detected: {output[:1000]}"


if __name__ == "__main__":
    main()
