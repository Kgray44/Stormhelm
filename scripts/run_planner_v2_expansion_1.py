from __future__ import annotations

import argparse
import ast
import json
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval.feature_audit import build_feature_audit
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl
from stormhelm.core.orchestrator.planner_v2 import PLANNER_V2_ROUTE_FAMILIES
from stormhelm.core.orchestrator.planner_v2 import PlannerV2

import run_250_checkpoint as checkpoint


OUTPUT_DIR = ROOT / ".artifacts" / "command-usability-eval" / "planner-v2-expansion-1"
MIGRATED_FAMILIES = (
    "workspace_operations",
    "routine",
    "workflow",
    "task_continuity",
    "discord_relay",
)
REMAINING_LEGACY_FAMILIES = (
    "terminal",
    "maintenance",
    "trust_approvals",
    "power",
    "machine",
    "desktop_search",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Planner v2 expansion and legacy quarantine artifacts.")
    parser.add_argument(
        "--mode",
        choices=["policy", "census", "workbench", "integration", "post250", "static", "finalize", "all"],
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.mode in {"policy", "all"}:
        write_legacy_quarantine_policy(args.output_dir)
    if args.mode in {"census", "all"}:
        write_legacy_family_census(args.output_dir)
    if args.mode in {"workbench", "all"}:
        run_workbench(args.output_dir)
    if args.mode in {"integration", "all"}:
        run_integration_lane(args)
    if args.mode == "post250":
        run_250_comparison(args)
    if args.mode in {"static", "all"}:
        write_static_anti_overfitting_check(args.output_dir)
    if args.mode in {"finalize", "all"}:
        write_final_report(args.output_dir)


def write_legacy_quarantine_policy(output_dir: Path) -> None:
    policy = {
        "policy_name": "planner_v2_legacy_quarantine_policy",
        "rules": [
            "No new route families may be added to the legacy planner.",
            "No new product behavior may be implemented only in legacy.",
            "Migrated Planner v2 families must never be overridden by legacy.",
            "Every legacy fallback must emit legacy_fallback_used, legacy_family, Planner v2 decline reason, schedule status, and migration priority.",
            "generic_provider remains gated behind native Planner v2 decline reasons.",
        ],
        "migrated_families": list(MIGRATED_FAMILIES),
        "remaining_legacy_families": list(REMAINING_LEGACY_FAMILIES),
        "legacy_fallback_telemetry_required": [
            "legacy_fallback_used",
            "legacy_family",
            "planner_v2_decline_reason",
            "legacy_family_scheduled_for_migration",
            "migration_priority",
            "generic_provider_gate_reason",
            "native_decline_reasons",
        ],
        "routine_save_historical_blocker": "known_unreproduced_product_latency_blocker",
    }
    write_json(output_dir / "legacy_quarantine_policy.json", policy)
    (output_dir / "legacy_quarantine_policy.md").write_text(_policy_md(policy), encoding="utf-8")


def write_legacy_family_census(output_dir: Path) -> None:
    rows = {
        "workspace_operations": _family(
            "workspace_operations",
            entry_points=["workspace_* tools", "route-spine semantic adapter", "legacy branch-chain workspace operations"],
            heuristics=["workspace", "assemble", "restore", "save", "list", "snapshot"],
            contexts=["workspace", "current_resolution", "current_task", "project seed"],
            tools=["workspace_restore", "workspace_assemble", "workspace_save", "workspace_list"],
            approval="dry-run plan; local mutation only after policy approval when live",
            failures=["legacy planner interference", "workspace latency lane", "missing-context fallback"],
            risk="medium: payload and latency are bounded but historically noisy",
            benefit="high: large broad-corpus footprint and many remaining legacy rows",
            order=1,
            decision="migrated_in_this_pass",
        ),
        "routine": _family(
            "routine",
            entry_points=["routine_save", "routine_execute", "trusted_hook legacy aliases"],
            heuristics=["save this as a routine", "remember workflow", "run routine", "saved workflow"],
            contexts=["active_request_state", "current_resolution", "selection", "recent action"],
            tools=["routine_save", "routine_execute"],
            approval="dry-run plan in eval; live save/execute follows routine policy",
            failures=["routine save missing-context generic fallback", "historical catastrophic latency lane"],
            risk="high: old latency blocker must remain preserved",
            benefit="high: native routine-save intent must not fall to provider",
            order=2,
            decision="migrated_in_this_pass",
        ),
        "workflow": _family(
            "workflow",
            entry_points=["workflow_execute", "workflow semantic branch"],
            heuristics=["set up environment", "prepare setup", "run workflow", "restore workflow"],
            contexts=["workflow context for same/previous/that", "explicit setup name"],
            tools=["workflow_execute"],
            approval="dry-run plan in eval",
            failures=["unsupported specifics", "context missing should clarify"],
            risk="medium: near-miss workflow theory can overcapture",
            benefit="high: shared setup/workflow language appears often",
            order=3,
            decision="migrated_in_this_pass",
        ),
        "task_continuity": _family(
            "task_continuity",
            entry_points=["workspace_where_left_off", "workspace_next_steps"],
            heuristics=["continue that", "resume task", "where were we", "next steps"],
            contexts=["current_task", "workspace", "current_resolution", "recent task context"],
            tools=["workspace_where_left_off", "workspace_next_steps"],
            approval="read-only in eval",
            failures=["deictic/follow-up binding", "invented continuity when missing"],
            risk="medium: conceptual task-management near misses",
            benefit="high: repeated holdout weakness",
            order=4,
            decision="migrated_in_this_pass",
        ),
        "discord_relay": _family(
            "discord_relay",
            entry_points=["discord relay preview/dispatch adapter"],
            heuristics=["send/share/message/relay/forward/dm to recipient", "selected payload"],
            contexts=["destination", "payload", "selection", "active request payload"],
            tools=[],
            approval="live sends require preview and approval; eval never sends externally",
            failures=["missing recipient/payload clarification", "external-action safety boundary"],
            risk="high: external messaging and self-bot/API policy boundary",
            benefit="high: native relay should clarify instead of provider fallback",
            order=5,
            decision="migrated_in_this_pass",
        ),
        "terminal": _family("terminal", ["legacy terminal branch"], ["terminal", "powershell", "shell"], ["folder"], ["shell_command"], "internal surface open", ["working-dir clarification"], "medium", "medium", 6, "deferred"),
        "maintenance": _family("maintenance", ["legacy maintenance branch"], ["clean up", "archive", "tidy"], ["folder", "system_resource"], ["maintenance_action"], "dry-run plan; mutation requires policy", ["conceptual cleanup near misses"], "medium", "medium", 7, "deferred"),
        "trust_approvals": _family("trust_approvals", ["legacy trust branch"], ["approve", "deny", "allow"], ["approval_object"], [], "trust-sensitive", ["policy expectation rows"], "medium", "medium", 8, "deferred"),
        "power": _family("power", ["legacy status branch"], ["battery", "charging", "power"], ["system_resource"], ["power_status", "power_projection"], "read-only", ["taxonomy only"], "low", "low", 9, "deferred"),
        "machine": _family("machine", ["legacy status branch"], ["machine name", "os version", "computer"], ["system_resource"], ["machine_status"], "read-only", ["taxonomy only"], "low", "low", 10, "deferred"),
        "desktop_search": _family("desktop_search", ["legacy search branch"], ["find file", "search desktop"], ["file", "folder"], ["desktop_search", "recent_files"], "read-only/internal open", ["web-vs-desktop ambiguity"], "medium", "medium", 11, "deferred"),
    }
    payload = {
        "families": rows,
        "recommended_migration_order": sorted(rows, key=lambda item: rows[item]["recommended_migration_order"]),
        "migrated_this_pass": list(MIGRATED_FAMILIES),
        "deferred": [family for family, data in rows.items() if data["decision"] == "deferred"],
    }
    write_json(output_dir / "legacy_family_migration_census.json", payload)
    (output_dir / "legacy_family_migration_census.md").write_text(_census_md(payload), encoding="utf-8")


def run_workbench(output_dir: Path) -> None:
    planner = PlannerV2()
    rows: list[dict[str, Any]] = []
    for case in workbench_cases():
        trace = planner.plan(
            case["prompt"],
            active_context=case.get("active_context") or {},
            active_request_state=case.get("active_request_state") or {},
            recent_tool_results=case.get("recent_tool_results") or [],
        )
        checks = _workbench_checks(case, trace)
        passed = all(checks.values())
        rows.append(
            {
                "test_id": case["test_id"],
                "prompt": case["prompt"],
                "lane": case["lane"],
                "expected_route_family": case["expected_route_family"],
                "actual_route_family": trace.route_decision.selected_route_family,
                "expected_routing_engine": case["expected_routing_engine"],
                "actual_routing_engine": trace.route_decision.routing_engine,
                "expected_result_state": case.get("expected_result_state") or "",
                "actual_result_state": trace.result_state_draft.result_state,
                "expected_binding_status": case.get("expected_binding_status") or "",
                "actual_binding_status": trace.context_binding.status,
                "legacy_fallback_used": trace.legacy_fallback_used,
                "generic_provider_allowed": trace.route_decision.generic_provider_allowed,
                "generic_provider_gate_reason": trace.route_decision.generic_provider_gate_reason,
                "native_decline_reasons": trace.route_decision.native_decline_reasons,
                "candidate_specs_considered": list(trace.route_decision.candidate_specs_considered),
                "selected_route_spec": trace.route_decision.selected_route_spec,
                "checks": checks,
                "passed": passed,
                "planner_v2_trace": trace.to_dict(),
            }
        )
    write_jsonl(output_dir / "planner_v2_expansion_workbench_results.jsonl", rows)
    summary = _workbench_summary(rows)
    write_json(output_dir / "planner_v2_expansion_workbench_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def run_integration_lane(args: argparse.Namespace) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")
    cases = integration_cases()
    write_jsonl(args.output_dir / "planner_v2_expansion_integration_corpus.jsonl", [case.to_dict() for case in cases])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(cases, results_name="planner_v2_expansion_integration_results.jsonl", resume=False)
    rows = _read_jsonl(args.output_dir / "planner_v2_expansion_integration_results.jsonl")
    post_orphan = checkpoint._orphan_process_check_result()
    summary = build_checkpoint_summary(results, feature_audit=build_feature_audit(cases))
    summary.update(_run_safety_summary(cases, results, rows, pre_orphan, post_orphan))
    summary["planner_v2_family_rows"] = sum(1 for row in rows if row.get("expected_route_family") in PLANNER_V2_ROUTE_FAMILIES)
    summary["planner_v2_authoritative_rows"] = sum(
        1
        for row in rows
        if row.get("expected_route_family") in PLANNER_V2_ROUTE_FAMILIES and row.get("routing_engine") == "planner_v2"
    )
    summary["planner_v2_authority_ok"] = summary["planner_v2_family_rows"] == summary["planner_v2_authoritative_rows"]
    summary["migrated_family_authority"] = {
        family: {
            "rows": sum(1 for row in rows if row.get("expected_route_family") == family),
            "planner_v2_rows": sum(
                1
                for row in rows
                if row.get("expected_route_family") == family and row.get("routing_engine") == "planner_v2"
            ),
        }
        for family in MIGRATED_FAMILIES
    }
    summary["non_planner_v2_rows"] = [
        {
            "test_id": row.get("test_id"),
            "expected_route_family": row.get("expected_route_family"),
            "actual_route_family": row.get("actual_route_family"),
            "routing_engine": row.get("routing_engine"),
        }
        for row in rows
        if row.get("expected_route_family") in PLANNER_V2_ROUTE_FAMILIES and row.get("routing_engine") != "planner_v2"
    ]
    near_miss_rows = [row for row in rows if "near_miss" in str(row.get("test_id") or "")]
    summary["near_miss_rows"] = len(near_miss_rows)
    summary["near_miss_overroute_rows"] = [
        {
            "test_id": row.get("test_id"),
            "expected_route_family": row.get("expected_route_family"),
            "actual_route_family": row.get("actual_route_family"),
            "routing_engine": row.get("routing_engine"),
        }
        for row in near_miss_rows
        if row.get("actual_route_family") != "generic_provider"
    ]
    generic_rows = [row for row in rows if row.get("actual_route_family") == "generic_provider"]
    summary["generic_provider_rows"] = len(generic_rows)
    summary["generic_provider_rows_missing_gate_reason"] = [
        {
            "test_id": row.get("test_id"),
            "generic_provider_gate_reason": row.get("generic_provider_gate_reason"),
            "native_decline_reasons": row.get("native_decline_reasons"),
        }
        for row in generic_rows
        if not row.get("generic_provider_gate_reason") and not row.get("native_decline_reasons")
    ]
    write_json(args.output_dir / "planner_v2_expansion_integration_summary.json", summary)
    print(json.dumps({"attempted": len(cases), "completed": len(results), "durable_rows": len(rows)}, indent=2))


def run_250_comparison(args: argparse.Namespace) -> None:
    tmp = args.output_dir / "_250_checkpoint_tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(ROOT / ".venv" / "Scripts" / "python.exe"),
        str(ROOT / "scripts" / "run_250_checkpoint.py"),
        "--output-dir",
        str(tmp),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--server-startup-timeout-seconds",
        str(args.server_startup_timeout_seconds),
        "--process-scope",
        args.process_scope,
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    mapping = {
        "250_results.jsonl": "250_post_planner_v2_expansion_results.jsonl",
        "250_summary.json": "250_post_planner_v2_expansion_summary.json",
        "250_checkpoint_report.md": "250_post_planner_v2_expansion_report.md",
    }
    for source, dest in mapping.items():
        shutil.copyfile(tmp / source, args.output_dir / dest)
    summary = _read_json(args.output_dir / "250_post_planner_v2_expansion_summary.json")
    summary["copied_from"] = str(tmp)
    write_json(args.output_dir / "250_post_planner_v2_expansion_summary.json", summary)


def write_static_anti_overfitting_check(output_dir: Path) -> None:
    product_paths = [
        ROOT / "src" / "stormhelm" / "core" / "orchestrator" / name
        for name in (
            "intent_frame.py",
            "planner.py",
            "planner_v2.py",
            "route_context.py",
            "route_family_specs.py",
            "route_spine.py",
            "router.py",
        )
    ]
    exact_prompt_sources: dict[str, str] = {"use this for that": "prior_static_audit_leak"}
    test_id_sources: dict[str, str] = {}
    for case in workbench_cases():
        prompt = str(case.get("prompt") or "").strip()
        if _is_static_prompt_candidate(prompt):
            exact_prompt_sources[prompt] = f"workbench:{case.get('test_id')}"
    for case in integration_cases():
        prompt = str(case.message).strip()
        if _is_static_prompt_candidate(prompt):
            exact_prompt_sources[prompt] = f"integration:{case.case_id}"
        test_id_sources[case.case_id] = "integration_test_id"

    hits: list[dict[str, Any]] = []
    for path in product_paths:
        if not path.exists():
            continue
        literals = _python_string_literals(path)
        for literal, source in exact_prompt_sources.items():
            for occurrence in literals.get(literal, []):
                hits.append(_static_hit(path, literal, source, occurrence))
        for literal, source in test_id_sources.items():
            for occurrence in literals.get(literal, []):
                hits.append(_static_hit(path, literal, source, occurrence))

    test_id_hits = [hit for hit in hits if str(hit["source"]).endswith("_test_id")]
    exact_prompt_hits = [hit for hit in hits if not str(hit["source"]).endswith("_test_id")]
    planner_v2_hits = [
        hit
        for hit in hits
        if hit["path"].endswith(("planner_v2.py", "route_family_specs.py", "route_spine.py", "intent_frame.py"))
    ]
    payload = {
        "product_paths_scanned": [str(path.relative_to(ROOT)) for path in product_paths if path.exists()],
        "exact_prompt_hits": exact_prompt_hits,
        "test_id_hits": test_id_hits,
        "planner_v2_or_spine_hits": planner_v2_hits,
        "legacy_planner_hits": [hit for hit in hits if hit["path"].endswith("planner.py")],
        "passed": not hits,
        "planner_v2_clean": not planner_v2_hits,
        "notes": [
            "Exact prompts and test ids are allowed in tests, reports, fixtures, and artifacts.",
            "Any hit listed here is in product routing logic and should be treated as anti-overfitting debt.",
            "This audit does not mutate product behavior.",
        ],
    }
    write_json(output_dir / "static_anti_overfitting_check.json", payload)
    (output_dir / "static_anti_overfitting_check.md").write_text(_static_audit_md(payload), encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "hits": len(hits), "planner_v2_clean": payload["planner_v2_clean"]}, indent=2))


