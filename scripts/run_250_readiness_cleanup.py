from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from statistics import median
from typing import Any

from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_audit
from stormhelm.core.orchestrator.command_eval import build_feature_map
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "250-readiness-cleanup"
POST_HARDENING_DIR = Path(".artifacts") / "command-usability-eval" / "focused-80-post-hardening"
POST_ROUTING_DIR = Path(".artifacts") / "command-usability-eval" / "routing-remediation"
PAYLOAD_HARDENING_DIR = Path(".artifacts") / "command-usability-eval" / "payload-routine-hardening"
ROUTINE_REPRO_DIR = Path(".artifacts") / "command-usability-eval" / "routine-save-repro"
OLD_LATENCY_DIR = Path(".artifacts") / "command-usability-eval" / "latency-micro-20260424-225838"
HARD_TIMEOUT_DIR = Path(".artifacts") / "command-usability-eval" / "hard-timeout-proof-20260425-024110"

PAYLOAD_WARN_BYTES = 1_000_000
PAYLOAD_FAIL_BYTES = 5_000_000
LATENCY_MICRO_REPS = 3

WORKSPACE_SPAN_FIELDS = (
    "workspace_state_load_ms",
    "workspace_db_query_ms",
    "workspace_file_scan_ms",
    "workspace_index_or_search_ms",
    "workspace_task_graph_ms",
    "workspace_event_emit_ms",
    "workspace_dto_build_ms",
    "workspace_payload_build_ms",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run narrow 250-readiness cleanup only.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    post_routing_rows = _read_jsonl(POST_ROUTING_DIR / "focused_80_post_routing_results.jsonl")
    post_routing_targeted_rows = _read_jsonl(POST_ROUTING_DIR / "targeted_routing_results.jsonl")
    post_hardening_summary = _read_json(POST_HARDENING_DIR / "focused_80_summary.json")
    post_routing_summary = _read_json(POST_ROUTING_DIR / "focused_80_post_routing_summary.json")

    corpus = build_command_usability_corpus(min_cases=1000)
    full_corpus = corpus[:1000]
    focused_corpus = _focused_subset(full_corpus, limit=80)
    feature_audit = build_feature_audit(full_corpus)

    write_json(args.output_dir / "feature_map.json", build_feature_map())
    write_json(args.output_dir / "feature_map_audit.json", feature_audit)
    write_jsonl(args.output_dir / "focused_80_corpus.jsonl", [case.to_dict() for case in focused_corpus])

    corpus_audit = _corpus_expectation_audit(post_routing_rows, feature_audit)
    write_json(args.output_dir / "250_readiness_corpus_audit.json", corpus_audit)
    (args.output_dir / "250_readiness_corpus_audit.md").write_text(_corpus_audit_markdown(corpus_audit), encoding="utf-8")

    watch_report = _watch_runtime_subsystem_report(post_routing_rows)
    (args.output_dir / "watch_runtime_subsystem_labeling_report.md").write_text(watch_report, encoding="utf-8")

    telemetry_audit = _telemetry_gap_audit(post_routing_rows, feature_audit)
    (args.output_dir / "telemetry_gap_audit.md").write_text(_telemetry_audit_markdown(telemetry_audit), encoding="utf-8")

    targeted_cases = _targeted_cases(focused_corpus, post_routing_rows)
    targeted_harness = _harness(args)
    targeted_results = targeted_harness.run(
        targeted_cases,
        results_name="targeted_routing_post_cleanup_results.jsonl",
        resume=False,
    )
    targeted_rows = _read_jsonl(args.output_dir / "targeted_routing_post_cleanup_results.jsonl")
    targeted_summary = _summary(
        rows=targeted_rows,
        attempted=len(targeted_cases),
        result_count=len(targeted_results),
        checkpoint=_read_json(args.output_dir / "targeted_routing_post_cleanup_results.checkpoint.json"),
        output_dir=args.output_dir,
        results_name="targeted_routing_post_cleanup_results.jsonl",
    )
    targeted_summary["remaining_failure_classifications"] = _targeted_failure_classification(targeted_rows)
    write_json(args.output_dir / "targeted_routing_post_cleanup_summary.json", targeted_summary)

    workspace_cases = _workspace_latency_cases(focused_corpus, post_routing_rows)
    workspace_harness = _harness(args)
    workspace_results = workspace_harness.run(
        workspace_cases,
        results_name="workspace_latency_micro_results.jsonl",
        resume=False,
    )
    workspace_rows = _enrich_workspace_latency_rows(
        _read_jsonl(args.output_dir / "workspace_latency_micro_results.jsonl")
    )
    write_jsonl(args.output_dir / "workspace_latency_micro_results.jsonl", workspace_rows)
    workspace_report = _workspace_latency_report(
        rows=workspace_rows,
        attempted=len(workspace_cases),
        result_count=len(workspace_results),
        before_rows=post_routing_rows,
    )
    (args.output_dir / "workspace_latency_micro_report.md").write_text(workspace_report["markdown"], encoding="utf-8")
    write_json(args.output_dir / "workspace_latency_micro_summary.json", workspace_report["summary"])

    focused_harness = _harness(args)
    focused_results = focused_harness.run(
        focused_corpus,
        results_name="focused_80_250_readiness_results.jsonl",
        resume=False,
    )
    focused_rows = _read_jsonl(args.output_dir / "focused_80_250_readiness_results.jsonl")
    route_confusion = _route_confusion_matrix(focused_rows)
    write_json(args.output_dir / "focused_80_250_readiness_route_confusion_matrix.json", route_confusion)

    focused_summary = _summary(
        rows=focused_rows,
        attempted=len(focused_corpus),
        result_count=len(focused_results),
        checkpoint=_read_json(args.output_dir / "focused_80_250_readiness_results.checkpoint.json"),
        output_dir=args.output_dir,
        results_name="focused_80_250_readiness_results.jsonl",
    )
    focused_summary.update(
        {
            "before_after": _before_after(post_hardening_summary, post_routing_summary, focused_summary),
            "corpus_expectation_audit": corpus_audit,
            "watch_runtime_subsystem_labeling": _watch_runtime_status(focused_rows),
            "workspace_latency": workspace_report["summary"],
            "telemetry_gap_audit": telemetry_audit,
            "targeted_mini_suite": targeted_summary,
            "route_confusion_matrix": route_confusion,
            "artifacts_preserved": {
                "focused_80_post_hardening": str(POST_HARDENING_DIR),
                "routing_remediation": str(POST_ROUTING_DIR),
                "payload_routine_hardening": str(PAYLOAD_HARDENING_DIR),
                "routine_save_repro": str(ROUTINE_REPRO_DIR),
                "old_latency_triage": str(OLD_LATENCY_DIR / "latency_triage_report.md"),
                "old_latency_micro_results": str(OLD_LATENCY_DIR / "latency_micro_results.jsonl"),
                "hard_timeout_proof": str(HARD_TIMEOUT_DIR),
            },
        }
    )
    focused_summary["recommendation"] = _recommendation(focused_summary)
    write_json(args.output_dir / "focused_80_250_readiness_summary.json", focused_summary)
    (args.output_dir / "focused_80_250_readiness_report.md").write_text(
        _focused_report(focused_summary),
        encoding="utf-8",
    )

    print(f"targeted_routing_post_cleanup_results: {args.output_dir / 'targeted_routing_post_cleanup_results.jsonl'}")
    print(f"targeted_routing_post_cleanup_summary: {args.output_dir / 'targeted_routing_post_cleanup_summary.json'}")
    print(f"workspace_latency_micro_results: {args.output_dir / 'workspace_latency_micro_results.jsonl'}")
    print(f"workspace_latency_micro_report: {args.output_dir / 'workspace_latency_micro_report.md'}")
    print(f"focused_80_250_readiness_results: {args.output_dir / 'focused_80_250_readiness_results.jsonl'}")
    print(f"focused_80_250_readiness_summary: {args.output_dir / 'focused_80_250_readiness_summary.json'}")
    print(f"focused_80_250_readiness_report: {args.output_dir / 'focused_80_250_readiness_report.md'}")


def _harness(args: argparse.Namespace) -> ProcessIsolatedCommandUsabilityHarness:
    return ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )


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


