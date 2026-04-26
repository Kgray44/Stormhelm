from __future__ import annotations

import argparse
import json
import statistics
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


OUTPUT_DIR = ROOT / ".artifacts" / "command-usability-eval" / "planner-v2"


def main() -> None:
    parser = argparse.ArgumentParser(description="Planner v2 design, workbench, and bounded integration lane.")
    parser.add_argument(
        "--mode",
        choices=["design", "workbench", "integration", "finalize", "all"],
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.mode in {"design", "all"}:
        write_design_artifacts(args.output_dir)
    if args.mode in {"workbench", "all"}:
        run_workbench(args.output_dir)
    if args.mode in {"integration", "all"}:
        run_integration_lane(args)
    if args.mode in {"finalize", "all"}:
        write_final_report(args.output_dir)


def write_design_artifacts(output_dir: Path) -> None:
    architecture = {
        "purpose": (
            "Planner v2 is a thin typed planning spine that runs before the legacy planner for selected families. "
            "It separates intent extraction, context binding, capability matching, policy, result-state composition, "
            "and telemetry so route decisions are explainable and not dependent on legacy branch order."
        ),
        "pipeline": [
            {
                "stage": "InputNormalizer",
                "responsibility": "Remove invocation fluff, normalize whitespace and casing, and produce NormalizedRequest.",
            },
            {
                "stage": "IntentFrameExtractor",
                "responsibility": "Produce the typed IntentFrame with speech act, operation, target type, context reference, risk class, and native owner hints.",
            },
            {
                "stage": "ContextBinder",
                "responsibility": "Resolve selected/highlighted/current/prior/visible references into a ContextBinding with available/missing/stale/ambiguous/unsupported status.",
            },
            {
                "stage": "CapabilityRegistry / RouteFamilySpec registry",
                "responsibility": "Expose capability contracts for selected route families from declarative specs.",
            },
            {
                "stage": "CandidateGenerator",
                "responsibility": "Generate route candidates from contracts and score operation, target, risk, context, positive signals, and near-miss guards.",
            },
            {
                "stage": "RouteArbitrator",
                "responsibility": "Choose a native route, native clarification, generic provider, or explicit legacy fallback with decline reasons.",
            },
            {
                "stage": "PlanBuilder",
                "responsibility": "Turn the route decision into a route-family-owned PlanDraft and planned tool shape.",
            },
            {
                "stage": "PolicyEvaluator",
                "responsibility": "Decide live approval, preview, trust, dry-run allowance, and execution blocking separately from routing.",
            },
            {
                "stage": "ResultStateComposer",
                "responsibility": "Compose planned/dry_run_ready/needs_clarification/blocked/unsupported states without route selection inventing success copy.",
            },
            {
                "stage": "TelemetryEmitter",
                "responsibility": "Emit PlannerV2Trace plus compatibility route-spine telemetry for command evaluation.",
            },
        ],
        "typed_models": [
            "NormalizedRequest",
            "IntentFrame",
            "ContextBinding",
            "CapabilitySpec",
            "RouteCandidate",
            "RouteDecision",
            "PlanDraft",
            "PolicyDecision",
            "ResultStateDraft",
            "PlannerV2Trace",
        ],
        "authoritative_families": sorted(PLANNER_V2_ROUTE_FAMILIES),
        "legacy_compatibility": {
            "policy": "Legacy planner remains only after Planner v2 explicitly declines with no selected-family native owner.",
            "fallback_reason": "no_planner_v2_native_owner",
            "not_allowed_for": "Planner v2 selected families with missing/stale/ambiguous context; those clarify natively instead.",
        },
        "generic_provider_gate": {
            "law": "generic_provider may become eligible only after native candidates decline with reasons.",
            "command_eval_default": "provider/OpenAI/LLM/embedding calls remain disabled and audited.",
            "native_missing_context": "Native owner wins and asks for context instead of falling through to generic_provider.",
        },
        "context_binding": {
            "references": [
                "this",
                "that",
                "it",
                "selected text",
                "highlighted text",
                "current page",
                "current file",
                "current app",
                "prior calculation",
                "prior result",
                "visible UI target",
            ],
            "statuses": ["available", "missing", "stale", "ambiguous", "unsupported"],
            "principle": "Unavailable context is a typed missing precondition, not evidence for provider fallback.",
        },
        "policy_separation": {
            "routing_decides": ["intent", "native owner", "target/context preconditions", "plan shape"],
            "policy_decides": ["approval", "preview", "trust scope", "dry-run allowance", "execution block"],
        },
        "result_state_composition": [
            "planned",
            "dry_run_ready",
            "needs_clarification",
            "blocked_missing_context",
            "blocked_policy",
            "requires_approval",
            "unsupported",
            "completed",
            "verified",
            "failed",
        ],
        "telemetry": [
            "planner_v2_trace",
            "routing_engine",
            "intent_frame",
            "candidate_specs_considered",
            "selected_route_spec",
            "native_decline_reasons",
            "generic_provider_gate_reason",
            "legacy_fallback_used",
        ],
    }
    write_json(output_dir / "planner_v2_architecture.json", architecture)
    (output_dir / "planner_v2_architecture.md").write_text(_architecture_markdown(architecture), encoding="utf-8")


def run_workbench(output_dir: Path) -> None:
    planner = PlannerV2()
    rows: list[dict[str, Any]] = []
    for case in workbench_cases():
        trace = planner.plan(
            case["prompt"],
            surface_mode=case.get("surface_mode", "ghost"),
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
                "expected_result_state": case.get("expected_result_state", ""),
                "actual_result_state": trace.result_state_draft.result_state,
                "expected_binding_status": case.get("expected_binding_status", ""),
                "actual_binding_status": trace.context_binding.status,
                "legacy_fallback_used": trace.legacy_fallback_used,
                "generic_provider_allowed": trace.route_decision.generic_provider_allowed,
                "generic_provider_gate_reason": trace.route_decision.generic_provider_gate_reason,
                "native_decline_reasons": trace.route_decision.native_decline_reasons,
                "candidate_specs_considered": list(trace.route_decision.candidate_specs_considered),
                "checks": checks,
                "passed": passed,
                "planner_v2_trace": trace.to_dict(),
            }
        )
    write_jsonl(output_dir / "planner_v2_workbench_results.jsonl", rows)
    summary = _workbench_summary(rows)
    write_json(output_dir / "planner_v2_workbench_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def run_integration_lane(args: argparse.Namespace) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")
    cases = integration_cases()
    write_jsonl(args.output_dir / "planner_v2_integration_corpus.jsonl", [case.to_dict() for case in cases])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(cases, results_name="planner_v2_integration_results.jsonl", resume=False)
    rows = _read_jsonl(args.output_dir / "planner_v2_integration_results.jsonl")
    post_orphan = checkpoint._orphan_process_check_result()
    summary = build_checkpoint_summary(results, feature_audit=build_feature_audit(cases))
    summary.update(_run_safety_summary(cases, results, rows, pre_orphan, post_orphan))
    summary["planner_v2_family_rows"] = sum(1 for row in rows if row.get("expected_route_family") in PLANNER_V2_ROUTE_FAMILIES)
    summary["planner_v2_authoritative_rows"] = sum(1 for row in rows if row.get("routing_engine") == "planner_v2")
    summary["planner_v2_authority_ok"] = summary["planner_v2_family_rows"] == summary["planner_v2_authoritative_rows"]
    summary["recommendation"] = "planner_v2_slice_complete_do_not_run_250_or_1000_in_this_pass"
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
    write_json(args.output_dir / "planner_v2_integration_summary.json", summary)
    print(json.dumps({"attempted": len(cases), "completed": len(results), "durable_rows": len(rows)}, indent=2))


