from __future__ import annotations

import argparse
import json
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
from stormhelm.core.orchestrator.planner_v2 import PlannerV2

import run_250_checkpoint as checkpoint


OUT = ROOT / ".artifacts" / "command-usability-eval" / "routing-gap-burndown-1"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run routing-gap burn-down 1 workbench/integration lanes.")
    parser.add_argument("--mode", choices=["workbench", "integration"], required=True)
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "workbench":
        run_workbench(args.output_dir)
    else:
        run_integration(args)


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
        checks = {
            "route_family": trace.route_decision.selected_route_family == case["expected_route_family"],
            "routing_engine": trace.route_decision.routing_engine == case["expected_routing_engine"],
            "result_state": trace.result_state_draft.result_state in case["expected_result_states"],
            "generic_gate": trace.route_decision.generic_provider_allowed == case["expected_generic_provider_allowed"],
            "binding_status": trace.context_binding.status in case["expected_binding_statuses"],
            "legacy_fallback": trace.legacy_fallback_used == case["expected_legacy_fallback_used"],
        }
        rows.append(
            {
                "test_id": case["test_id"],
                "prompt": case["prompt"],
                "lane": case["lane"],
                "expected_route_family": case["expected_route_family"],
                "actual_route_family": trace.route_decision.selected_route_family,
                "expected_routing_engine": case["expected_routing_engine"],
                "actual_routing_engine": trace.route_decision.routing_engine,
                "expected_result_states": case["expected_result_states"],
                "actual_result_state": trace.result_state_draft.result_state,
                "expected_binding_statuses": case["expected_binding_statuses"],
                "actual_binding_status": trace.context_binding.status,
                "generic_provider_allowed": trace.route_decision.generic_provider_allowed,
                "generic_provider_gate_reason": trace.route_decision.generic_provider_gate_reason,
                "legacy_fallback_used": trace.legacy_fallback_used,
                "candidate_specs_considered": list(trace.route_decision.candidate_specs_considered),
                "native_decline_reasons": trace.route_decision.native_decline_reasons,
                "checks": checks,
                "passed": all(checks.values()),
                "planner_v2_trace": trace.to_dict(),
            }
        )
    write_jsonl(output_dir / "burndown_workbench_results.jsonl", rows)
    summary = {
        "total": len(rows),
        "pass": sum(1 for row in rows if row["passed"]),
        "fail": sum(1 for row in rows if not row["passed"]),
        "route_family_counts": dict(Counter(str(row["actual_route_family"]) for row in rows)),
        "routing_engine_counts": dict(Counter(str(row["actual_routing_engine"]) for row in rows)),
        "legacy_fallback_usage": sum(1 for row in rows if row["legacy_fallback_used"]),
        "generic_provider_allowed_rows": sum(1 for row in rows if row["generic_provider_allowed"]),
        "failed_rows": [row["test_id"] for row in rows if not row["passed"]],
    }
    write_json(output_dir / "burndown_workbench_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def run_integration(args: argparse.Namespace) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")
    cases = integration_cases()
    write_jsonl(args.output_dir / "burndown_integration_corpus.jsonl", [case.to_dict() for case in cases])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(cases, results_name="burndown_integration_results.jsonl", resume=False)
    rows = read_jsonl(args.output_dir / "burndown_integration_results.jsonl")
    post_orphan = checkpoint._orphan_process_check_result()
    summary = build_checkpoint_summary(results, feature_audit=build_feature_audit(cases))
    summary.update(
        {
            "pre_orphan_process_check": pre_orphan,
            "post_orphan_process_check": post_orphan,
            "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
            "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
            "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
            "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
            "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
            "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout"),
            "process_kills": sum(1 for row in rows if row.get("process_killed")),
            "payload_guardrail_failures": sum(1 for row in rows if row.get("failure_category") == "payload_guardrail_failure"),
            "planner_v2_rows": sum(1 for row in rows if row.get("routing_engine") == "planner_v2"),
            "generic_provider_rows": sum(1 for row in rows if row.get("actual_route_family") == "generic_provider"),
            "missing_context_native_clarifications": sum(
                1
                for row in rows
                if row.get("expected_approval_state") != "provider"
                and row.get("actual_route_family") != "generic_provider"
                and row.get("result_state") == "needs_clarification"
            ),
            "non_planner_v2_rows": [
                {
                    "test_id": row.get("test_id"),
                    "expected_route_family": row.get("expected_route_family"),
                    "actual_route_family": row.get("actual_route_family"),
                    "routing_engine": row.get("routing_engine"),
                    "failure_category": row.get("failure_category"),
                }
                for row in rows
                if row.get("routing_engine") != "planner_v2" and row.get("expected_route_family") != "generic_provider"
            ],
        }
    )
    write_json(args.output_dir / "burndown_integration_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def workbench_cases() -> list[dict[str, Any]]:
    return [
        positive_browser("exact_browser_followup", "do the same thing as before"),
        positive_browser("variant_browser_repeat", "repeat the previous browser open"),
        positive_browser("variant_browser_again", "open that page again"),
        missing_browser("missing_browser_context", "open that website again"),
        positive_context("exact_context_followup", "do the same thing as before"),
        missing_context("missing_context_selection", "reuse the previous selection"),
        positive_app("exact_active_apps_followup", "do the same thing as before"),
        positive_app("variant_active_apps_again", "show active apps again"),
        missing_discord("exact_discord_followup_missing_destination", "do the same thing as before"),
        missing_discord("variant_discord_missing_destination", "send that again"),
        generic_negative("near_miss_no_owner_same", "do the same thing as before"),
        generic_negative("near_miss_no_owner_this", "use this for that"),
    ]


def positive_browser(test_id: str, text: str) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "prompt": text,
        "lane": "positive",
        "expected_route_family": "browser_destination",
        "expected_routing_engine": "planner_v2",
        "expected_result_states": {"dry_run_ready"},
        "expected_binding_statuses": {"available"},
        "expected_generic_provider_allowed": False,
        "expected_legacy_fallback_used": False,
        "active_request_state": {"family": "browser_destination", "subject": "browser destination", "parameters": {"request_stage": "preview"}},
        "active_context": {"recent_entities": [{"kind": "page", "title": "Stormhelm docs", "url": "https://docs.example.com/stormhelm"}]},
    }