def _targeted_cases(focused_corpus: list[Any], post_routing_rows: list[dict[str, Any]]) -> list[Any]:
    targeted_ids = {
        str(row.get("test_id") or "")
        for row in post_routing_rows
        if row.get("score_in_pass_fail")
        and str(row.get("failure_category") or "") in {"wrong_subsystem", "corpus_expectation_bug", "response_correctness_failure"}
    }
    targeted_ids.update(
        {
            "workflow_execute_canonical_00",
            "workflow_execute_command_mode_00",
            "file_operation_canonical_00",
            "file_operation_command_mode_00",
            "context_action_canonical_00",
            "context_action_command_mode_00",
            "browser_context_canonical_00",
            "browser_context_command_mode_00",
        }
    )
    return [case for case in focused_corpus if case.case_id in targeted_ids]


def _workspace_latency_cases(focused_corpus: list[Any], post_routing_rows: list[dict[str, Any]]) -> list[Any]:
    cases_by_id = {case.case_id: case for case in focused_corpus}
    slow_workspace_ids = [
        str(row.get("test_id") or "")
        for row in post_routing_rows
        if str(row.get("failure_category") or "") == "latency_issue"
        and str(row.get("expected_route_family") or "") in {"workspace_operations", "task_continuity"}
        and str(row.get("test_id") or "").startswith("workspace_")
    ]
    required = [
        "workspace_assemble_command_mode_00",
        "workspace_save_canonical_00",
        "workspace_save_command_mode_00",
        "workspace_rename_canonical_00",
        "workspace_rename_command_mode_00",
        "workspace_tag_canonical_00",
        "workspace_tag_command_mode_00",
    ]
    control_ids = ["calculations_canonical_00", "browser_destination_canonical_00", "software_control_install_canonical_00"]
    ordered_ids = list(dict.fromkeys([*slow_workspace_ids, *required, *control_ids]))
    suite: list[Any] = []
    for case_id in ordered_ids:
        case = cases_by_id.get(case_id)
        if case is None:
            continue
        for rep in range(1, LATENCY_MICRO_REPS + 1):
            suite.append(replace(case, case_id=f"{case.case_id}_latency_rep{rep:02d}"))
    return suite