def write_final_report(output_dir: Path) -> None:
    workbench = _read_json(output_dir / "planner_v2_workbench_summary.json")
    integration = _read_json(output_dir / "planner_v2_integration_summary.json")
    integration_rows = _read_jsonl(output_dir / "planner_v2_integration_results.jsonl")
    architecture = _read_json(output_dir / "planner_v2_architecture.json")
    summary = {
        "architecture_added": bool(architecture),
        "authoritative_families": architecture.get("authoritative_families", sorted(PLANNER_V2_ROUTE_FAMILIES)),
        "workbench": workbench,
        "integration": integration,
        "recommendation": "migrate_more_families_or_run_250_comparison_next",
        "do_not_run_1000_yet": True,
        "routine_save_historical_blocker": "known_unreproduced_product_latency_blocker",
    }
    write_json(output_dir / "planner_v2_summary.json", summary)
    (output_dir / "planner_v2_report.md").write_text(
        _final_report_markdown(architecture, workbench, integration, integration_rows),
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
        recent_tool_results: list[dict[str, Any]] | None = None,
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
                "recent_tool_results": recent_tool_results or [],
                "expected_generic_provider_allowed": generic_allowed,
                "expected_legacy_fallback_used": legacy_fallback,
                "lane": lane,
            }
        )

    add("planner_v2_direct_math", "what is 7 * 8", "calculations", lane="positive", result_state="dry_run_ready")
    add(
        "planner_v2_calc_followup",
        "now divide that by 3",
        "calculations",
        lane="followup",
        result_state="dry_run_ready",
        binding_status="available",
        active_context={
            "recent_context_resolutions": [
                {"kind": "calculation", "result": {"expression": "18 / 3", "display_result": "6"}}
            ]
        },
    )
    add(
        "planner_v2_calc_missing_context",
        "now divide that by 3",
        "calculations",
        lane="missing_context",
        result_state="needs_clarification",
        binding_status="missing",
        generic_allowed=False,
    )
    add("planner_v2_open_url", "open https://example.com/status", "browser_destination", lane="positive")
    add(
        "planner_v2_open_that_website_missing",
        "open that website",
        "browser_destination",
        lane="missing_context",
        result_state="needs_clarification",
        binding_status="missing",
        generic_allowed=False,
    )
    add(
        "planner_v2_open_current_page_bound",
        "open that website",
        "browser_destination",
        lane="deictic",
        binding_status="available",
        active_context={
            "recent_entities": [
                {"kind": "page", "title": "Docs", "url": "https://docs.example.com/stormhelm", "freshness": "current"}
            ]
        },
    )
    add("planner_v2_open_app", "open Notepad", "app_control", lane="positive")
    add("planner_v2_quit_app", "quit Notepad", "app_control", lane="positive")
    add("planner_v2_install_software", "install Minecraft", "software_control", lane="positive", result_state="dry_run_ready")
    add("planner_v2_verify_software", "check if Git is installed", "software_control", lane="positive", result_state="dry_run_ready")
    add(
        "planner_v2_screen_status",
        "what am I looking at",
        "screen_awareness",
        lane="missing_context",
        result_state="needs_clarification",
        binding_status="missing",
        generic_allowed=False,
    )
    add(
        "planner_v2_press_submit",
        "press submit",
        "screen_awareness",
        lane="missing_context",
        result_state="needs_clarification",
        binding_status="missing",
        generic_allowed=False,
    )
    add("planner_v2_wifi_status", "which wifi am I on", "network", lane="positive")
    add("planner_v2_file_path", r"open C:\Stormhelm\README.md", "file", lane="positive")
    add(
        "planner_v2_selected_text",
        "summarize the selected text",
        "context_action",
        lane="context",
        binding_status="available",
        active_context={
            "selection": {
                "kind": "text",
                "value": "Selected Stormhelm routing notes.",
                "preview": "Selected Stormhelm routing notes.",
            }
        },
    )
    add(
        "planner_v2_neural_network_near_miss",
        "which neural network architecture is better",
        "generic_provider",
        lane="near_miss",
        engine="generic_provider",
        result_state="unsupported",
        generic_allowed=True,
    )
    add(
        "planner_v2_generic_legacy_decline_control",
        "write me a cozy paragraph about planning",
        "legacy_planner",
        lane="legacy_fallback_control",
        engine="legacy_planner",
        legacy_fallback=True,
    )
    return rows


