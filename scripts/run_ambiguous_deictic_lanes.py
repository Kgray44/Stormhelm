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


OUT = ROOT / ".artifacts" / "command-usability-eval" / "ambiguous-deictic-clarification"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ambiguous-deictic Planner v2 workbench/integration lanes.")
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
            "subsystem": trace.route_decision.selected_subsystem == case["expected_subsystem"],
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
                "expected_subsystem": case["expected_subsystem"],
                "actual_subsystem": trace.route_decision.selected_subsystem,
                "expected_routing_engine": case["expected_routing_engine"],
                "actual_routing_engine": trace.route_decision.routing_engine,
                "expected_result_states": sorted(case["expected_result_states"]),
                "actual_result_state": trace.result_state_draft.result_state,
                "expected_binding_statuses": sorted(case["expected_binding_statuses"]),
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
    write_jsonl(output_dir / "ambiguous_deictic_workbench_results.jsonl", rows)
    summary = {
        "total": len(rows),
        "pass": sum(1 for row in rows if row["passed"]),
        "fail": sum(1 for row in rows if not row["passed"]),
        "route_family_counts": dict(Counter(str(row["actual_route_family"]) for row in rows)),
        "routing_engine_counts": dict(Counter(str(row["actual_routing_engine"]) for row in rows)),
        "legacy_fallback_usage": sum(1 for row in rows if row["legacy_fallback_used"]),
        "generic_provider_allowed_rows": sum(1 for row in rows if row["generic_provider_allowed"]),
        "context_clarification_rows": sum(1 for row in rows if row["actual_route_family"] == "context_clarification"),
        "failed_rows": [row["test_id"] for row in rows if not row["passed"]],
    }
    write_json(output_dir / "ambiguous_deictic_workbench_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def run_integration(args: argparse.Namespace) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")
    cases = integration_cases()
    write_jsonl(args.output_dir / "ambiguous_deictic_integration_corpus.jsonl", [case.to_dict() for case in cases])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(cases, results_name="ambiguous_deictic_integration_results.jsonl", resume=False)
    rows = read_jsonl(args.output_dir / "ambiguous_deictic_integration_results.jsonl")
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
            "context_clarification_rows": sum(1 for row in rows if row.get("actual_route_family") == "context_clarification"),
            "native_clarification_rows": sum(
                1
                for row in rows
                if row.get("actual_route_family") != "generic_provider"
                and row.get("actual_result_state") in {"needs_clarification", "blocked_missing_context"}
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
    write_json(args.output_dir / "ambiguous_deictic_integration_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def workbench_cases() -> list[dict[str, Any]]:
    return [
        context_clarification("no_owner_deictic_exact", "use this for that", active_context=selected_context()),
        context_clarification("no_owner_followup_exact", "do the same thing as before"),
        context_clarification("no_owner_deictic_variant", "use the current thing for the previous thing", active_context=selected_context()),
        context_clarification("no_owner_followup_variant", "repeat what I just meant with that"),
        browser_followup("prior_browser_owner_deictic", "use this for that"),
        app_followup("prior_app_owner_deictic", "use this for that"),
        discord_missing("discord_missing_payload", "send this to Baby"),
        routine_missing("routine_missing_context", "save this as a routine"),
        trust_pending("trust_pending_deictic", "use this for that"),
        not_context("conceptual_this_question", "what is this architecture concept"),
        legacy_not_context("general_question_no_deictic", "write a two sentence pep talk for finals"),
        browser_confident("confident_url_open", "open https://example.com"),
    ]


def base_case(test_id: str, prompt: str, route_family: str, subsystem: str) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "prompt": prompt,
        "lane": "positive",
        "expected_route_family": route_family,
        "expected_subsystem": subsystem,
        "expected_routing_engine": "planner_v2",
        "expected_result_states": {"dry_run_ready"},
        "expected_binding_statuses": {"available"},
        "expected_generic_provider_allowed": False,
        "expected_legacy_fallback_used": False,
        "active_context": {},
        "active_request_state": {},
    }


def context_clarification(test_id: str, prompt: str, *, active_context: dict[str, Any] | None = None) -> dict[str, Any]:
    case = base_case(test_id, prompt, "context_clarification", "context")
    case.update(
        {
            "lane": "ambiguous_no_owner",
            "expected_result_states": {"needs_clarification"},
            "expected_binding_statuses": {"missing", "ambiguous"},
            "active_context": active_context or {},
        }
    )
    return case


def browser_followup(test_id: str, prompt: str) -> dict[str, Any]:
    case = base_case(test_id, prompt, "browser_destination", "browser")
    case.update(
        {
            "lane": "prior_owner",
            "expected_result_states": {"needs_clarification", "dry_run_ready"},
            "expected_binding_statuses": {"missing", "available"},
            "active_request_state": {"family": "browser_destination", "subject": "browser destination", "parameters": {"request_stage": "preview"}},
        }
    )
    return case


def app_followup(test_id: str, prompt: str) -> dict[str, Any]:
    case = base_case(test_id, prompt, "app_control", "system")
    case.update(
        {
            "lane": "prior_owner",
            "active_request_state": {"family": "app_control", "subject": "active apps", "parameters": {"source_case": "active_apps", "request_stage": "preview"}},
        }
    )
    return case


def discord_missing(test_id: str, prompt: str) -> dict[str, Any]:
    case = base_case(test_id, prompt, "discord_relay", "discord_relay")
    case.update({"lane": "missing_context", "expected_result_states": {"needs_clarification"}, "expected_binding_statuses": {"missing"}})
    return case


def routine_missing(test_id: str, prompt: str) -> dict[str, Any]:
    case = base_case(test_id, prompt, "routine", "routine")
    case.update({"lane": "missing_context", "expected_result_states": {"needs_clarification"}, "expected_binding_statuses": {"missing"}})
    return case


def trust_pending(test_id: str, prompt: str) -> dict[str, Any]:
    case = base_case(test_id, prompt, "trust_approvals", "trust")
    case.update(
        {
            "lane": "regression",
            "expected_result_states": {"dry_run_ready"},
            "expected_binding_statuses": {"available"},
            "active_context": selected_context(),
            "active_request_state": trust_state(),
        }
    )
    return case


def not_context(test_id: str, prompt: str) -> dict[str, Any]:
    case = base_case(test_id, prompt, "generic_provider", "provider")
    case.update(
        {
            "lane": "near_miss",
            "expected_routing_engine": "generic_provider",
            "expected_result_states": {"unsupported"},
            "expected_binding_statuses": {"available", "missing"},
            "expected_generic_provider_allowed": True,
        }
    )
    return case


def legacy_not_context(test_id: str, prompt: str) -> dict[str, Any]:
    case = base_case(test_id, prompt, "legacy_planner", "legacy")
    case.update(
        {
            "lane": "near_miss",
            "expected_routing_engine": "legacy_planner",
            "expected_result_states": {"dry_run_ready"},
            "expected_binding_statuses": {"available", "missing"},
            "expected_generic_provider_allowed": True,
            "expected_legacy_fallback_used": True,
        }
    )
    return case


def browser_confident(test_id: str, prompt: str) -> dict[str, Any]:
    case = base_case(test_id, prompt, "browser_destination", "browser")
    case["lane"] = "regression_canary"
    return case


def selected_context() -> dict[str, Any]:
    return {"selection": {"kind": "text", "preview": "Selected launch notes", "value": "Selected launch notes"}}


def trust_state() -> dict[str, Any]:
    return {
        "family": "software_control",
        "subject": "firefox",
        "parameters": {"operation_type": "install", "request_stage": "awaiting_confirmation", "target_name": "firefox"},
        "trust": {"request_id": "trust-eval-1", "reason": "Installing software changes the machine."},
    }


def integration_cases() -> list[CommandEvalCase]:
    return [
        _case(
            "ambiguous_deictic_no_owner_selection",
            "use this for that",
            "context_clarification",
            "context",
            (),
            input_context=selected_context(),
            clarification="expected",
        ),
        _case("ambiguous_followup_no_owner", "do the same thing as before", "context_clarification", "context", (), clarification="expected"),
        _case(
            "ambiguous_prior_browser_owner",
            "use this for that",
            "browser_destination",
            "browser",
            (),
            active_request_state={"family": "browser_destination", "subject": "browser destination", "parameters": {"request_stage": "preview"}},
            clarification="expected",
            approval="allowed",
        ),
        _case(
            "ambiguous_prior_app_owner",
            "use this for that",
            "app_control",
            "system",
            ("active_apps",),
            active_request_state={"family": "app_control", "subject": "active apps", "parameters": {"source_case": "active_apps", "request_stage": "preview"}},
            clarification="allowed",
        ),
        _case("ambiguous_discord_missing", "send this to Baby", "discord_relay", "discord_relay", (), clarification="expected", approval="allowed"),
        _case("ambiguous_routine_missing", "save this as a routine", "routine", "routine", (), clarification="expected", approval="allowed"),
        _case("ambiguous_conceptual_near_miss", "what is this architecture concept", "generic_provider", "provider", (), clarification="allowed"),
        _case("ambiguous_confident_url", "open https://example.com", "browser_destination", "browser", ("external_open_url",), approval="allowed"),
        _case(
            "ambiguous_trust_pending_deictic",
            "use this for that",
            "trust_approvals",
            "trust",
            (),
            active_request_state=trust_state(),
            input_context=selected_context(),
            clarification="allowed",
            approval="allowed",
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
        tags=("ambiguous_deictic_clarification",),
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


if __name__ == "__main__":
    main()