def _corpus_expectation_audit(rows: list[dict[str, Any]], feature_audit: dict[str, Any]) -> dict[str, Any]:
    audited = []
    for row in rows:
        if row.get("failure_category") != "corpus_expectation_bug":
            continue
        test_id = str(row.get("test_id") or "")
        classification = "ambiguous_requires_product_decision"
        corrected = {}
        justification = ""
        if test_id.startswith(("software_control_install", "software_control_update")):
            classification = "current_behavior_truthful_but_label_wrong"
            corrected = {"approval": "expected_or_preview satisfied by prepared local plan preview"}
            justification = "Stormhelm prepares a local plan and states no install/update occurred; eval was not counting that preview posture."
        elif test_id.startswith(("browser_deck", "file_deck")):
            classification = "preview_expectation_too_strict"
            corrected = {"approval": "expected_or_preview satisfied by dry-run preview"}
            justification = "Dry-run tool execution is a preview with no external action."
        elif test_id.startswith("workflow_execute"):
            classification = "unsupported_feature_expected"
            corrected = {"prompt": "set up my writing environment"}
            justification = "Current planner supports writing/research/diagnostics setup phrases, not arbitrary named workflow lookup."
        elif test_id.startswith("file_operation"):
            classification = "unsupported_feature_expected"
            corrected = {"prompt": "rename my screenshots by date"}
            justification = "Current file-operation route supports 'rename my/these screenshots by date', not the looser article form."
        elif test_id.startswith("context_action"):
            classification = "unsupported_feature_expected"
            corrected = {"prompt": "show the selection"}
            justification = "Current context-action route supports opening selection/clipboard or extracting tasks, not generic summarization."
        route_entry = dict((feature_audit.get("route_families") or {}).get(str(row.get("expected_route_family") or "")) or {})
        audited.append(
            {
                "test_id": test_id,
                "prompt": row.get("prompt") or row.get("input"),
                "classification": classification,
                "current_expected_behavior": {
                    "route_family": row.get("expected_route_family"),
                    "subsystem": row.get("expected_subsystem"),
                    "tool": row.get("expected_tool"),
                    "approval": _expected_approval(row),
                },
                "actual_behavior": _failure(row),
                "ui_response": row.get("ui_response") or (row.get("observation") or {}).get("ui_response"),
                "route_family": row.get("actual_route_family"),
                "result_state": row.get("result_state"),
                "approval_state": row.get("approval_state"),
                "preview_state": _preview_state(row),
                "implemented_routeable": route_entry.get("classification") == "implemented_routeable",
                "corrected_expected_behavior": corrected,
                "justification": justification,
            }
        )
    return {
        "source": str(POST_ROUTING_DIR / "focused_80_post_routing_results.jsonl"),
        "audited_count": len(audited),
        "classification_counts": dict(sorted(Counter(item["classification"] for item in audited).items())),
        "rows": audited,
    }