def integration_cases() -> list[CommandEvalCase]:
    cases = [
        _case("planner_v2_http_direct_math", "what is 7 * 8", "calculations", "calculations", tags=("planner_v2", "calculation")),
        _case(
            "planner_v2_http_calc_missing",
            "now divide that by 3",
            "calculations",
            "calculations",
            clarification="expected",
            tags=("planner_v2", "calculation", "missing_context"),
        ),
        _case(
            "planner_v2_http_open_url",
            "open https://example.com/status",
            "browser_destination",
            "browser",
            tools=("external_open_url",),
            approval="allowed",
            tags=("planner_v2", "browser"),
        ),
        _case(
            "planner_v2_http_open_website_missing",
            "open that website",
            "browser_destination",
            "browser",
            clarification="expected",
            tags=("planner_v2", "browser", "missing_context"),
        ),
        _case(
            "planner_v2_http_open_notepad",
            "open Notepad",
            "app_control",
            "system",
            tools=("app_control",),
            approval="allowed",
            tags=("planner_v2", "app_control"),
        ),
        _case(
            "planner_v2_http_quit_notepad",
            "quit Notepad",
            "app_control",
            "system",
            tools=("app_control",),
            approval="allowed",
            tags=("planner_v2", "app_control"),
        ),
        _case(
            "planner_v2_http_install_minecraft",
            "install Minecraft",
            "software_control",
            "software_control",
            approval="allowed",
            tags=("planner_v2", "software_control"),
        ),
        _case(
            "planner_v2_http_verify_git",
            "check if Git is installed",
            "software_control",
            "software_control",
            tags=("planner_v2", "software_control", "read_only"),
        ),
        _case(
            "planner_v2_http_screen_status",
            "what am I looking at",
            "screen_awareness",
            "screen_awareness",
            clarification="expected",
            tags=("planner_v2", "screen_awareness"),
        ),
        _case(
            "planner_v2_http_press_submit",
            "press submit",
            "screen_awareness",
            "screen_awareness",
            clarification="expected",
            tags=("planner_v2", "screen_awareness"),
        ),
        _case(
            "planner_v2_http_wifi_status",
            "which wifi am I on",
            "network",
            "system",
            tools=("network_status",),
            tags=("planner_v2", "watch_runtime", "network"),
        ),
        _case(
            "planner_v2_http_file_path",
            r"open C:\Stormhelm\README.md",
            "file",
            "files",
            tools=("external_open_file",),
            approval="allowed",
            tags=("planner_v2", "file"),
        ),
        _case(
            "planner_v2_http_selected_text",
            "summarize the selected text",
            "context_action",
            "context",
            tools=("context_action",),
            input_context={
                "selection": {
                    "kind": "text",
                    "value": "Selected Stormhelm routing notes.",
                    "preview": "Selected Stormhelm routing notes.",
                }
            },
            tags=("planner_v2", "context_action"),
        ),
    ]
    return cases