def missing_browser(test_id: str, text: str) -> dict[str, Any]:
    case = positive_browser(test_id, text)
    case["lane"] = "missing_context"
    case["expected_result_states"] = {"needs_clarification"}
    case["expected_binding_statuses"] = {"missing"}
    case["active_context"] = {}
    return case


def positive_context(test_id: str, text: str) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "prompt": text,
        "lane": "positive",
        "expected_route_family": "context_action",
        "expected_routing_engine": "planner_v2",
        "expected_result_states": {"dry_run_ready"},
        "expected_binding_statuses": {"available"},
        "expected_generic_provider_allowed": False,
        "expected_legacy_fallback_used": False,
        "active_request_state": {"family": "context_action", "subject": "context action", "parameters": {"request_stage": "preview"}},
        "active_context": {"selection": {"kind": "text", "value": "selected launch notes", "preview": "selected launch notes"}},
    }


def missing_context(test_id: str, text: str) -> dict[str, Any]:
    case = positive_context(test_id, text)
    case["lane"] = "missing_context"
    case["expected_result_states"] = {"needs_clarification"}
    case["expected_binding_statuses"] = {"missing"}
    case["active_context"] = {}
    return case


def positive_app(test_id: str, text: str) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "prompt": text,
        "lane": "positive",
        "expected_route_family": "app_control",
        "expected_routing_engine": "planner_v2",
        "expected_result_states": {"dry_run_ready"},
        "expected_binding_statuses": {"available"},
        "expected_generic_provider_allowed": False,
        "expected_legacy_fallback_used": False,
        "active_request_state": {"family": "app_control", "subject": "active apps", "parameters": {"source_case": "active_apps", "request_stage": "preview"}},
    }