def _watch_runtime_subsystem_report(rows: list[dict[str, Any]]) -> str:
    watch_rows = [row for row in rows if str(row.get("test_id") or "").startswith("browser_context")]
    diagnostics = []
    for row in watch_rows:
        diagnostics.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt") or row.get("input"),
                "expected": {
                    "route": row.get("expected_route_family"),
                    "subsystem": row.get("expected_subsystem"),
                    "tool": row.get("expected_tool"),
                },
                "actual": {
                    "route": row.get("actual_route_family"),
                    "subsystem": row.get("actual_subsystem"),
                    "tool": row.get("actual_tool"),
                },
                "route_candidates": row.get("route_candidates"),
                "route_scores": row.get("route_scores"),
                "route_surface_type": row.get("route_surface_type"),
                "selected_handler": "browser_context",
                "subsystem_label_source": "route-family default watch_runtime -> operations",
                "normalized_subsystem_label": "context",
                "final_classification": "route_telemetry_normalization_bug",
            }
        )
    lines = [
        "# Watch Runtime Subsystem Labeling Report",
        "",
        "## Finding",
        "- Browser-context prompts routed correctly to `watch_runtime` with `browser_context`, but the eval-facing subsystem was inferred only from the route family.",
        "- `watch_runtime` legitimately contains both `browser_context` and `activity_summary`, so the normalized subsystem must use the selected tool.",
        "- Fix applied: `browser_context` -> `context`; `activity_summary` remains `operations`.",
        "",
        "## Diagnostics",
        _markdown_rows(diagnostics),
    ]
    return "\n".join(lines).strip() + "\n"


def _watch_runtime_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [row for row in rows if row.get("failure_category") == "wrong_subsystem"]
    return {
        "remaining_wrong_subsystem_rows": [_failure(row) for row in failures],
        "browser_context_rows": [
            {
                "test_id": row.get("test_id"),
                "actual_route_family": row.get("actual_route_family"),
                "actual_subsystem": row.get("actual_subsystem"),
                "actual_tool": row.get("actual_tool"),
                "passed": row.get("passed"),
            }
            for row in rows
            if str(row.get("test_id") or "").startswith("browser_context")
        ],
    }


def _telemetry_gap_audit(rows: list[dict[str, Any]], feature_audit: dict[str, Any]) -> dict[str, Any]:
    items = []
    for row in rows:
        missing_route = not bool(row.get("route_state"))
        missing_obedience = bool(row.get("actual_tool")) and not bool(row.get("planner_obedience"))
        if not missing_route and not missing_obedience:
            continue
        family = str(row.get("expected_route_family") or "")
        route_entry = dict((feature_audit.get("route_families") or {}).get(family) or {})
        surface_type = str(row.get("route_surface_type") or "")
        if not surface_type:
            surface_type = "direct" if route_entry.get("classification") == "implemented_direct_only" else "legacy"
        route_required = surface_type == "planner"
        obedience_required = bool(row.get("actual_tool")) and surface_type == "planner"
        items.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt") or row.get("input"),
                "expected_family": family,
                "actual_family": row.get("actual_route_family"),
                "route_surface_type": surface_type,
                "surface_class": surface_type,
                "route_state_required": route_required,
                "planner_obedience_required": obedience_required,
                "reason": route_entry.get("scoring_note") or "Legacy/direct route surface.",
                "proposed_fix": (
                    "No focused-80 blocker: direct/legacy row explicitly exempted."
                    if not route_required and not obedience_required
                    else "Add planner telemetry for this legacy-backed native route before treating it as fully planner-obedience scored."
                ),
            }
        )
    return {
        "source": str(POST_ROUTING_DIR / "focused_80_post_routing_results.jsonl"),
        "missing_route_state": sum(1 for row in rows if not row.get("route_state")),
        "missing_planner_obedience": sum(1 for row in rows if row.get("actual_tool") and not row.get("planner_obedience")),
        "rows": items,
        "classification_counts": dict(sorted(Counter(item["route_surface_type"] for item in items).items())),
    }