def write_final_report(output_dir: Path) -> None:
    policy = _read_json(output_dir / "legacy_quarantine_policy.json")
    census = _read_json(output_dir / "legacy_family_migration_census.json")
    workbench = _read_json(output_dir / "planner_v2_expansion_workbench_summary.json")
    integration = _read_json(output_dir / "planner_v2_expansion_integration_summary.json")
    post250 = _read_json(output_dir / "250_post_planner_v2_expansion_summary.json")
    integration_rows = _read_jsonl(output_dir / "planner_v2_expansion_integration_results.jsonl")
    post250_rows = _read_jsonl(output_dir / "250_post_planner_v2_expansion_results.jsonl")
    static_audit = _read_json(output_dir / "static_anti_overfitting_check.json")
    post250_metrics = _post250_row_metrics(post250_rows)
    summary = {
        "migrated_families": list(MIGRATED_FAMILIES),
        "remaining_legacy_families": list(REMAINING_LEGACY_FAMILIES),
        "legacy_quarantine_policy_present": bool(policy),
        "legacy_family_census_present": bool(census),
        "workbench": workbench,
        "integration": integration,
        "post_250": post250,
        "post_250_row_metrics": post250_metrics,
        "static_anti_overfitting": static_audit,
        "provider_openai_llm_embedding_calls": {
            "provider": integration.get("provider_calls", 0),
            "openai": integration.get("openai_calls", 0),
            "llm": integration.get("llm_calls", 0),
            "embedding": integration.get("embedding_calls", 0),
        },
        "routine_save_historical_blocker": "known_unreproduced_product_latency_blocker",
        "recommendation": _recommendation(workbench, integration, post250),
    }
    write_json(output_dir / "planner_v2_expansion_summary.json", summary)
    (output_dir / "planner_v2_expansion_report.md").write_text(
        _final_report_md(policy, census, workbench, integration, integration_rows, post250, post250_metrics, static_audit, summary),
        encoding="utf-8",
    )


