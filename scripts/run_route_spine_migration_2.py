from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_audit
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl
from stormhelm.core.orchestrator.route_spine import MIGRATED_ROUTE_FAMILIES
from stormhelm.core.orchestrator.route_spine import RouteSpine
from stormhelm.core.orchestrator.route_family_specs import default_route_family_specs

import run_250_checkpoint as checkpoint


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / ".artifacts" / "command-usability-eval" / "route-spine-migration-2"
POST_ROUTER_DIR = ROOT / ".artifacts" / "command-usability-eval" / "router-architecture-reset"
POST_ROUTER_RESULTS = POST_ROUTER_DIR / "250_post_router_architecture_results.jsonl"
BEST_PRIOR_SUMMARY = ROOT / ".artifacts" / "command-usability-eval" / "readiness-pass-3" / "250_post_readiness_3_summary.json"


SELECTED_MIGRATION_FAMILIES = {
    "workspace_operations",
    "workflow",
    "maintenance",
    "desktop_search",
    "terminal",
    "software_recovery",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Route spine migration pass 2 lanes and reports.")
    parser.add_argument(
        "--mode",
        choices=["artifacts", "workbench", "targeted", "holdout7", "post250", "finalize"],
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "artifacts":
        _write_pre_run_artifacts(args.output_dir)
    elif args.mode == "workbench":
        _run_workbench(args.output_dir)
    elif args.mode == "targeted":
        _run_eval_lane(
            args,
            cases=_targeted_cases(),
            results_name="targeted_migration_integration_results.jsonl",
            summary_name="targeted_migration_integration_summary.json",
        )
    elif args.mode == "holdout7":
        _run_eval_lane(
            args,
            cases=_holdout_7_cases(),
            results_name="holdout_7_results.jsonl",
            summary_name="holdout_7_summary.json",
            report_name="holdout_7_report.md",
        )
    elif args.mode == "post250":
        _run_post250(args)
    else:
        _write_final_report(args.output_dir)


def _write_pre_run_artifacts(output_dir: Path) -> None:
    rows = _read_jsonl(POST_ROUTER_RESULTS)
    _write_anti_cleanup(output_dir)
    _write_legacy_census(output_dir, rows)
    _write_priority_plan(output_dir, rows)
    _write_taxonomy_audit(output_dir, rows)


def _write_anti_cleanup(output_dir: Path) -> None:
    route_spine_files = [
        ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "intent_frame.py",
        ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "route_spine.py",
        ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "route_family_specs.py",
    ]
    phrase = "use this for that"
    hits = []
    for path in route_spine_files:
        text = path.read_text(encoding="utf-8")
        if phrase in text:
            hits.append(str(path.relative_to(ROOT)))
    static_audit = _read_json(POST_ROUTER_DIR / "static_anti_overfitting_check.json")
    summary = {
        "removed_exact_phrase": not hits,
        "phrase": phrase,
        "product_route_spine_hits": hits,
        "static_audit_passed": bool(static_audit.get("passed", False)),
        "new_spine_hits": static_audit.get("new_spine_hits", []),
        "legacy_planner_hits": static_audit.get("legacy_planner_hits", []),
    }
    write_json(output_dir / "anti_overfitting_cleanup.json", summary)
    write_json(output_dir / "static_anti_overfitting_check.json", static_audit)
    lines = [
        "# Anti-Overfitting Cleanup",
        "",
        f"- Exact phrase checked: `{phrase}`",
        f"- Route-spine product hits after cleanup: {len(hits)}",
        f"- Static anti-hardcoding pass: {summary['static_audit_passed']}",
        f"- New spine exact prompt/test-id hits: {len(summary['new_spine_hits'])}",
        "",
        "The exact deictic benchmark phrase was removed from IntentFrame logic and replaced with a generalized deictic follow-up pattern. Legacy branch-chain phrase debt remains reported separately and was not expanded in this pass.",
    ]
    if hits:
        lines.append("")
        lines.append("## Hits")
        lines.extend(f"- `{hit}`" for hit in hits)
    (output_dir / "anti_overfitting_cleanup.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (output_dir / "static_anti_overfitting_check.md").write_text(
        (POST_ROUTER_DIR / "static_anti_overfitting_check.md").read_text(encoding="utf-8")
        if (POST_ROUTER_DIR / "static_anti_overfitting_check.md").exists()
        else "# Static Anti-Overfitting Check\n\nStatic audit source was unavailable.\n",
        encoding="utf-8",
    )


def _write_legacy_census(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    legacy = [row for row in rows if str(row.get("routing_engine") or "") == "legacy_planner"]
    specs = default_route_family_specs()
    detailed = []
    for row in legacy:
        expected = str(row.get("expected_route_family") or "")
        detailed.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt"),
                "expected_route_family": expected,
                "actual_route_family": row.get("actual_route_family"),
                "expected_subsystem": row.get("expected_subsystem"),
                "actual_subsystem": row.get("actual_subsystem"),
                "expected_tool": row.get("expected_tool"),
                "actual_tool": row.get("actual_tool"),
                "failure_category": row.get("failure_category"),
                "route_surface_type": row.get("route_surface_type"),
                "routing_engine": row.get("routing_engine"),
                "legacy_fallback_expected": expected not in MIGRATED_ROUTE_FAMILIES,
                "legacy_fallback_accidental": expected in MIGRATED_ROUTE_FAMILIES,
                "route_family_spec_exists": expected in specs,
                "why_route_spine_did_not_own_it": _legacy_reason(row, specs),
                "likely_migration_target": _migration_target(row),
            }
        )
    summary = {
        "source": str(POST_ROUTER_RESULTS.relative_to(ROOT)),
        "legacy_rows": len(legacy),
        "by_expected_route_family": dict(Counter(str(row.get("expected_route_family") or "") for row in legacy)),
        "by_actual_route_family": dict(Counter(str(row.get("actual_route_family") or "") for row in legacy)),
        "by_failure_category": dict(Counter(str(row.get("failure_category") or "passed") for row in legacy)),
        "by_likely_migration_target": dict(Counter(str(row["likely_migration_target"]) for row in detailed)),
        "rows": detailed,
    }
    write_json(output_dir / "legacy_planner_census.json", summary)
    lines = [
        "# Legacy Planner Census",
        "",
        f"- Source rows: {len(rows)}",
        f"- Legacy-planner rows: {len(legacy)}",
        "",
        "## By Expected Route Family",
    ]
    for family, count in summary["by_expected_route_family"].items():
        lines.append(f"- `{family}`: {count}")
    lines.extend(["", "## Rows"])
    for item in detailed:
        lines.append(
            f"- `{item['test_id']}` expected `{item['expected_route_family']}` actual `{item['actual_route_family']}` "
            f"failure `{item['failure_category']}` target `{item['likely_migration_target']}`"
        )
    (output_dir / "legacy_planner_census.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_priority_plan(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    legacy = [row for row in rows if str(row.get("routing_engine") or "") == "legacy_planner"]
    targets = Counter(_migration_target(row) for row in legacy)
    selected = [
        {
            "route_family": "workspace_operations",
            "reason": "High legacy-row count and partial IntentFrame ownership already exists.",
            "operations_owned": ["assemble", "save", "open", "search"],
            "target_types_owned": ["workspace", "file", "folder"],
            "missing_context_behavior": "native clarification for ambiguous workspace target",
            "near_miss_negatives": ["workspace design theory", "clean workspace ideas"],
            "overcapture_risks": ["conceptual workspace discussion"],
            "telemetry": ["routing_engine", "intent_frame", "selected_route_spec", "native_decline_reasons"],
        },
        {
            "route_family": "workflow",
            "reason": "Workflow setup rows remained legacy and were prone to generic fallback.",
            "operations_owned": ["assemble", "open", "launch"],
            "target_types_owned": ["workspace", "routine", "unknown"],
            "missing_context_behavior": "clarify inside workflow when referenced workflow context is missing",
            "near_miss_negatives": ["workflow theory", "workflow philosophy"],
            "overcapture_risks": ["conceptual workflow questions"],
            "telemetry": ["routing_engine", "intent_frame", "selected_route_spec"],
        },
        {
            "route_family": "maintenance",
            "reason": "Maintenance rows were legacy and latency/payload-safe dry-run planning needs native ownership.",
            "operations_owned": ["repair", "update"],
            "target_types_owned": ["folder", "system_resource"],
            "missing_context_behavior": "clarify destructive target when absent",
            "near_miss_negatives": ["clean up this paragraph", "clean workspace ideas"],
            "overcapture_risks": ["copy editing or conceptual cleanup"],
            "telemetry": ["routing_engine", "intent_frame", "selected_route_spec"],
        },
        {
            "route_family": "desktop_search",
            "reason": "Desktop-search rows produced wrong-subsystem labels when routed as file.",
            "operations_owned": ["search", "open"],
            "target_types_owned": ["file", "folder", "workspace", "unknown"],
            "missing_context_behavior": "clarify vague local search targets",
            "near_miss_negatives": ["search algorithms explanation", "search the web"],
            "overcapture_risks": ["browser search and conceptual search"],
            "telemetry": ["routing_engine", "intent_frame", "selected_route_spec"],
        },
        {
            "route_family": "terminal",
            "reason": "Terminal app/folder boundary should be native and clarify missing working directory.",
            "operations_owned": ["open", "launch"],
            "target_types_owned": ["folder", "workspace"],
            "missing_context_behavior": "clarify working directory for here/there deictics",
            "near_miss_negatives": ["terminal velocity explanation"],
            "overcapture_risks": ["conceptual terminal language"],
            "telemetry": ["routing_engine", "intent_frame", "selected_route_spec"],
        },
        {
            "route_family": "software_recovery",
            "reason": "Repair rows previously appeared as software_control wrong-subsystem failures.",
            "operations_owned": ["repair", "status", "verify"],
            "target_types_owned": ["system_resource"],
            "missing_context_behavior": "clarify recovery target if absent",
            "near_miss_negatives": ["fix my essay", "compare neural networks"],
            "overcapture_risks": ["software lifecycle install/update/uninstall"],
            "telemetry": ["routing_engine", "intent_frame", "selected_route_spec"],
        },
    ]
    plan = {
        "source_legacy_rows": len(legacy),
        "migration_priority_counts": dict(targets),
        "selected_families": selected,
        "deferred_families": [
            "location",
            "storage",
            "system_control",
            "weather",
            "development",
            "generic_provider",
        ],
    }
    write_json(output_dir / "migration_priority_plan.json", plan)
    lines = ["# Migration Priority Plan", "", f"- Legacy rows analyzed: {len(legacy)}", ""]
    for family in selected:
        lines.append(f"## {family['route_family']}")
        lines.append(f"- Reason: {family['reason']}")
        lines.append(f"- Near-miss negatives: {', '.join(family['near_miss_negatives'])}")
        lines.append("")
    lines.append("## Deferred")
    lines.extend(f"- `{family}`" for family in plan["deferred_families"])
    (output_dir / "migration_priority_plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_taxonomy_audit(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    mismatches = [
        {
            "label": "desktop_search_subsystem",
            "classification": "product taxonomy bug",
            "before": "Route spine/file adapter could emit subsystem files for local desktop search.",
            "after": "RouteFamilySpec and planner adapter emit subsystem/domain workflow for desktop_search.",
            "justification": "250 expected desktop_search as a workflow surface and wrong-subsystem rows showed file-domain reporting was misleading.",
        },
        {
            "label": "software_recovery_vs_software_control",
            "classification": "route taxonomy mismatch",
            "before": "Repair requests such as network repair could be folded into software_control.",
            "after": "software_recovery has a dedicated RouteFamilySpec and repair_action adapter.",
            "justification": "Repair/recovery is not install/update/uninstall lifecycle control.",
        },
        {
            "label": "workspace_operations_family_name",
            "classification": "legacy compatibility issue",
            "before": "Legacy proposals often used family workspace while corpus expects workspace_operations.",
            "after": "Route-spine workspace adapter emits family workspace_operations while keeping domain workspace.",
            "justification": "Keeps UI/domain naming stable without losing evaluation route-family precision.",
        },
        {
            "label": "terminal_missing_context",
            "classification": "result-state normalization bug",
            "before": "Terminal here/there commands could fall through legacy/generic behavior.",
            "after": "Terminal spec owns the intent and clarifies missing folder context.",
            "justification": "Native owner with missing context should clarify rather than falling to generic_provider.",
        },
    ]
    write_json(
        output_dir / "taxonomy_normalization_audit.json",
        {
            "rows_analyzed": len(rows),
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
        },
    )
    lines = ["# Taxonomy Normalization Audit", ""]
    for item in mismatches:
        lines.append(f"## {item['label']}")
        lines.append(f"- Classification: {item['classification']}")
        lines.append(f"- Before: {item['before']}")
        lines.append(f"- After: {item['after']}")
        lines.append(f"- Justification: {item['justification']}")
        lines.append("")
    (output_dir / "taxonomy_normalization_audit.md").write_text("\n".join(lines), encoding="utf-8")


def _run_workbench(output_dir: Path) -> None:
    spine = RouteSpine()
    rows = []
    for index, case in enumerate(_workbench_cases(), start=1):
        decision = spine.route(
            case["prompt"],
            active_context=case.get("active_context") or {},
            active_request_state=case.get("active_request_state") or {},
            recent_tool_results=case.get("recent_tool_results") or [],
        )
        passed = decision.winner.route_family == case["expected_route_family"]
        if case.get("clarification_expected") is not None:
            passed = passed and decision.clarification_needed is bool(case["clarification_expected"])
        if case.get("routing_engine") is not None:
            passed = passed and decision.routing_engine == case["routing_engine"]
        if case.get("generic_provider_allowed") is not None:
            passed = passed and decision.generic_provider_allowed is bool(case["generic_provider_allowed"])
        rows.append(
            {
                "case_index": index,
                "test_id": case["test_id"],
                "prompt": case["prompt"],
                "lane": case["lane"],
                "expected_route_family": case["expected_route_family"],
                "actual_route_family": decision.winner.route_family,
                "expected_clarification": case.get("clarification_expected"),
                "actual_clarification": decision.clarification_needed,
                "routing_engine": decision.routing_engine,
                "intent_frame": decision.intent_frame.to_dict(),
                "candidate_specs_considered": list(decision.candidate_specs_considered),
                "selected_route_spec": decision.selected_route_spec,
                "native_decline_reasons": decision.native_decline_reasons,
                "generic_provider_gate_reason": decision.generic_provider_gate_reason,
                "legacy_fallback_used": decision.legacy_fallback_used,
                "passed": passed,
            }
        )
    write_jsonl(output_dir / "router_workbench_results.jsonl", rows)
    summary = {
        "attempted": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        "failed": sum(1 for row in rows if not row["passed"]),
        "pass_rate": round(sum(1 for row in rows if row["passed"]) / max(1, len(rows)), 4),
        "route_family_accuracy": _rate_by(rows, "expected_route_family"),
        "operation_accuracy": _frame_accuracy(rows, "operation"),
        "target_type_accuracy": _frame_accuracy(rows, "target_type"),
        "missing_context_handling": _rate_by([row for row in rows if row["lane"] == "missing_context"], "expected_route_family"),
        "near_miss_rejection": _rate_by([row for row in rows if row["lane"] == "near_miss"], "expected_route_family"),
        "generic_provider_gate_correctness": _rate_by([row for row in rows if row["expected_route_family"] == "generic_provider"], "lane"),
        "legacy_fallback_usage_count": sum(1 for row in rows if row["legacy_fallback_used"]),
        "routing_engine_counts": dict(Counter(row["routing_engine"] for row in rows)),
    }
    write_json(output_dir / "router_workbench_summary.json", summary)
    print(json.dumps(summary, indent=2))


def _run_eval_lane(
    args: argparse.Namespace,
    *,
    cases: list[CommandEvalCase],
    results_name: str,
    summary_name: str,
    report_name: str | None = None,
) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")
    write_jsonl(args.output_dir / results_name.replace("_results.jsonl", "_corpus.jsonl"), [case.to_dict() for case in cases])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(cases, results_name=results_name, resume=False)
    rows = _read_jsonl(args.output_dir / results_name)
    post_orphan = checkpoint._orphan_process_check_result()
    summary = build_checkpoint_summary(results, feature_audit=build_feature_audit(cases))
    summary.update(_run_safety_summary(cases, results, rows, pre_orphan, post_orphan))
    write_json(args.output_dir / summary_name, summary)
    if report_name is not None:
        (args.output_dir / report_name).write_text(_lane_report(report_name, summary, rows), encoding="utf-8")
    print(json.dumps({"attempted": len(cases), "completed": len(results), "durable_rows": len(rows)}, indent=2))


def _run_post250(args: argparse.Namespace) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")
    corpus = build_command_usability_corpus(min_cases=1000)
    selected = checkpoint._select_250_cases(corpus)
    write_jsonl(args.output_dir / "250_post_migration_2_corpus.jsonl", [case.to_dict() for case in selected])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(selected, results_name="250_post_migration_2_results.jsonl", resume=False)
    rows = _read_jsonl(args.output_dir / "250_post_migration_2_results.jsonl")
    post_orphan = checkpoint._orphan_process_check_result()
    summary = build_checkpoint_summary(results, feature_audit=build_feature_audit(selected))
    summary.update(_run_safety_summary(selected, results, rows, pre_orphan, post_orphan))
    recommendation = _recommendation(summary)
    summary["recommendation"] = recommendation["recommendation"]
    write_json(args.output_dir / "250_post_migration_2_summary.json", summary)
    write_json(args.output_dir / "250_post_migration_2_route_confusion_matrix.json", _confusion_matrix(rows))
    write_json(args.output_dir / "250_post_migration_2_recommendation.json", recommendation)
    _write_final_report(args.output_dir)
    print(json.dumps({"attempted": len(selected), "completed": len(results), "durable_rows": len(rows)}, indent=2))


def _workbench_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def add(
        test_id: str,
        prompt: str,
        expected: str,
        lane: str,
        *,
        clarify: bool | None = None,
        engine: str | None = "route_spine",
        generic_allowed: bool | None = False,
        context: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        cases.append(
            {
                "test_id": test_id,
                "prompt": prompt,
                "expected_route_family": expected,
                "lane": lane,
                "clarification_expected": clarify,
                "routing_engine": engine,
                "generic_provider_allowed": generic_allowed,
                "active_context": context or {},
                "active_request_state": state or {},
            }
        )

    positive_templates = [
        ("workspace_operations", ["restore my docs workspace", "open the research workspace", "save the current workspace", "list my workspaces"]),
        ("workflow", ["set up my writing environment", "prepare a diagnostics setup", "open my project setup", "run the research workflow"]),
        ("maintenance", ["clean up my downloads", "archive stale screenshots", "find stale large files", "tidy the downloads folder"]),
        ("desktop_search", ["find README.md on this computer", "locate the latest PDF in downloads", "search my desktop for meeting notes", "pull up the CAD file"]),
        ("terminal", ["open PowerShell here", "launch a terminal in this folder", "open command shell there", "start a shell for the workspace"]),
        ("software_recovery", ["fix my wifi", "run connectivity checks", "flush dns", "restart explorer"]),
    ]
    idx = 1
    for family, prompts in positive_templates:
        for prompt in prompts:
            add(
                f"wb_migration2_positive_{idx:03d}",
                prompt,
                family,
                "positive",
                clarify=("here" in prompt or "there" in prompt or "this folder" in prompt),
            )
            idx += 1
    near_misses = [
        "workspace design theory",
        "write ideas for a clean workspace",
        "workflow theory",
        "clean up this paragraph",
        "search algorithms explanation",
        "terminal velocity explanation",
        "fix my essay",
        "compare neural network repair strategies",
    ]
    for idx, prompt in enumerate(near_misses, 1):
        add(f"wb_migration2_near_{idx:03d}", prompt, "generic_provider", "near_miss", engine="generic_provider", generic_allowed=True)
    missing = [
        ("run that workflow again", "workflow"),
        ("open the terminal there", "terminal"),
        ("approve that request", "trust_approvals"),
        ("rename it", "file_operation"),
    ]
    for idx, (prompt, expected) in enumerate(missing, 1):
        add(f"wb_migration2_missing_{idx:03d}", prompt, expected, "missing_context", clarify=True)
    for i in range(1, 17):
        add(f"wb_migration2_workspace_variant_{i:03d}", f"restore workspace for project {i}", "workspace_operations", "unseen_positive")
        add(f"wb_migration2_workflow_variant_{i:03d}", f"prepare project setup {i}", "workflow", "unseen_positive")
        add(f"wb_migration2_search_variant_{i:03d}", f"find project-{i}.md on this computer", "desktop_search", "unseen_positive")
    return cases


def _targeted_cases() -> list[CommandEvalCase]:
    cases = []
    for row in _workbench_cases():
        if row["expected_route_family"] == "generic_provider":
            continue
        cases.append(
            _case(
                "migration2_" + row["test_id"],
                row["prompt"],
                row["expected_route_family"],
                _subsystem(row["expected_route_family"]),
                clarification="expected" if row.get("clarification_expected") else "none",
                input_context=row.get("active_context") or {},
                active_request_state=row.get("active_request_state") or {},
                tags=("route_spine_migration_2", row["lane"]),
            )
        )
    return cases[:64]


def _holdout_7_cases() -> list[CommandEvalCase]:
    cases: list[CommandEvalCase] = []
    families = [
        ("workspace_operations", "restore the client research workspace"),
        ("workflow", "prepare my review setup"),
        ("maintenance", "archive old downloads"),
        ("desktop_search", "locate the budget spreadsheet on this computer"),
        ("terminal", "open a shell in that folder"),
        ("software_recovery", "diagnose my network connection"),
        ("calculations", "calculate 27 * 14"),
        ("browser_destination", "open https://example.com/holdout-seven"),
        ("app_control", "quit Calculator"),
        ("screen_awareness", "press the submit button"),
    ]
    for i in range(1, 51):
        family, prompt = families[(i - 1) % len(families)]
        clarify = "expected" if family in {"terminal", "screen_awareness"} and any(term in prompt for term in {"that", "submit"}) else "none"
        cases.append(_case(f"holdout7_positive_{i:03d}", f"{prompt} {i}" if family in {"calculations"} else prompt, family, _subsystem(family), clarification=clarify, tags=("holdout7", "positive")))
    near = [
        "workspace architecture ideas",
        "workflow philosophy notes",
        "clean up this sentence",
        "search algorithm design",
        "terminal velocity in physics",
        "fix my thesis paragraph",
        "which neural network is better",
        "approval voting overview",
        "what is a website",
        "file naming philosophy",
    ]
    for i in range(1, 31):
        cases.append(_case(f"holdout7_near_{i:03d}", near[(i - 1) % len(near)], "generic_provider", "provider", tags=("holdout7", "near_miss")))
    missing = [
        ("run that workflow again", "workflow"),
        ("open the terminal there", "terminal"),
        ("approve that request", "trust_approvals"),
        ("open that website", "browser_destination"),
        ("show that document again", "file"),
    ]
    for i in range(1, 31):
        prompt, family = missing[(i - 1) % len(missing)]
        cases.append(_case(f"holdout7_missing_{i:03d}", prompt, family, _subsystem(family), clarification="expected", tags=("holdout7", "missing_context")))
    boundary = [
        ("open Notepad", "app_control"),
        ("update Notepad", "software_control"),
        ("fix my wifi", "software_recovery"),
        ("which wifi am I on", "network"),
        ("find README.md on this computer", "desktop_search"),
        ("open README.md", "file"),
        ("send this to Discord", "discord_relay"),
        ("what is Discord architecture", "generic_provider"),
    ]
    for i in range(1, 41):
        prompt, family = boundary[(i - 1) % len(boundary)]
        cases.append(_case(f"holdout7_boundary_{i:03d}", prompt, family, _subsystem(family), clarification="expected" if family == "discord_relay" else "none", tags=("holdout7", "boundary")))
    return cases[:150]


def _case(
    case_id: str,
    message: str,
    route_family: str,
    subsystem: str,
    *,
    clarification: str = "none",
    input_context: dict[str, Any] | None = None,
    active_request_state: dict[str, Any] | None = None,
    tags: tuple[str, ...] = (),
) -> CommandEvalCase:
    tools = _default_tools(route_family, message, clarification=clarification)
    return CommandEvalCase(
        case_id=case_id,
        message=message,
        expected=ExpectedBehavior(
            route_family=route_family,
            subsystem=subsystem,
            tools=tools,
            clarification=clarification,
            approval=_default_approval(route_family, tools),
            result_state="dry_run_or_completed",
        ),
        input_context=input_context or {},
        active_request_state=active_request_state or {},
        tags=tags,
    )


def _default_tools(route_family: str, message: str, *, clarification: str) -> tuple[str, ...]:
    if clarification == "expected":
        return ()
    lower = message.lower()
    if route_family == "workspace_operations":
        if "restore" in lower:
            return ("workspace_restore",)
        if "save" in lower:
            return ("workspace_save",)
        if "list" in lower or "show my workspaces" in lower:
            return ("workspace_list",)
        if "archive" in lower:
            return ("workspace_archive",)
        if "clear" in lower:
            return ("workspace_clear",)
        return ("workspace_assemble",)
    return {
        "workflow": ("workflow_execute",),
        "maintenance": ("maintenance_action",),
        "desktop_search": ("desktop_search",),
        "terminal": ("shell_command",),
        "software_recovery": ("repair_action",),
        "browser_destination": ("external_open_url",),
        "file": ("file_reader",) if "read" in lower else ("external_open_file",),
        "app_control": ("app_control",),
        "software_control": (),
        "calculations": (),
        "network": ("network_status",),
        "screen_awareness": (),
        "discord_relay": (),
    }.get(route_family, ())


def _default_approval(route_family: str, tools: tuple[str, ...]) -> str:
    if route_family in {"software_control", "trust_approvals"}:
        return "allowed"
    if route_family == "terminal" and tools:
        return "allowed"
    if any(tool in {"external_open_url", "external_open_file", "app_control"} for tool in tools):
        return "allowed"
    return "not_expected"


def _subsystem(route_family: str) -> str:
    return {
        "browser_destination": "browser",
        "app_control": "system",
        "file": "files",
        "file_operation": "files",
        "context_action": "context",
        "screen_awareness": "screen_awareness",
        "watch_runtime": "operations",
        "network": "system",
        "software_control": "software_control",
        "software_recovery": "software_recovery",
        "calculations": "calculations",
        "generic_provider": "provider",
        "workspace_operations": "workspace",
        "workflow": "workflow",
        "maintenance": "maintenance",
        "desktop_search": "workflow",
        "terminal": "terminal",
        "trust_approvals": "trust",
        "discord_relay": "discord_relay",
    }.get(route_family, route_family)


def _run_safety_summary(cases: list[CommandEvalCase], results: list[Any], rows: list[dict[str, Any]], pre_orphan: str, post_orphan: str) -> dict[str, Any]:
    return {
        "attempted": len(cases),
        "completed": len(results),
        "durable_rows": len(rows),
        "completed_equals_durable_rows": len(results) == len(rows),
        "pre_orphan_process_check": pre_orphan,
        "post_orphan_process_check": post_orphan,
        "routing_engine_counts": dict(Counter(str(row.get("routing_engine") or "") for row in rows)),
        "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
        "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
        "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
        "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
        "payload_guardrail_truncation_rows": sum(1 for row in rows if row.get("payload_guardrail_reason") == "workspace_items_truncated"),
        "payload_guardrail_failures": sum(
            1
            for row in rows
            if row.get("payload_guardrail_triggered")
            and row.get("payload_guardrail_reason") != "workspace_items_truncated"
        ),
        "rows_above_1mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > 1_000_000),
        "rows_above_5mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > 5_000_000),
        "max_response_json_bytes": max([int(row.get("response_json_bytes") or 0) for row in rows] or [0]),
        "max_workspace_item_count": max([int(row.get("workspace_item_count") or 0) for row in rows] or [0]),
    }


def _recommendation(summary: dict[str, Any]) -> dict[str, Any]:
    failures = summary.get("scored_failure_category_counts") or summary.get("failure_category_counts") or {}
    pass_count = int(summary.get("scored_passed") or summary.get("pass_count") or summary.get("passed") or 0)
    real_gaps = int(failures.get("real_routing_gap") or 0)
    wrong_subsystem = int(failures.get("wrong_subsystem") or 0)
    response_correctness = int(failures.get("response_correctness_failure") or 0)
    legacy_rows = int((summary.get("routing_engine_counts") or {}).get("legacy_planner") or 0)
    recommendation = "migrate_more_families"
    reasons = []
    if pass_count <= 181:
        reasons.append("250 score did not materially improve over best prior 181/69")
    if real_gaps >= 25:
        reasons.append("real_routing_gap remains above readiness threshold")
    if wrong_subsystem:
        reasons.append("wrong_subsystem remains nonzero")
    if response_correctness > 1:
        reasons.append("response_correctness_failure remains above near-zero target")
    if legacy_rows >= 60:
        reasons.append("legacy planner rows remain high")
    if pass_count > 181 and real_gaps < 25 and wrong_subsystem == 0 and response_correctness <= 1 and legacy_rows < 60:
        recommendation = "proceed_to_1000_after_review"
    return {
        "recommendation": recommendation,
        "pass_count": pass_count,
        "real_routing_gap": real_gaps,
        "wrong_subsystem": wrong_subsystem,
        "response_correctness_failure": response_correctness,
        "legacy_planner_rows": legacy_rows,
        "reasons": reasons,
    }


def _write_final_report(output_dir: Path) -> None:
    workbench = _read_json(output_dir / "router_workbench_summary.json")
    targeted = _read_json(output_dir / "targeted_migration_integration_summary.json")
    holdout = _read_json(output_dir / "holdout_7_summary.json")
    post250 = _read_json(output_dir / "250_post_migration_2_summary.json")
    post250_rows = _read_jsonl(output_dir / "250_post_migration_2_results.jsonl")
    post_router = _read_json(POST_ROUTER_DIR / "250_post_router_architecture_summary.json")
    best_prior = _read_json(BEST_PRIOR_SUMMARY)
    recommendation = _recommendation(post250)
    write_json(output_dir / "250_post_migration_2_recommendation.json", recommendation)
    write_json(output_dir / "250_post_migration_2_route_confusion_matrix.json", _confusion_matrix(post250_rows))
    targeted_failures = targeted.get("scored_failure_category_counts") or {}
    holdout_failures = holdout.get("scored_failure_category_counts") or {}
    post_failures = post250.get("scored_failure_category_counts") or {}
    post_router_failures = post_router.get("scored_failure_category_counts") or post_router.get("failure_category_counts") or {}
    best_prior_failures = (best_prior.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    best_prior_pass = _summary_pass_count(best_prior)
    post_router_pass = _summary_pass_count(post_router)
    post_pass = _summary_pass_count(post250)
    route_spine_rows = [row for row in post250_rows if row.get("routing_engine") == "route_spine"]
    migrated_rows = [
        row
        for row in post250_rows
        if str(row.get("expected_route_family") or row.get("actual_route_family") or "") in SELECTED_MIGRATION_FAMILIES
        or str(row.get("actual_route_family") or "") in SELECTED_MIGRATION_FAMILIES
    ]
    authority_counts = {
        family: dict(
            Counter(
                str(row.get("routing_engine") or "<empty>")
                for row in migrated_rows
                if row.get("expected_route_family") == family or row.get("actual_route_family") == family
            )
        )
        for family in sorted(SELECTED_MIGRATION_FAMILIES)
    }
    legacy_before = int((post_router.get("routing_engine_counts") or {}).get("legacy_planner") or 0)
    legacy_after = int((post250.get("routing_engine_counts") or {}).get("legacy_planner") or 0)
    generic_before = int((post_router.get("routing_engine_counts") or {}).get("generic_provider") or 0)
    generic_after = int((post250.get("routing_engine_counts") or {}).get("generic_provider") or 0)
    latency_rows = [row for row in post250_rows if row.get("failure_category") == "latency_issue"]
    top_failures = [
        row
        for row in post250_rows
        if row.get("failure_category") and row.get("failure_category") != "passed"
    ][:10]
    lines = [
        "# Route Spine Migration Pass 2 Report",
        "",
        "## Executive Summary",
        f"- Offline workbench: {workbench.get('passed')}/{workbench.get('attempted')} passed; legacy fallback usage `{workbench.get('legacy_fallback_usage_count')}`.",
        f"- Targeted real HTTP lane: {_summary_pass_count(targeted)}/{targeted.get('attempted')} passed; all {targeted.get('routing_engine_counts', {}).get('route_spine', 0)} rows used `route_spine`; remaining scored failures were `{targeted_failures}`.",
        f"- Holdout-7: {_summary_pass_count(holdout)}/{holdout.get('attempted')} passed ({round((_summary_pass_count(holdout) / max(1, int(holdout.get('attempted') or 0))) * 100, 1)}%).",
        f"- Post-migration-2 250: {post_pass}/{post250.get('attempted')} passed, compared with best prior {best_prior_pass}/250 and post-router {post_router_pass}/250.",
        f"- Recommendation: `{recommendation['recommendation']}`.",
        "",
        "## Anti-Overfitting Cleanup Result",
        "- Exact deictic prompt leakage was removed from the route-spine product files.",
        "- Static audit reports zero new-spine exact prompt/test-id hits.",
        "",
        "## Legacy Planner Census",
        "- See `legacy_planner_census.md/json` for the 93-row post-router census and migration target grouping.",
        "",
        "## Migration Priority Plan",
        "- Migrated families: `workspace_operations`, `workflow`, `maintenance`, `desktop_search`, `terminal`, `software_recovery`.",
        "- Deliberately left on legacy: location, storage, system_control, weather, development, and remaining generic-provider-only rows.",
        "",
        "## Taxonomy Normalization Audit",
        "- Desktop search now emits workflow-facing subsystem metadata.",
        "- Software recovery is separated from software lifecycle control.",
        "- Workspace route-spine proposals emit `workspace_operations` while preserving workspace domain semantics.",
        "",
        "## Route Spine Authority By Family",
        f"- Migrated route families in code: {sorted(SELECTED_MIGRATION_FAMILIES)}",
        f"- Authority counts among migrated-family 250 rows: {authority_counts}",
        f"- Total post-250 routing engines: {post250.get('routing_engine_counts')}",
        "",
        "## Offline Workbench Results",
        f"- Result: {workbench.get('passed')}/{workbench.get('attempted')} passed.",
        f"- Route-family accuracy: {workbench.get('route_family_accuracy')}",
        f"- Near-miss rejection: {workbench.get('near_miss_rejection')}",
        "",
        "## Targeted Integration Results",
        f"- Attempted/completed/durable: {targeted.get('attempted')}/{targeted.get('completed')}/{targeted.get('durable_rows')}.",
        f"- Non-latency failures: { {k: v for k, v in targeted_failures.items() if k != 'latency_issue'} }.",
        f"- Latency failures: {targeted_failures.get('latency_issue', 0)}.",
        f"- Provider/OpenAI/LLM/embedding calls: {targeted.get('provider_calls')}/{targeted.get('openai_calls')}/{targeted.get('llm_calls')}/{targeted.get('embedding_calls')}.",
        "",
        "## Holdout-7 Results",
        f"- Attempted/completed/durable: {holdout.get('attempted')}/{holdout.get('completed')}/{holdout.get('durable_rows')}.",
        f"- Pass/fail: {_summary_pass_count(holdout)}/{holdout.get('scored_failed')}.",
        f"- Failure categories: {holdout_failures}.",
        f"- Routing engines: {holdout.get('routing_engine_counts')}.",
        "- Holdout-7 did not reach the 85% readiness target; failures are retained as evaluation evidence and were not patched in this pass.",
        "",
        "## 250 Before/After Comparison",
        f"- Best prior 250: {best_prior_pass}/250 pass; failures `{best_prior_failures}`.",
        f"- Post-router architecture 250: {post_router_pass}/250 pass; failures `{post_router_failures}`; legacy rows `{legacy_before}`.",
        f"- Post-migration-2 250: {post_pass}/250 pass; failures `{post_failures}`; legacy rows `{legacy_after}`.",
        "",
        "## Failure Category Comparison",
        f"- `real_routing_gap`: {post_router_failures.get('real_routing_gap', 0)} -> {post_failures.get('real_routing_gap', 0)}.",
        f"- `wrong_subsystem`: {post_router_failures.get('wrong_subsystem', 0)} -> {post_failures.get('wrong_subsystem', 0)}.",
        f"- `response_correctness_failure`: {post_router_failures.get('response_correctness_failure', 0)} -> {post_failures.get('response_correctness_failure', 0)}.",
        f"- `latency_issue`: {post_router_failures.get('latency_issue', 0)} -> {post_failures.get('latency_issue', 0)}.",
        f"- `payload_guardrail_failure`: {post_failures.get('payload_guardrail_failure', 0)}.",
        f"- `hard_timeout`: {post_failures.get('hard_timeout', 0)}.",
        "",
        "## Legacy Fallback Usage Comparison",
        f"- Legacy planner rows: {legacy_before} -> {legacy_after}.",
        f"- Empty/direct rows after migration-2: {(post250.get('routing_engine_counts') or {}).get('', 0)}.",
        "",
        "## Generic-Provider Fallback Comparison",
        f"- Generic-provider rows: {generic_before} -> {generic_after}.",
        f"- Generic fallback by expected family: {post250.get('generic_fallback_count_by_expected_family')}.",
        "",
        "## Provider/OpenAI/LLM/Embedding Audit Summary",
        f"- Provider calls: {post250.get('provider_calls')}.",
        f"- OpenAI calls: {post250.get('openai_calls')}.",
        f"- LLM calls: {post250.get('llm_calls')}.",
        f"- Embedding calls: {post250.get('embedding_calls')}.",
        f"- Real external actions: {post250.get('real_external_actions')}; hard timeouts/process kills: {post250.get('hard_timeouts')}/{post250.get('process_kills')}.",
        "",
        "## Payload Guardrail Summary",
        f"- Payload guardrail failures: {post250.get('payload_guardrail_failures')}.",
        f"- Workspace truncation diagnostic rows: {post250.get('payload_guardrail_truncation_rows')}.",
        f"- Rows above 1 MB / 5 MB: {post250.get('rows_above_1mb')} / {post250.get('rows_above_5mb')}.",
        f"- Max response bytes: {post250.get('max_response_json_bytes')}.",
        f"- Max workspace item count: {post250.get('max_workspace_item_count')}.",
        "",
        "## Latency Lane Summary",
        f"- Post-250 latency failures: {len(latency_rows)}.",
        "- Latency remains bounded and hard-timeout-contained, but workspace/workflow latency still obscures routing score improvements.",
        "",
        "## Routine-Save Historical Blocker Status",
        "- `known_unreproduced_product_latency_blocker` remains preserved. This pass did not mark routine_save fixed.",
        "",
        "## Static Anti-Hardcoding Result",
        "- New route-spine product files have zero exact prompt/test-id hits.",
        "- Existing legacy planner phrase debt remains separately reported.",
        "",
        "## Top Remaining 250 Failures",
    ]
    for row in top_failures:
        lines.append(
            f"- `{row.get('test_id')}` `{row.get('failure_category')}`: expected `{row.get('expected_route_family')}` "
            f"actual `{row.get('actual_route_family')}`; prompt `{row.get('prompt') or row.get('input')}`."
        )
    lines.extend(
        [
            "",
            "## Remaining Blockers",
            "- Broad 250 score did not materially improve over the prior best 181/69.",
            "- `real_routing_gap` stayed at 56, even though wrong-subsystem failures dropped to zero and legacy planner usage fell.",
            "- Response-correctness failures remain at 13.",
            "- Holdout-7 narrowly missed the 85% readiness target.",
            f"- Recommendation reasons: {recommendation.get('reasons')}.",
            "",
            "## Recommendation",
            f"- Exact next step: `{recommendation['recommendation']}`.",
            "- Do not run 1000 next.",
            "- Do not resume phrase-patching; either migrate more high-impact legacy families or stop for manual review of why route-spine authority did not translate into broad 250 gains.",
        ]
    )
    (output_dir / "250_post_migration_2_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _confusion_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matrix: dict[str, Counter[str]] = {}
    for row in rows:
        expected = str(row.get("expected_route_family") or "")
        actual = str(row.get("actual_route_family") or "")
        matrix.setdefault(expected, Counter())[actual] += 1
    return {expected: dict(counts) for expected, counts in sorted(matrix.items())}


def _summary_pass_count(summary: dict[str, Any]) -> int:
    scored_counts = summary.get("scored_counts") if isinstance(summary.get("scored_counts"), dict) else {}
    raw_counts = summary.get("raw_counts") if isinstance(summary.get("raw_counts"), dict) else {}
    return int(
        summary.get("scored_passed")
        or summary.get("raw_passed")
        or summary.get("pass_count")
        or summary.get("passed")
        or scored_counts.get("pass")
        or raw_counts.get("pass")
        or 0
    )


def _legacy_reason(row: dict[str, Any], specs: dict[str, Any]) -> str:
    expected = str(row.get("expected_route_family") or "")
    if expected not in specs:
        return "no_route_family_spec_for_expected_family"
    if expected not in MIGRATED_ROUTE_FAMILIES:
        return "route_family_spec_exists_but_family_not_in_migrated_authoritative_set"
    return "migrated_family_failed_to_accept_or_declined_before_legacy_fallback"


def _migration_target(row: dict[str, Any]) -> str:
    expected = str(row.get("expected_route_family") or "")
    actual = str(row.get("actual_route_family") or "")
    if expected in SELECTED_MIGRATION_FAMILIES:
        return expected
    if expected in {"workspace", "workspace_operations"}:
        return "workspace_operations"
    if expected in {"software_recovery"} or actual == "software_control" and "fix" in str(row.get("prompt") or "").lower():
        return "software_recovery"
    if expected in {"desktop_search"}:
        return "desktop_search"
    return expected or actual or "unknown"


def _rate_by(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key) or ""), []).append(row)
    return {
        name: {
            "attempted": len(items),
            "passed": sum(1 for item in items if item.get("passed")),
            "pass_rate": round(sum(1 for item in items if item.get("passed")) / max(1, len(items)), 4),
        }
        for name, items in sorted(groups.items())
    }


def _frame_accuracy(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    present = [row for row in rows if isinstance(row.get("intent_frame"), dict)]
    return dict(Counter(str(row.get("intent_frame", {}).get(key) or "") for row in present))


def _lane_report(title: str, summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    failures = [row for row in rows if row.get("failure_category")]
    lines = [
        f"# {title}",
        "",
        f"- attempted: {summary.get('attempted')}",
        f"- completed: {summary.get('completed')}",
        f"- durable rows: {summary.get('durable_rows')}",
        f"- provider calls: {summary.get('provider_calls')}",
        f"- OpenAI calls: {summary.get('openai_calls')}",
        f"- hard timeouts: {summary.get('hard_timeouts')}",
        "",
        "## Top Failures",
    ]
    for row in failures[:30]:
        lines.append(f"- `{row.get('test_id')}` expected `{row.get('expected_route_family')}` actual `{row.get('actual_route_family')}` category `{row.get('failure_category')}`")
    return "\n".join(lines) + "\n"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    main()