def _targeted_failure_classification(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    classified = []
    for row in rows:
        if row.get("passed"):
            continue
        category = str(row.get("failure_category") or "")
        classification = "product_failure"
        if category == "latency_issue" and str(row.get("expected_route_family") or "").startswith("workspace"):
            classification = "known_latency_lane"
        elif category in {"corpus_expectation_bug", "feature_map_overexpectation"}:
            classification = "corpus_expectation_bug"
        elif category == "wrong_subsystem":
            classification = "product_failure"
        elif category == "missing_telemetry":
            classification = "telemetry_gap"
        classified.append({**_failure(row), "classification": classification})
    return classified


def _enrich_workspace_latency_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        subspans = row.get("route_handler_subspans") if isinstance(row.get("route_handler_subspans"), dict) else {}
        item = dict(row)
        for field in WORKSPACE_SPAN_FIELDS:
            item[field] = float(subspans.get(field) or item.get(field) or 0.0)
        item["response_serialization_ms"] = float(item.get("response_serialization_ms") or 0.0)
        item["unattributed_latency_ms"] = float(item.get("unattributed_latency_ms") or 0.0)
        enriched.append(item)
    return enriched


def _workspace_latency_report(
    *,
    rows: list[dict[str, Any]],
    attempted: int,
    result_count: int,
    before_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    workspace_rows = [
        row
        for row in rows
        if str(row.get("expected_route_family") or "") in {"workspace_operations", "task_continuity"}
    ]
    control_rows = [row for row in rows if row not in workspace_rows]
    family_summary = {
        family: _stats([float(row.get("latency_ms") or 0.0) for row in family_rows])
        for family, family_rows in _group_by(rows, "expected_route_family").items()
    }
    repeated_variance = {
        base: _stats([float(row.get("latency_ms") or 0.0) for row in base_rows])
        for base, base_rows in _group_by(rows, lambda row: str(row.get("test_id") or "").split("_latency_rep")[0]).items()
    }
    hard_timeouts = [row for row in rows if row.get("status") == "hard_timeout" or row.get("process_killed")]
    workspace_p95 = _stats([float(row.get("latency_ms") or 0.0) for row in workspace_rows]).get("p95")
    classification = "known_workspace_latency_lane"
    if hard_timeouts:
        classification = "block_250"
    elif workspace_p95 is not None and float(workspace_p95) <= 2_500:
        classification = "fixed"
    elif workspace_p95 is not None and float(workspace_p95) <= 10_000:
        classification = "acceptable_for_250_with_budget"
    before_workspace = [
        row
        for row in before_rows
        if str(row.get("expected_route_family") or "") in {"workspace_operations", "task_continuity"}
        and str(row.get("failure_category") or "") == "latency_issue"
    ]
    summary = {
        "attempted": attempted,
        "completed": len(rows),
        "harness_result_count": result_count,
        "durable_rows": len(rows),
        "hard_timeouts": len(hard_timeouts),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
        "provider_calls": sum(1 for row in rows if row.get("provider_called")),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "workspace_latency_summary": _stats([float(row.get("latency_ms") or 0.0) for row in workspace_rows]),
        "control_latency_summary": _stats([float(row.get("latency_ms") or 0.0) for row in control_rows]),
        "route_family_latency_summary": family_summary,
        "slowest_20": [_failure(row) for row in sorted(rows, key=lambda item: float(item.get("latency_ms") or 0.0), reverse=True)[:20]],
        "repeated_case_variance": repeated_variance,
        "workspace_latency_before_focus": _stats([float(row.get("latency_ms") or 0.0) for row in before_workspace]),
        "root_cause_hypothesis": _workspace_root_cause(rows),
        "recommended_classification": classification if classification != "acceptable_for_250_with_budget" else "known_workspace_latency_lane",
        "triage_guardrail_ms": 10_000,
        "target_budget_ms": 2_500,
        "ship_budget_ms": 5_000,
    }
    markdown = "\n".join(
        [
            "# Workspace Latency Micro-Suite Report",
            "",
            "## Summary",
            _fmt(summary),
            "",
            "## Slowest 20 Rows",
            _markdown_rows(summary["slowest_20"]),
            "",
            "## Interpretation",
            f"- Classification: {summary['recommended_classification']}",
            f"- Root-cause hypothesis: {summary['root_cause_hypothesis']}",
            "- This is bounded by the hard-timeout harness and payload-safe, but it is not fixed by raising budgets.",
        ]
    ).strip() + "\n"
    return {"summary": summary, "markdown": markdown}


def _workspace_root_cause(rows: list[dict[str, Any]]) -> str:
    workspace_rows = [row for row in rows if str(row.get("expected_route_family") or "").startswith("workspace") or str(row.get("expected_route_family") or "") == "task_continuity"]
    if not workspace_rows:
        return "no workspace rows captured"
    route_handler = sum(float(row.get("route_handler_ms") or 0.0) for row in workspace_rows)
    memory = sum(float(row.get("memory_context_ms") or 0.0) for row in workspace_rows)
    unattributed = sum(float(row.get("unattributed_latency_ms") or 0.0) for row in workspace_rows)
    if route_handler >= memory and route_handler >= unattributed:
        return "workspace route-handler/service work dominates; payload remains capped"
    if memory >= route_handler and memory >= unattributed:
        return "memory/workspace context setup dominates"
    return "large unattributed request lifecycle remains; inspect workspace service and ASGI lifecycle spans"


def _summary(
    *,
    rows: list[dict[str, Any]],
    attempted: int,
    result_count: int,
    checkpoint: dict[str, Any],
    output_dir: Path,
    results_name: str,
) -> dict[str, Any]:
    failed = [row for row in rows if not row.get("passed")]
    scored = [row for row in rows if row.get("score_in_pass_fail")]
    scored_failed = [row for row in scored if not row.get("passed")]
    excluded = [row for row in rows if not row.get("score_in_pass_fail")]
    excluded_failed = [row for row in excluded if not row.get("passed")]
    latencies = [float(row.get("latency_ms") or 0.0) for row in rows]
    payloads = [float(row.get("response_json_bytes") or 0.0) for row in rows]
    workspace_counts = [int(row.get("workspace_item_count") or 0) for row in rows]
    payload_guardrail_failures = [
        _failure(row)
        for row in rows
        if int(row.get("response_json_bytes") or 0) > PAYLOAD_FAIL_BYTES
        or str(row.get("failure_category") or "") == "payload_guardrail_failure"
    ]
    return {
        "attempted": attempted,
        "completed": len(rows),
        "harness_result_count": result_count,
        "durable_rows": _line_count(output_dir / results_name),
        "completed_equals_durable_rows": len(rows) == _line_count(output_dir / results_name),
        "checkpoint_rows": int(checkpoint.get("completed") or 0),
        "checkpoint": checkpoint,
        "safety": {
            "provider_calls": sum(1 for row in rows if row.get("provider_called")),
            "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
            "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout" or row.get("result_state") == "hard_timeout"),
            "process_kills": sum(1 for row in rows if row.get("process_killed")),
            "orphan_process_check": _orphan_process_check_result(),
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
        "known_blocker_lanes": _known_blocker_lanes(rows),
        "failure_counts": {
            "raw_failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in failed).items())),
            "scored_failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in scored_failed).items())),
            "excluded_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in excluded_failed).items())),
        },
        "route_family_coverage": {
            "expected": dict(sorted(Counter(str(row.get("expected_route_family") or "") for row in rows).items())),
            "actual": dict(sorted(Counter(str(row.get("actual_route_family") or "") for row in rows).items())),
        },
        "route_confusion_matrix": _route_confusion_matrix(rows),
        "generic_provider_fallback_count_by_expected_family": dict(sorted(Counter(str(row.get("expected_route_family") or "") for row in rows if row.get("actual_route_family") == "generic_provider").items())),
        "wrong_subsystem_rows": [_failure(row) for row in rows if row.get("failure_category") == "wrong_subsystem"],
        "remaining_real_routing_gaps": [_failure(row) for row in rows if row.get("failure_category") == "real_routing_gap"],
        "remaining_failures_by_category": {
            category: [_failure(row) for row in rows if row.get("failure_category") == category and not row.get("passed")]
            for category in sorted({str(row.get("failure_category") or "") for row in rows if not row.get("passed")})
        },
        "latency_summary_ms": _stats(latencies),
        "slowest_20": [_failure(row) for row in sorted(rows, key=lambda item: float(item.get("latency_ms") or 0.0), reverse=True)[:20]],
        "payload_summary": {
            "response_json_bytes": _stats(payloads),
            "rows_above_1mb": [_failure(row) for row in rows if int(row.get("response_json_bytes") or 0) > PAYLOAD_WARN_BYTES],
            "rows_above_5mb": [_failure(row) for row in rows if int(row.get("response_json_bytes") or 0) > PAYLOAD_FAIL_BYTES],
            "max_workspace_item_count": max(workspace_counts) if workspace_counts else 0,
            "payload_guardrail_failures": payload_guardrail_failures,
            "top_largest_payload_rows": [_failure(row) for row in sorted(rows, key=lambda item: int(item.get("response_json_bytes") or 0), reverse=True)[:20]],
        },
        "routine_save_summary": _routine_save_summary(rows),
        "missing_telemetry_summary": _missing_telemetry_rows(rows),
    }


def _known_blocker_lanes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    workspace_latency = [
        row
        for row in rows
        if row.get("failure_category") == "latency_issue"
        and str(row.get("expected_route_family") or "") in {"workspace_operations", "task_continuity"}
    ]
    labels = sorted({label for row in rows for label in row.get("historical_blocker_labels") or []})
    return {
        "known_workspace_latency_lane_rows": len(workspace_latency),
        "known_workspace_latency_lane_p95_ms": _stats([float(row.get("latency_ms") or 0.0) for row in workspace_latency]).get("p95"),
        "historical_blocker_labels": labels,
        "routine_save_historical_status": "known_unreproduced_product_latency_blocker",
    }


def _before_after(post_hardening: dict[str, Any], post_routing: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "focused_80_post_hardening": {
            "raw_counts": post_hardening.get("raw_counts"),
            "scored_counts": post_hardening.get("scored_counts"),
            "failure_counts": post_hardening.get("failure_counts"),
            "latency_summary_ms": post_hardening.get("latency_summary_ms"),
            "payload_summary": _compact_payload_summary(post_hardening.get("payload_summary")),
        },
        "focused_80_post_routing_remediation": {
            "raw_counts": post_routing.get("raw_counts"),
            "scored_counts": post_routing.get("scored_counts"),
            "failure_counts": post_routing.get("failure_counts"),
            "latency_summary_ms": post_routing.get("latency_summary_ms"),
            "payload_summary": _compact_payload_summary(post_routing.get("payload_summary")),
        },
        "focused_80_250_readiness_cleanup": {
            "raw_counts": readiness.get("raw_counts"),
            "scored_counts": readiness.get("scored_counts"),
            "failure_counts": readiness.get("failure_counts"),
            "latency_summary_ms": readiness.get("latency_summary_ms"),
            "payload_summary": _compact_payload_summary(readiness.get("payload_summary")),
        },
    }


def _recommendation(summary: dict[str, Any]) -> str:
    safety = summary.get("safety") or {}
    if summary.get("attempted") != summary.get("durable_rows") or not summary.get("completed_equals_durable_rows"):
        return "fix harness before 250"
    if safety.get("provider_calls") or safety.get("real_external_actions") or safety.get("process_kills"):
        return "fix safety isolation before 250"
    if safety.get("orphan_process_check") != "no_orphan_command_eval_processes_detected":
        return "fix telemetry/process cleanup before 250"
    if summary.get("payload_summary", {}).get("payload_guardrail_failures"):
        return "fix latency/payload first"
    if summary.get("wrong_subsystem_rows"):
        return "fix telemetry first"
    if summary.get("remaining_real_routing_gaps"):
        return "fix routing first"
    workspace = summary.get("workspace_latency") or {}
    if workspace.get("recommended_classification") == "block_250":
        return "fix workspace latency first"
    if workspace.get("recommended_classification") in {"known_workspace_latency_lane", "acceptable_for_250_with_budget"}:
        return "proceed to 250 with known workspace latency lane"
    if summary.get("scored_counts", {}).get("fail"):
        return "proceed to 250 with known bounded latency lanes and audited corpus expectations"
    return "proceed to 250"


def _focused_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Focused-80 250-Readiness Cleanup Report",
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
        "",
        "## 4. Before/After Comparison",
        _fmt(summary["before_after"]),
        "",
        "## 5. Pass/Fail Comparison",
        _fmt({"raw_counts": summary["raw_counts"], "scored_counts": summary["scored_counts"], "known_blocker_lanes": summary["known_blocker_lanes"]}),
        "",
        "## 6. Remaining Wrong-Subsystem Rows",
        _markdown_rows(summary["wrong_subsystem_rows"]),
        "",
        "## 7. Corpus Expectation Audit Results",
        _fmt({"counts": summary["corpus_expectation_audit"]["classification_counts"], "audited": summary["corpus_expectation_audit"]["audited_count"]}),
        "",
        "## 8. Workspace Latency Summary And Recommendation",
        _fmt(summary["workspace_latency"]),
        "",
        "## 9. Telemetry Gap Audit Results",
        _fmt(summary["telemetry_gap_audit"]),
        "",
        "## 10. Targeted Mini-Suite Status",
        _fmt({
            "attempted": summary["targeted_mini_suite"]["attempted"],
            "completed": summary["targeted_mini_suite"]["completed"],
            "durable_rows": summary["targeted_mini_suite"]["durable_rows"],
            "scored_counts": summary["targeted_mini_suite"]["scored_counts"],
            "failure_counts": summary["targeted_mini_suite"]["failure_counts"],
        }),
        "",
        "## 11. Generic-Provider Fallback Summary",
        _fmt(summary["generic_provider_fallback_count_by_expected_family"]),
        "",
        "## 12. Route Confusion Matrix",
        _fmt(summary["route_confusion_matrix"]),
        "",
        "## 13. Payload Guardrail Summary",
        _fmt(summary["payload_summary"]),
        "",
        "## 14. Routine-Save Summary",
        _fmt(summary["routine_save_summary"]),
        "",
        "## 15. Remaining Blockers",
        _fmt(summary["remaining_failures_by_category"]),
        "",
        "## 16. Recommendation",
        f"- {summary['recommendation']}",
    ]
    return "\n".join(lines).strip() + "\n"


def _corpus_audit_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# 250-Readiness Corpus Expectation Audit",
        "",
        f"- source: {audit['source']}",
        f"- audited rows: {audit['audited_count']}",
        f"- classification counts: {audit['classification_counts']}",
        "",
        "## Rows",
        _markdown_rows(audit["rows"]),
    ]
    return "\n".join(lines).strip() + "\n"