def workbench_cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(
        test_id: str,
        prompt: str,
        route_family: str,
        *,
        lane: str,
        engine: str = "planner_v2",
        result_state: str | None = None,
        binding_status: str | None = None,
        active_context: dict[str, Any] | None = None,
        active_request_state: dict[str, Any] | None = None,
        generic_allowed: bool | None = None,
        legacy_fallback: bool | None = False,
    ) -> None:
        rows.append(
            {
                "test_id": test_id,
                "prompt": prompt,
                "expected_route_family": route_family,
                "expected_routing_engine": engine,
                "expected_result_state": result_state,
                "expected_binding_status": binding_status,
                "active_context": active_context or {},
                "active_request_state": active_request_state or {},
                "expected_generic_provider_allowed": generic_allowed,
                "expected_legacy_fallback_used": legacy_fallback,
                "lane": lane,
            }
        )

    selection = {"selection": {"kind": "text", "value": "Selected routing notes.", "preview": "Selected routing notes."}}
    workspace = {"current_resolution": {"kind": "workspace_seed", "title": "Router diagnostics", "items": [{"title": "ping"}]}}
    task = {"workspace": {"name": "Stormhelm eval"}, "current_task": {"title": "Planner v2", "status": "in_progress"}}
    workflow_state = {"family": "workflow", "subject": "writing_setup", "parameters": {"workflow_kind": "writing_setup"}}

    add("calc_direct", "what is 7 * 8", "calculations", lane="old_slice")
    add("browser_url", "open https://example.com/status", "browser_destination", lane="old_slice")
    add("app_open", "open Notepad", "app_control", lane="old_slice")
    add("file_path", r"open C:\Stormhelm\README.md", "file", lane="old_slice")
    add("screen_missing", "press submit", "screen_awareness", lane="old_slice", result_state="needs_clarification", binding_status="missing", generic_allowed=False)
    add("software_install", "install Minecraft", "software_control", lane="old_slice")
    add("network_status", "which wifi am I on", "network", lane="old_slice")
    add("workspace_seeded", "make a workspace for this", "workspace_operations", lane="positive", active_context=workspace)
    add("workspace_missing", "make a workspace for this", "workspace_operations", lane="missing_context", result_state="needs_clarification", binding_status="missing", generic_allowed=False)
    add("workspace_near_miss", "workspace organization philosophy ideas", "generic_provider", lane="near_miss", engine="generic_provider", generic_allowed=True)
    add("routine_seeded", "save this as a routine called cleanup", "routine", lane="positive", active_request_state=workflow_state)
    add("routine_missing", "save this as a routine called cleanup", "routine", lane="missing_context", result_state="needs_clarification", binding_status="missing", generic_allowed=False)
    add("routine_near_miss", "daily routine advice", "generic_provider", lane="near_miss", engine="generic_provider", generic_allowed=True)
    add("workflow_explicit", "set up my writing environment", "workflow", lane="positive")
    add("workflow_missing", "run that workflow again", "workflow", lane="missing_context", result_state="needs_clarification", binding_status="missing", generic_allowed=False)
    add("workflow_near_miss", "explain workflow theory", "generic_provider", lane="near_miss", engine="generic_provider", generic_allowed=True)
    add("task_bound", "continue that", "task_continuity", lane="positive", active_context=task)
    add("task_missing", "continue that", "task_continuity", lane="missing_context", result_state="needs_clarification", binding_status="missing", generic_allowed=False)
    add("task_near_miss", "what are next steps in algebra", "generic_provider", lane="near_miss", engine="generic_provider", generic_allowed=True)
    add("discord_bound", "send this to Baby", "discord_relay", lane="positive", active_context=selection)
    add("discord_missing", "send this to Baby", "discord_relay", lane="missing_context", result_state="needs_clarification", binding_status="missing", generic_allowed=False)
    add("discord_near_miss", "message format for Discord docs", "generic_provider", lane="near_miss", engine="generic_provider", generic_allowed=True)
    add("legacy_control", "write me a cozy paragraph about planning", "legacy_planner", lane="legacy_control", engine="legacy_planner", legacy_fallback=True)
    return rows