def _case(
    case_id: str,
    message: str,
    route_family: str,
    subsystem: str,
    *,
    tools: tuple[str, ...] = (),
    clarification: str = "none",
    approval: str = "not_expected",
    input_context: dict[str, Any] | None = None,
    active_request_state: dict[str, Any] | None = None,
    tags: tuple[str, ...] = (),
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
        input_context=input_context or {},
        active_request_state=active_request_state or {},
        tags=tags,
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
        checks["generic_provider_allowed"] = trace.route_decision.generic_provider_allowed == bool(
            case["expected_generic_provider_allowed"]
        )
    if case["expected_route_family"] in PLANNER_V2_ROUTE_FAMILIES:
        checks["authoritative_selected_family"] = trace.authoritative is True
        checks["no_legacy_for_selected_family"] = trace.legacy_fallback_used is False
    return checks


def _workbench_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for row in rows if row.get("passed"))
    return {
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "routing_engine_counts": dict(Counter(str(row.get("actual_routing_engine") or "") for row in rows)),
        "route_family_accuracy": _rate(rows, "route_family"),
        "result_state_accuracy": _rate(rows, "result_state"),
        "context_binding_accuracy": _rate(rows, "binding_status"),
        "missing_context_handling": _lane_rate(rows, "missing_context"),
        "near_miss_rejection": _lane_rate(rows, "near_miss"),
        "generic_provider_gate_correctness": _rate(rows, "generic_provider_allowed"),
        "legacy_fallback_usage_count": sum(1 for row in rows if row.get("legacy_fallback_used")),
        "unexpected_legacy_fallback_usage_count": sum(
            1
            for row in rows
            if row.get("legacy_fallback_used") and row.get("expected_route_family") in PLANNER_V2_ROUTE_FAMILIES
        ),
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
        "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
        "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
        "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
        "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
        "payload_guardrail_failures": sum(
            1
            for row in rows
            if row.get("payload_guardrail_triggered") and row.get("payload_guardrail_reason") != "workspace_items_truncated"
        ),
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
    return {
        "applicable": len(applicable),
        "passed": passed,
        "failed": len(applicable) - passed,
        "rate": round(passed / len(applicable), 4) if applicable else 0.0,
    }


def _lane_rate(rows: list[dict[str, Any]], lane: str) -> dict[str, Any]:
    applicable = [row for row in rows if row.get("lane") == lane]
    passed = sum(1 for row in applicable if row.get("passed"))
    return {
        "applicable": len(applicable),
        "passed": passed,
        "failed": len(applicable) - passed,
        "rate": round(passed / len(applicable), 4) if applicable else 0.0,
    }


def _architecture_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Planner v2 Architecture",
        "",
        "## Purpose",
        payload["purpose"],
        "",
        "## Pipeline Stages",
    ]
    for stage in payload["pipeline"]:
        lines.append(f"- **{stage['stage']}**: {stage['responsibility']}")
    lines.extend(
        [
            "",
            "## Typed Models",
            ", ".join(payload["typed_models"]),
            "",
            "## Authoritative Families",
            ", ".join(payload["authoritative_families"]),
            "",
            "## Legacy Fallback",
            payload["legacy_compatibility"]["policy"],
            "",
            "## Generic Provider Gate",
            payload["generic_provider_gate"]["law"],
            "",
            "## Context Binding",
            payload["context_binding"]["principle"],
            "",
            "## Policy Separation",
            "Routing decides intent and plan shape. Policy decides approval, preview, trust, dry-run, and execution blocking.",
            "",
            "## Result-State Composition",
            ", ".join(payload["result_state_composition"]),
            "",
            "## Telemetry",
            ", ".join(payload["telemetry"]),
            "",
        ]
    )
    return "\n".join(lines)