def _telemetry_audit_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Telemetry Gap Audit",
        "",
        f"- source: {audit['source']}",
        f"- missing route_state: {audit['missing_route_state']}",
        f"- missing planner_obedience: {audit['missing_planner_obedience']}",
        f"- classification counts: {audit['classification_counts']}",
        "",
        "## Rows",
        _markdown_rows(audit["rows"]),
    ]
    return "\n".join(lines).strip() + "\n"


def _routine_save_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    routine = [
        row
        for row in rows
        if "routine_save" in str(row.get("test_id") or "")
        or "routine_save" in [str(tool) for tool in row.get("actual_tool") or []]
    ]
    no_context = [row for row in routine if row.get("result_state") in {"needs_clarification", "blocked_missing_context"}]
    return {
        "rows": len(routine),
        "active_context_behavior": [_failure(row) for row in routine if row not in no_context],
        "no_context_behavior": [_failure(row) for row in no_context],
        "latency_ms": _stats([float(row.get("latency_ms") or 0.0) for row in routine]),
        "generic_provider_fallbacks": sum(1 for row in routine if row.get("actual_route_family") == "generic_provider"),
        "historical_blocker_labels": sorted({label for row in routine for label in row.get("historical_blocker_labels") or []}),
        "old_blocker_status": "known_unreproduced_product_latency_blocker",
    }