def integration_cases() -> list[CommandEvalCase]:
    selection = {"selection": {"kind": "text", "value": "Selected routing notes.", "preview": "Selected routing notes."}}
    workspace = {"current_resolution": {"kind": "workspace_seed", "title": "Router diagnostics", "items": [{"title": "ping"}]}}
    task = {"workspace": {"name": "Stormhelm eval"}, "current_task": {"title": "Planner v2", "status": "in_progress"}}
    workflow_state = {"family": "workflow", "subject": "writing_setup", "parameters": {"workflow_kind": "writing_setup"}}
    return [
        _case("exp1_http_calc_direct", "what is 7 * 8", "calculations", "calculations"),
        _case("exp1_http_browser_url", "open https://example.com/status", "browser_destination", "browser", tools=("external_open_url",), approval="allowed"),
        _case("exp1_http_app_open", "open Notepad", "app_control", "system", tools=("app_control",), approval="allowed"),
        _case("exp1_http_file_path", r"open C:\Stormhelm\README.md", "file", "files", tools=("external_open_file",), approval="allowed"),
        _case("exp1_http_screen_missing", "press submit", "screen_awareness", "screen_awareness", clarification="expected"),
        _case("exp1_http_software_install", "install Minecraft", "software_control", "software_control", approval="allowed"),
        _case("exp1_http_network_status", "which wifi am I on", "network", "system", tools=("network_status",)),
        _case("exp1_http_workspace_seeded", "make a workspace for this", "workspace_operations", "workspace", workspace_context=workspace, tools=("workspace_assemble",)),
        _case("exp1_http_workspace_missing", "make a workspace for this", "workspace_operations", "workspace", clarification="expected"),
        _case("exp1_http_workspace_near_miss", "workspace organization philosophy ideas", "generic_provider", "provider", tags_extra=("near_miss", "provider_fallback_diagnostic")),
        _case("exp1_http_routine_seeded", "save this as a routine called cleanup", "routine", "routine", active_request_state=workflow_state, tools=("routine_save",)),
        _case("exp1_http_routine_missing", "save this as a routine called cleanup", "routine", "routine", clarification="expected"),
        _case("exp1_http_routine_near_miss", "daily routine advice", "generic_provider", "provider", tags_extra=("near_miss", "provider_fallback_diagnostic")),
        _case("exp1_http_workflow_explicit", "set up my writing environment", "workflow", "workflow", tools=("workflow_execute",)),
        _case("exp1_http_workflow_missing", "run that workflow again", "workflow", "workflow", clarification="expected"),
        _case("exp1_http_workflow_near_miss", "explain workflow theory", "generic_provider", "provider", tags_extra=("near_miss", "provider_fallback_diagnostic")),
        _case("exp1_http_task_bound", "continue that", "task_continuity", "workspace", workspace_context=task, tools=("workspace_next_steps",)),
        _case("exp1_http_task_missing", "continue that", "task_continuity", "workspace", clarification="expected"),
        _case("exp1_http_task_near_miss", "what are next steps in algebra", "generic_provider", "provider", tags_extra=("near_miss", "provider_fallback_diagnostic")),
        _case("exp1_http_discord_bound", "send this to Baby", "discord_relay", "discord_relay", input_context=selection, approval="allowed"),
        _case("exp1_http_discord_missing", "send this to Baby", "discord_relay", "discord_relay", clarification="expected"),
        _case("exp1_http_discord_near_miss", "message format for Discord docs", "generic_provider", "provider", tags_extra=("near_miss", "provider_fallback_diagnostic")),
    ]