def _final_report_markdown(
    architecture: dict[str, Any],
    workbench: dict[str, Any],
    integration: dict[str, Any],
    integration_rows: list[dict[str, Any]],
) -> str:
    routing_counts = integration.get("routing_engine_counts") or {}
    lines = [
        "# Planner v2 Report",
        "",
        "## Executive Summary",
        (
            "Planner v2 now exists as a real typed pipeline for the selected calculation, browser, app, file/context, "
            "screen-awareness, software-control, watch/runtime, and network/status families. The legacy planner remains, "
            "but only after Planner v2 explicitly declines ownership."
        ),
        "",
        "## Architecture Added",
        f"Typed stages: {', '.join(stage['stage'] for stage in architecture.get('pipeline', []))}.",
        "",
        "## Authoritative Families",
        ", ".join(architecture.get("authoritative_families", sorted(PLANNER_V2_ROUTE_FAMILIES))),
        "",
        "## Legacy Fallback Control",
        "Planner v2 emits `legacy_fallback_used` and `generic_provider_gate_reason`; missing context inside selected families clarifies natively.",
        "",
        "## Generic Provider Gate",
        "The provider route is eligible only after native candidates decline with recorded reasons. Eval provider/OpenAI/LLM/embedding usage remains blocked and audited.",
        "",
        "## Context Binding",
        "Bindings cover deictic browser targets, selected text, visible UI, prior calculations/results, current files/apps/pages, and explicit missing-context statuses.",
        "",
        "## Policy Separation",
        "Planner v2 emits `PlanDraft`; `PolicyEvaluator` separately decides live approval, preview, dry-run, trust scope, and execution blocking.",
        "",
        "## Result-State Composition",
        "Result-state composition now emits `dry_run_ready`, `needs_clarification`, and `unsupported` for the thin slice without route selection writing success claims.",
        "",
        "## Workbench Results",
        f"Workbench: {workbench.get('passed', 0)}/{workbench.get('total_cases', 0)} passed.",
        f"Near-miss preservation: {workbench.get('near_miss_rejection', {}).get('passed', 0)}/{workbench.get('near_miss_rejection', {}).get('applicable', 0)}.",
        f"Unexpected legacy fallback for selected families: {workbench.get('unexpected_legacy_fallback_usage_count', 0)}.",
        "",
        "## Integration Lane Results",
        f"Attempted/completed/durable: {integration.get('attempted', 0)}/{integration.get('completed', 0)}/{integration.get('durable_rows', 0)}.",
        f"Routing engines: {routing_counts}.",
        f"Planner v2 authority OK: {integration.get('planner_v2_authority_ok')}.",
        f"Provider/OpenAI/LLM/embedding calls: {integration.get('provider_calls', 0)}/{integration.get('openai_calls', 0)}/{integration.get('llm_calls', 0)}/{integration.get('embedding_calls', 0)}.",
        f"Real external actions: {integration.get('real_external_actions', 0)}.",
        f"Hard timeouts/process kills: {integration.get('hard_timeouts', 0)}/{integration.get('process_kills', 0)}.",
        f"Payload failures / rows above 1 MB: {integration.get('payload_guardrail_failures', 0)} / {integration.get('rows_above_1mb', 0)}.",
        "",
        "## Telemetry Examples",
    ]
    for row in integration_rows[:5]:
        lines.append(
            f"- `{row.get('test_id')}`: engine=`{row.get('routing_engine')}`, route=`{row.get('actual_route_family')}`, "
            f"spec=`{row.get('selected_route_spec')}`, generic_gate=`{row.get('generic_provider_gate_reason')}`."
        )
    lines.extend(
        [
            "",
            "## Left On Legacy",
            "Workspace, routine, workflow, task-continuity, Discord relay, terminal, maintenance, trust, power, machine, desktop search, and other families remain outside this Planner v2 slice.",
            "",
            "## Risks",
            "- This is a thin vertical slice, not proof that the 250 or 1000 corpus is ready.",
            "- Broad quality still depends on migrating additional families and checking taxonomy compatibility.",
            "- The old native `routine_save` catastrophic latency remains `known_unreproduced_product_latency_blocker`.",
            "",
            "## Recommendation",
            "Use this as the base for the next pass: either migrate more families into Planner v2 or run a bounded 250 comparison with Planner v2 telemetry. Do not run 1000 yet.",
            "",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    main()