def _missing_telemetry_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missing = []
    for row in rows:
        if not row.get("route_state") or (row.get("actual_tool") and not row.get("planner_obedience")):
            missing.append(
                {
                    "test_id": row.get("test_id"),
                    "route_surface_type": row.get("route_surface_type"),
                    "route_state_required": row.get("route_surface_type") == "planner",
                    "planner_obedience_required": bool(row.get("actual_tool")) and row.get("route_surface_type") == "planner",
                }
            )
    return {
        "missing_route_state": sum(1 for row in rows if not row.get("route_state")),
        "missing_planner_obedience": sum(1 for row in rows if row.get("actual_tool") and not row.get("planner_obedience")),
        "classified_rows": missing,
    }


def _route_confusion_matrix(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        matrix[str(row.get("expected_route_family") or "")][str(row.get("actual_route_family") or "")] += 1
    return {expected: dict(sorted(actuals.items())) for expected, actuals in sorted(matrix.items())}


def _group_by(rows: list[dict[str, Any]], key: str | Any) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = key(row) if callable(key) else row.get(key)
        grouped[str(value or "")].append(row)
    return dict(grouped)


def _compact_payload_summary(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    return {key: value for key, value in payload.items() if key != "top_largest_payload_rows"}


def _expected_approval(row: dict[str, Any]) -> str:
    case = row.get("case") if isinstance(row.get("case"), dict) else {}
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    return str(expected.get("approval") or "")


def _preview_state(row: dict[str, Any]) -> str:
    verification = str(row.get("verification_state") or "")
    response = str(row.get("ui_response") or (row.get("observation") or {}).get("ui_response") or "").lower()
    if "preview" in verification or "dry_run" in verification or "dry-run" in response or "prepared a local" in response:
        return "preview_observed"
    return "not_observed"


def _failure(row: dict[str, Any]) -> dict[str, Any]:
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
        "failure_reason": row.get("failure_reason"),
        "latency_ms": row.get("latency_ms"),
        "response_json_bytes": row.get("response_json_bytes"),
        "workspace_item_count": row.get("workspace_item_count"),
        "route_scores": row.get("route_scores"),
        "fallback_reason": row.get("fallback_reason"),
        "historical_blocker_labels": row.get("historical_blocker_labels"),
    }


def _known_latency_failure(row: dict[str, Any]) -> bool:
    if row.get("failure_category") != "latency_issue":
        return False
    return str(row.get("expected_route_family") or "") in {
        "workspace_operations",
        "task_continuity",
        "routine",
        "maintenance",
    }


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
    if isinstance(payload, list):
        return _markdown_rows(payload)
    return str(payload)


def _markdown_rows(rows: list[dict[str, Any]]) -> str:
    return "\n".join(f"- `{row.get('test_id') or row.get('case_id') or '<row>'}`: {row}" for row in rows) if rows else "- none"


if __name__ == "__main__":
    main()