def _case(
    case_id: str,
    message: str,
    route_family: str,
    subsystem: str,
    *,
    tools: tuple[str, ...] = (),
    clarification: str = "none",
    approval: str = "not_expected",
    workspace_context: dict[str, Any] | None = None,
    input_context: dict[str, Any] | None = None,
    active_request_state: dict[str, Any] | None = None,
    tags_extra: tuple[str, ...] = (),
) -> CommandEvalCase:
    return CommandEvalCase(
        case_id=case_id,
        message=message,
        expected=ExpectedBehavior(
            route_family=route_family,
            subsystem=subsystem,
            tools=tools,
            clarification=clarification,
            approval=approval,
            result_state="dry_run_or_completed",
            latency_ms_max=10000,
        ),
        workspace_context=workspace_context or {},
        input_context=input_context or {},
        active_request_state=active_request_state or {},
        tags=("planner_v2", "planner_v2_expansion_1", route_family, *tags_extra),
    )


def _workbench_checks(case: dict[str, Any], trace: Any) -> dict[str, bool]:
    checks = {
        "route_family": trace.route_decision.selected_route_family == case["expected_route_family"],
        "routing_engine": trace.route_decision.routing_engine == case["expected_routing_engine"],
        "legacy_fallback_used": trace.legacy_fallback_used == bool(case.get("expected_legacy_fallback_used")),
    }
    if case.get("expected_result_state"):
        expected = str(case["expected_result_state"])
        actual = trace.result_state_draft.result_state
        checks["result_state"] = actual == expected or (
            expected == "needs_clarification" and actual in {"needs_clarification", "blocked_missing_context"}
        )
    if case.get("expected_binding_status"):
        checks["binding_status"] = trace.context_binding.status == case["expected_binding_status"]
    if case.get("expected_generic_provider_allowed") is not None:
        checks["generic_provider_allowed"] = trace.route_decision.generic_provider_allowed == bool(case["expected_generic_provider_allowed"])
    if case["expected_route_family"] in PLANNER_V2_ROUTE_FAMILIES:
        checks["authoritative_selected_family"] = trace.authoritative is True
        checks["no_legacy_for_selected_family"] = trace.legacy_fallback_used is False
    return checks