def missing_discord(test_id: str, text: str) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "prompt": text,
        "lane": "missing_context",
        "expected_route_family": "discord_relay",
        "expected_routing_engine": "planner_v2",
        "expected_result_states": {"needs_clarification"},
        "expected_binding_statuses": {"missing"},
        "expected_generic_provider_allowed": False,
        "expected_legacy_fallback_used": False,
        "active_request_state": {"family": "discord_relay", "subject": "discord relay", "parameters": {"request_stage": "preview"}},
        "active_context": {"selection": {"kind": "text", "value": "selected launch notes", "preview": "selected launch notes"}},
    }


def generic_negative(test_id: str, text: str) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "prompt": text,
        "lane": "near_miss",
        "expected_route_family": "legacy_planner",
        "expected_routing_engine": "legacy_planner",
        "expected_result_states": {"unsupported", "dry_run_ready"},
        "expected_binding_statuses": {"missing"},
        "expected_generic_provider_allowed": True,
        "expected_legacy_fallback_used": True,
        "active_request_state": {},
        "active_context": {},
    }


def integration_cases() -> list[CommandEvalCase]:
    return [
        _case(
            "burndown_browser_followup_exact",
            "do the same thing as before",
            "browser_destination",
            "browser",
            ("external_open_url",),
            active_request_state={"family": "browser_destination", "subject": "browser destination", "parameters": {"request_stage": "preview", "source_case": "browser_destination"}},
            input_context={"recent_entities": [{"kind": "page", "title": "Stormhelm docs", "url": "https://docs.example.com/stormhelm", "freshness": "current"}]},
            clarification="allowed",
            approval="allowed",
        ),
        _case(
            "burndown_browser_followup_variant",
            "repeat the previous browser open",
            "browser_destination",
            "browser",
            ("external_open_url",),
            active_request_state={"family": "browser_destination", "subject": "browser destination", "parameters": {"request_stage": "preview"}},
            input_context={"recent_entities": [{"kind": "page", "title": "Stormhelm docs", "url": "https://docs.example.com/stormhelm"}]},
            clarification="allowed",
            approval="allowed",
        ),
        _case(
            "burndown_context_missing_exact",
            "do the same thing as before",
            "context_action",
            "context",
            (),
            active_request_state={"family": "context_action", "subject": "context action", "parameters": {"request_stage": "preview"}},
            clarification="expected",
        ),
        _case(
            "burndown_context_selection_variant",
            "reuse the previous selection",
            "context_action",
            "context",
            ("context_action",),
            active_request_state={"family": "context_action", "subject": "context action", "parameters": {"request_stage": "preview"}},
            input_context={"selection": {"kind": "text", "value": "selected launch notes", "preview": "selected launch notes"}},
            clarification="allowed",
        ),
        _case(
            "burndown_active_apps_followup_exact",
            "do the same thing as before",
            "app_control",
            "system",
            ("active_apps",),
            active_request_state={"family": "app_control", "subject": "active apps", "parameters": {"request_stage": "preview", "source_case": "active_apps"}},
            clarification="allowed",
        ),
        _case(
            "burndown_discord_missing_destination_exact",
            "do the same thing as before",
            "discord_relay",
            "discord_relay",
            (),
            active_request_state={"family": "discord_relay", "subject": "discord relay", "parameters": {"request_stage": "preview"}},
            input_context={"selection": {"kind": "text", "value": "selected launch notes", "preview": "selected launch notes"}},
            clarification="expected",
            approval="allowed",
        ),
        _case(
            "burndown_near_miss_no_owner_followup",
            "do the same thing as before",
            "generic_provider",
            "provider",
            (),
            clarification="allowed",
        ),
        _case(
            "burndown_near_miss_no_owner_deictic",
            "use this for that",
            "generic_provider",
            "provider",
            (),
            clarification="allowed",
        ),
    ]


def _case(
    case_id: str,
    message: str,
    route_family: str,
    subsystem: str,
    tools: tuple[str, ...],
    *,
    active_request_state: dict[str, Any] | None = None,
    input_context: dict[str, Any] | None = None,
    clarification: str = "none",
    approval: str = "not_expected",
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
            latency_ms_max=60_000,
        ),
        active_request_state=active_request_state or {},
        input_context=input_context or {},
        tags=("routing_gap_burndown_1",),
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


if __name__ == "__main__":
    main()