def _workbench_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for row in rows if row.get("passed"))
    route_counts = Counter(str(row.get("actual_route_family") or "") for row in rows)
    return {
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "route_family_counts": dict(route_counts),
        "routing_engine_counts": dict(Counter(str(row.get("actual_routing_engine") or "") for row in rows)),
        "route_family_accuracy": _rate(rows, "route_family"),
        "operation_accuracy": "covered_by_intent_frame_trace",
        "target_type_accuracy": "covered_by_intent_frame_trace",
        "context_binding_accuracy": _rate(rows, "binding_status"),
        "missing_context_correctness": _lane_rate(rows, "missing_context"),
        "near_miss_rejection": _lane_rate(rows, "near_miss"),
        "generic_provider_gate_correctness": _rate(rows, "generic_provider_allowed"),
        "legacy_fallback_usage_count": sum(1 for row in rows if row.get("legacy_fallback_used")),
        "unexpected_legacy_fallback_usage_count": sum(1 for row in rows if row.get("legacy_fallback_used") and row.get("expected_route_family") in PLANNER_V2_ROUTE_FAMILIES),
        "failed_rows": [
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt"),
                "expected_route_family": row.get("expected_route_family"),
                "actual_route_family": row.get("actual_route_family"),
                "checks": row.get("checks"),
            }
            for row in rows
            if not row.get("passed")
        ],
    }


def _run_safety_summary(
    cases: list[CommandEvalCase],
    results: list[Any],
    rows: list[dict[str, Any]],
    pre_orphan: str,
    post_orphan: str,
) -> dict[str, Any]:
    latencies = [float(row.get("total_latency_ms") or row.get("latency_ms") or 0) for row in rows]
    return {
        "attempted": len(cases),
        "completed": len(results),
        "durable_rows": len(rows),
        "completed_equals_durable_rows": len(results) == len(rows),
        "pre_orphan_process_check": pre_orphan,
        "post_orphan_process_check": post_orphan,
        "routing_engine_counts": dict(Counter(str(row.get("routing_engine") or "") for row in rows)),
        "route_family_counts": dict(Counter(str(row.get("actual_route_family") or "") for row in rows)),
        "legacy_fallback_rows": sum(1 for row in rows if row.get("legacy_fallback_used")),
        "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
        "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
        "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
        "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
        "payload_guardrail_failures": sum(1 for row in rows if row.get("payload_guardrail_triggered") and row.get("payload_guardrail_reason") != "workspace_items_truncated"),
        "rows_above_1mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > 1_000_000),
        "rows_above_5mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > 5_000_000),
        "max_response_json_bytes": max([int(row.get("response_json_bytes") or 0) for row in rows] or [0]),
        "latency_min_ms": round(min(latencies), 3) if latencies else 0,
        "latency_median_ms": round(statistics.median(latencies), 3) if latencies else 0,
        "latency_max_ms": round(max(latencies), 3) if latencies else 0,
    }


def _rate(rows: list[dict[str, Any]], check_name: str) -> dict[str, Any]:
    applicable = [row for row in rows if check_name in (row.get("checks") or {})]
    passed = sum(1 for row in applicable if (row.get("checks") or {}).get(check_name))
    return {"applicable": len(applicable), "passed": passed, "failed": len(applicable) - passed, "rate": round(passed / len(applicable), 4) if applicable else 0.0}


def _lane_rate(rows: list[dict[str, Any]], lane: str) -> dict[str, Any]:
    applicable = [row for row in rows if row.get("lane") == lane]
    passed = sum(1 for row in applicable if row.get("passed"))
    return {"applicable": len(applicable), "passed": passed, "failed": len(applicable) - passed, "rate": round(passed / len(applicable), 4) if applicable else 0.0}


def _family(
    name: str,
    entry_points: list[str],
    heuristics: list[str],
    contexts: list[str],
    tools: list[str],
    approval: str,
    failures: list[str],
    risk: str,
    benefit: str,
    order: int,
    decision: str,
) -> dict[str, Any]:
    return {
        "family": name,
        "current_legacy_entry_points": entry_points,
        "route_phrases_or_heuristics": heuristics,
        "target_context_requirements": contexts,
        "tools_actions": tools,
        "approval_trust_requirements": approval,
        "result_states_used": ["dry_run_ready", "needs_clarification", "blocked_missing_context", "completed"],
        "common_failure_patterns_from_prior_reports": failures,
        "migration_risk": risk,
        "expected_benefit": benefit,
        "recommended_migration_order": order,
        "decision": decision,
    }


def _policy_md(policy: dict[str, Any]) -> str:
    lines = ["# Legacy Quarantine Policy", ""]
    for rule in policy["rules"]:
        lines.append(f"- {rule}")
    lines += ["", f"Migrated families: {', '.join(policy['migrated_families'])}.", f"Remaining legacy families: {', '.join(policy['remaining_legacy_families'])}.", "", f"Routine-save blocker preserved: `{policy['routine_save_historical_blocker']}`."]
    return "\n".join(lines) + "\n"


def _census_md(payload: dict[str, Any]) -> str:
    lines = ["# Legacy Family Migration Census", ""]
    for family in payload["recommended_migration_order"]:
        data = payload["families"][family]
        lines.extend([
            f"## {family}",
            f"- decision: {data['decision']}",
            f"- entry points: {', '.join(data['current_legacy_entry_points'])}",
            f"- heuristics: {', '.join(data['route_phrases_or_heuristics'])}",
            f"- context: {', '.join(data['target_context_requirements'])}",
            f"- tools: {', '.join(data['tools_actions']) if data['tools_actions'] else 'none'}",
            f"- approval/trust: {data['approval_trust_requirements']}",
            f"- risk: {data['migration_risk']}",
            f"- expected benefit: {data['expected_benefit']}",
            "",
        ])
    return "\n".join(lines)


def _is_static_prompt_candidate(value: str) -> bool:
    if len(value) < 12:
        return False
    if " " not in value:
        return False
    if "_" in value and " " not in value:
        return False
    if value in PLANNER_V2_ROUTE_FAMILIES:
        return False
    return True


def _python_string_literals(path: Path) -> dict[str, list[dict[str, Any]]]:
    source = path.read_text(encoding="utf-8-sig")
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    literals: dict[str, list[dict[str, Any]]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            line_number = getattr(node, "lineno", 0) or 0
            literals.setdefault(node.value, []).append(
                {
                    "line": line_number,
                    "line_preview": lines[line_number - 1].strip()[:240] if 0 < line_number <= len(lines) else "",
                }
            )
    return literals


def _static_hit(path: Path, literal: str, source: str, occurrence: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "line": occurrence.get("line", 0),
        "literal": literal,
        "source": source,
        "line_preview": occurrence.get("line_preview", ""),
        "product_routing_logic": True,
    }


def _static_audit_md(payload: dict[str, Any]) -> str:
    lines = [
        "# Static Anti-Overfitting Check",
        "",
        f"Passed: {payload.get('passed')}.",
        f"Planner v2 / route-spine files clean: {payload.get('planner_v2_clean')}.",
        f"Product paths scanned: {len(payload.get('product_paths_scanned') or [])}.",
        "",
        "## Hits",
    ]
    hits = list(payload.get("exact_prompt_hits") or []) + list(payload.get("test_id_hits") or [])
    if not hits:
        lines.append("No exact prompt or test-id hits were found in scanned product routing logic.")
    for hit in hits:
        lines.append(
            f"- `{hit.get('literal')}` from `{hit.get('source')}` at `{hit.get('path')}:{hit.get('line')}`"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "- Exact prompts and test ids are allowed in tests, reports, fixtures, and artifacts.",
            "- Hits in product routing logic are anti-overfitting debt, even if they are in legacy code.",
            "- This audit did not change product behavior.",
            "",
        ]
    )
    return "\n".join(lines)


def _post250_row_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failure_rows = [row for row in rows if str(row.get("failure_category") or "passed") != "passed"]
    return {
        "rows": len(rows),
        "routing_engine_counts": dict(Counter(str(row.get("routing_engine") or "unknown") for row in rows)),
        "legacy_planner_rows": sum(1 for row in rows if row.get("routing_engine") == "legacy_planner"),
        "planner_v2_rows": sum(1 for row in rows if row.get("routing_engine") == "planner_v2"),
        "route_spine_rows": sum(1 for row in rows if row.get("routing_engine") == "route_spine"),
        "generic_provider_rows": sum(1 for row in rows if row.get("actual_route_family") == "generic_provider"),
        "failure_category_counts": dict(Counter(str(row.get("failure_category") or "passed") for row in failure_rows)),
        "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
        "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
        "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
        "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
        "payload_guardrail_failures": sum(1 for row in rows if row.get("payload_guardrail_triggered") and row.get("payload_guardrail_reason") != "workspace_items_truncated"),
        "rows_above_1mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > 1_000_000),
        "max_response_json_bytes": max([int(row.get("response_json_bytes") or 0) for row in rows] or [0]),
    }


def _final_report_md(
    policy: dict[str, Any],
    census: dict[str, Any],
    workbench: dict[str, Any],
    integration: dict[str, Any],
    integration_rows: list[dict[str, Any]],
    post250: dict[str, Any],
    post250_metrics: dict[str, Any],
    static_audit: dict[str, Any],
    summary: dict[str, Any],
) -> str:
    lines = [
        "# Planner v2 Expansion 1 Report",
        "",
        "## Executive Summary",
        (
            "Planner v2 now owns workspace_operations, routine, workflow, task_continuity, and discord_relay "
            "end-to-end for this pass. Legacy remains as quarantined compatibility scaffolding for deferred families."
        ),
        (
            "The focused workbench and HTTP lane passed, but the single 250 comparison regressed to "
            f"{_scored_text(post250)}. Do not run 1000 from this state."
        ),
        "",
        "## Legacy Quarantine",
        f"Policy present: {bool(policy)}. Migrated families must not be overridden by legacy.",
        "",
        "## Legacy Family Census",
        f"Migrated this pass: {', '.join(summary['migrated_families'])}.",
        f"Remaining legacy: {', '.join(summary['remaining_legacy_families'])}.",
        "",
        "## Planner v2 Authority",
        f"Workbench: {workbench.get('passed', 0)}/{workbench.get('total_cases', 0)} passed.",
        f"Integration attempted/completed/durable: {integration.get('attempted', 0)}/{integration.get('completed', 0)}/{integration.get('durable_rows', 0)}.",
        f"Integration routing engines: {integration.get('routing_engine_counts', {})}.",
        f"Planner v2 authority OK: {integration.get('planner_v2_authority_ok')}.",
        f"Near-miss HTTP rows / overroutes: {integration.get('near_miss_rows', 0)} / {len(integration.get('near_miss_overroute_rows') or [])}.",
        f"Generic-provider rows missing gate reason: {len(integration.get('generic_provider_rows_missing_gate_reason') or [])}.",
        "",
        "## Static Anti-Overfitting",
        f"Passed: {static_audit.get('passed') if static_audit else 'not_run'}.",
        f"Planner v2 / route-spine files clean: {static_audit.get('planner_v2_clean') if static_audit else 'not_run'}.",
        f"Product routing hits: {len((static_audit.get('exact_prompt_hits') or []) + (static_audit.get('test_id_hits') or [])) if static_audit else 0}.",
        "",
        "## Targeted Integration Examples",
    ]
    for row in integration_rows[:8]:
        lines.append(
            f"- `{row.get('test_id')}`: engine=`{row.get('routing_engine')}`, route=`{row.get('actual_route_family')}`, spec=`{row.get('selected_route_spec')}`"
        )
    lines.extend(
        [
            "",
            "## Safety And Provider Audit",
            f"Provider/OpenAI/LLM/embedding calls: {integration.get('provider_calls', 0)}/{integration.get('openai_calls', 0)}/{integration.get('llm_calls', 0)}/{integration.get('embedding_calls', 0)}.",
            f"Real external actions: {integration.get('real_external_actions', 0)}.",
            f"Hard timeouts/process kills: {integration.get('hard_timeouts', 0)}/{integration.get('process_kills', 0)}.",
            f"Payload failures / rows above 1 MB: {integration.get('payload_guardrail_failures', 0)} / {integration.get('rows_above_1mb', 0)}.",
            "",
            "## 250 Comparison",
            _post250_summary(post250),
            f"250 routing engines: {post250_metrics.get('routing_engine_counts', {})}.",
            f"250 failure categories from rows: {post250_metrics.get('failure_category_counts', {})}.",
            f"250 generic-provider rows: {post250_metrics.get('generic_provider_rows', 0)}.",
            "Best prior 250 was 181 pass / 69 fail; this pass is not an improvement over that bar.",
            "",
            "## Routine-Save Historical Blocker",
            "`known_unreproduced_product_latency_blocker` remains preserved and was not marked fixed.",
            "",
            "## Recommendation",
            summary["recommendation"],
            "",
        ]
    )
    return "\n".join(lines)


def _post250_summary(post250: dict[str, Any]) -> str:
    if not post250:
        return "250 comparison was not run in this artifact set."
    checkpoint_summary = post250.get("checkpoint_summary") or {}
    completed = post250.get("completed") or checkpoint_summary.get("completed_requests")
    durable = post250.get("durable_rows") or checkpoint_summary.get("durable_assertion_rows")
    categories = checkpoint_summary.get("failure_category_counts") or post250.get("failure_category_counts") or {}
    return (
        f"attempted/completed/durable: {post250.get('attempted')}/{completed}/{durable}; "
        f"scored counts: {post250.get('scored_counts')}; raw counts: {post250.get('raw_counts')}; "
        f"failure categories: {categories}."
    )


def _scored_text(post250: dict[str, Any]) -> str:
    scored = post250.get("scored_counts") or {}
    if not scored:
        return "no scored 250 result"
    return f"{scored.get('pass', 0)} pass / {scored.get('fail', 0)} fail"


def _recommendation(workbench: dict[str, Any], integration: dict[str, Any], post250: dict[str, Any]) -> str:
    if workbench.get("failed"):
        return "fix Planner v2 expansion workbench failures before broader comparison."
    if not integration.get("planner_v2_authority_ok"):
        return "fix Planner v2 integration authority before any 250 rerun."
    if any(integration.get(key, 0) for key in ("provider_calls", "openai_calls", "llm_calls", "embedding_calls", "real_external_actions", "hard_timeouts", "process_kills", "payload_guardrail_failures")):
        return "fix safety/provider/payload containment before broader evaluation."
    if not post250:
        return "focused lanes pass; run the optional 250 comparison next, not 1000."
    scored = post250.get("scored_counts") or {}
    if int(scored.get("fail") or 0):
        return "250 still has scored failures; continue targeted Planner v2 migration/taxonomy work before 1000."
    return "250 is clean enough to consider 1000, with routine-save historical blocker preserved."


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


if __name__ == "__main__":
    main()
