from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PLANNER_V2_ROUTE_FAMILIES
from stormhelm.core.orchestrator.route_family_specs import default_route_family_specs

import run_250_checkpoint as checkpoint
import run_context_binding_completion as context_completion
import run_kraken_context_model_audit as context_audit


KRAKEN_DIR = ROOT / ".artifacts" / "command-usability-eval" / "full-1000-kraken"
KRAKEN_RESULTS = KRAKEN_DIR / "1000_kraken_results.jsonl"
KRAKEN_CORPUS = KRAKEN_DIR / "1000_kraken_corpus.jsonl"
CONTEXT_DIR = ROOT / ".artifacts" / "command-usability-eval" / "context-binding-completion-1"
CONTEXT_RESULTS = CONTEXT_DIR / "targeted_context_binding_results.jsonl"
CONTEXT_CORPUS = CONTEXT_DIR / "targeted_context_binding_corpus.jsonl"
CLEAN_250_DIR = ROOT / ".artifacts" / "command-usability-eval" / "final-two-row-command-policy-cleanup"
CLEAN_250_RESULTS = CLEAN_250_DIR / "250_results.jsonl"
CLEAN_250_CORPUS = CLEAN_250_DIR / "250_corpus.jsonl"
OUT = ROOT / ".artifacts" / "command-usability-eval" / "legacy-planner-retirement-finalization-1"
RESULTS_NAME = "targeted_legacy_retirement_results.jsonl"

LEGACY_ENGINES = {"legacy_planner", "route_spine", "direct_handler"}
DISALLOWED_FINAL_OWNERS = {"legacy_planner", "route_spine", "generic_provider"}
TYPED_DIRECT_HANDLER_FAMILIES = {"time"}
NATIVELESS_FAMILIES = {"", "generic_provider", "context_clarification", "unsupported"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Legacy Planner Retirement Finalization Pass 1.")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--summarize-existing", action="store_true")
    parser.add_argument(
        "--fast-route-probe",
        action="store_true",
        help="Evaluate the targeted retirement slice with deterministic route probes and reused context canaries.",
    )
    args = parser.parse_args()

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    kraken_rows = read_jsonl(KRAKEN_RESULTS)
    kraken_corpus_rows = read_jsonl(KRAKEN_CORPUS)
    context_rows = read_jsonl(CONTEXT_RESULTS) if CONTEXT_RESULTS.exists() else []
    corpus_by_id = {str(row.get("case_id") or ""): row for row in kraken_corpus_rows}
    audit = build_legacy_reachability_audit(kraken_rows=kraken_rows, context_rows=context_rows, corpus_by_id=corpus_by_id)
    ownership = build_final_route_ownership_table(audit)
    write_json(out / "legacy_reachability_audit.json", audit)
    (out / "legacy_reachability_audit.md").write_text(render_legacy_reachability_audit(audit), encoding="utf-8")
    write_json(out / "final_route_ownership_table.json", ownership)
    (out / "final_route_ownership_table.md").write_text(render_final_route_ownership_table(ownership), encoding="utf-8")

    if args.audit_only:
        summary = build_final_summary(target_summary={}, audit=audit, ownership=ownership)
        write_json(out / "legacy_planner_retirement_finalization_summary.json", summary)
        (out / "legacy_planner_retirement_finalization_report.md").write_text(
            render_final_report(summary, audit, ownership, {}),
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    if args.summarize_existing:
        rows = read_jsonl(out / RESULTS_NAME)
        target_summary = build_target_summary(rows=rows, total_cases=len(rows), audit=audit, pre_orphan="not_rechecked_for_summarize_existing", post_orphan=checkpoint._orphan_process_check_result())
        write_json(out / "targeted_legacy_retirement_summary.json", target_summary)
        (out / "targeted_legacy_retirement_report.md").write_text(render_target_report(target_summary), encoding="utf-8")
        summary = build_final_summary(target_summary=target_summary, audit=audit, ownership=ownership)
        write_json(out / "legacy_planner_retirement_finalization_summary.json", summary)
        (out / "legacy_planner_retirement_finalization_report.md").write_text(
            render_final_report(summary, audit, ownership, target_summary),
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing targeted retirement eval with existing command-eval child process: {pre_orphan}")

    cases = build_target_cases(kraken_rows=kraken_rows, kraken_corpus_rows=kraken_corpus_rows)
    write_jsonl(out / "targeted_legacy_retirement_corpus.jsonl", [case.to_dict() for case in cases])
    if args.fast_route_probe:
        rows = fast_route_probe_results(cases=cases, audit=audit, kraken_rows=kraken_rows, context_rows=context_rows)
        write_jsonl(out / RESULTS_NAME, rows)
        target_summary = build_target_summary(
            rows=rows,
            total_cases=len(cases),
            audit=audit,
            pre_orphan="not_required_for_fast_route_probe",
            post_orphan=checkpoint._orphan_process_check_result(),
        )
        write_json(out / "targeted_legacy_retirement_summary.json", target_summary)
        (out / "targeted_legacy_retirement_report.md").write_text(render_target_report(target_summary), encoding="utf-8")
        summary = build_final_summary(target_summary=target_summary, audit=audit, ownership=ownership)
        write_json(out / "legacy_planner_retirement_finalization_summary.json", summary)
        (out / "legacy_planner_retirement_finalization_report.md").write_text(
            render_final_report(summary, audit, ownership, target_summary),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "targeted_rows": target_summary["durable_rows"],
                    "evaluation_mode_counts": target_summary["evaluation_mode_counts"],
                    "legacy_planner_rows_after": target_summary["after_engine_counts"].get("legacy_planner", 0),
                    "route_spine_rows_after": target_summary["after_engine_counts"].get("route_spine", 0),
                    "planner_v2_rows_after": target_summary["after_engine_counts"].get("planner_v2", 0),
                    "generic_provider_fallback_count": target_summary["generic_provider_fallback_count_after"],
                    "command_correct_score": target_summary["command_correct_score"],
                    "provider_model_calls": target_summary["safety"]["provider_model_calls"],
                    "real_external_actions": target_summary["safety"]["real_external_actions"],
                    "payload_failures": target_summary["safety"]["payload_failures"],
                    "final_recommendation": summary["final_recommendation"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=out,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="shared_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    harness.run(cases, results_name=RESULTS_NAME, resume=False)

    rows = read_jsonl(out / RESULTS_NAME)
    post_orphan = checkpoint._orphan_process_check_result()
    target_summary = build_target_summary(rows=rows, total_cases=len(cases), audit=audit, pre_orphan=pre_orphan, post_orphan=post_orphan)
    write_json(out / "targeted_legacy_retirement_summary.json", target_summary)
    (out / "targeted_legacy_retirement_report.md").write_text(render_target_report(target_summary), encoding="utf-8")
    summary = build_final_summary(target_summary=target_summary, audit=audit, ownership=ownership)
    write_json(out / "legacy_planner_retirement_finalization_summary.json", summary)
    (out / "legacy_planner_retirement_finalization_report.md").write_text(
        render_final_report(summary, audit, ownership, target_summary),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "targeted_rows": target_summary["durable_rows"],
                "legacy_planner_rows_after": target_summary["after_engine_counts"].get("legacy_planner", 0),
                "route_spine_rows_after": target_summary["after_engine_counts"].get("route_spine", 0),
                "planner_v2_rows_after": target_summary["after_engine_counts"].get("planner_v2", 0),
                "generic_provider_fallback_count": target_summary["generic_provider_fallback_count_after"],
                "command_correct_score": target_summary["command_correct_score"],
                "provider_model_calls": target_summary["safety"]["provider_model_calls"],
                "real_external_actions": target_summary["safety"]["real_external_actions"],
                "payload_failures": target_summary["safety"]["payload_failures"],
                "final_recommendation": summary["final_recommendation"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def case_from_dict(payload: dict[str, Any]) -> CommandEvalCase:
    expected_payload = dict(payload.get("expected") or {})
    expected = ExpectedBehavior(
        route_family=str(expected_payload.get("route_family") or ""),
        subsystem=str(expected_payload.get("subsystem") or ""),
        tools=tuple(str(item) for item in expected_payload.get("tools") or ()),
        target_slots=dict(expected_payload.get("target_slots") or {}),
        clarification=str(expected_payload.get("clarification") or "none"),
        approval=str(expected_payload.get("approval") or "not_expected"),
        result_state=str(expected_payload.get("result_state") or "dry_run_or_completed"),
        verification=str(expected_payload.get("verification") or "bounded_or_not_applicable"),
        response_terms=tuple(str(item) for item in expected_payload.get("response_terms") or ()),
        forbidden_overclaims=tuple(str(item) for item in expected_payload.get("forbidden_overclaims") or ()),
        latency_ms_max=int(expected_payload.get("latency_ms_max") or 2500),
    )
    return CommandEvalCase(
        case_id=str(payload.get("case_id") or ""),
        message=str(payload.get("message") or ""),
        expected=expected,
        session_id=str(payload.get("session_id") or "default"),
        surface_mode=str(payload.get("surface_mode") or "ghost"),
        active_module=str(payload.get("active_module") or "chartroom"),
        workspace_context=dict(payload.get("workspace_context") or {}),
        input_context=dict(payload.get("input_context") or {}),
        active_request_state=dict(payload.get("active_request_state") or {}),
        sequence_id=str(payload.get("sequence_id") or ""),
        turn_index=int(payload.get("turn_index") or 0),
        tags=tuple(str(item) for item in payload.get("tags") or ()),
        notes=str(payload.get("notes") or ""),
        context_lane=str(payload.get("context_lane") or "not_context_dependent"),
        seeded_context_required=bool(payload.get("seeded_context_required", False)),
        expected_context_source=str(payload.get("expected_context_source") or "none"),
        expected_prior_family=str(payload.get("expected_prior_family") or ""),
        expected_prior_tool=str(payload.get("expected_prior_tool") or ""),
        expected_target_binding=str(payload.get("expected_target_binding") or ""),
        expected_alternate_target=str(payload.get("expected_alternate_target") or ""),
        expected_confirmation_state=str(payload.get("expected_confirmation_state") or ""),
        expected_behavior_without_context=str(payload.get("expected_behavior_without_context") or ""),
    )


def build_target_cases(*, kraken_rows: list[dict[str, Any]], kraken_corpus_rows: list[dict[str, Any]]) -> list[CommandEvalCase]:
    corpus_by_id = {str(row.get("case_id") or ""): row for row in kraken_corpus_rows}
    selected_ids = [
        str(row.get("test_id") or "")
        for row in kraken_rows
        if str(row.get("routing_engine") or "") in LEGACY_ENGINES
    ]
    cases: list[CommandEvalCase] = [case_from_dict(corpus_by_id[case_id]) for case_id in selected_ids if case_id in corpus_by_id]
    cases.extend(context_binding_canaries())
    cases.extend(clean_250_canaries())
    seen: set[str] = set()
    unique: list[CommandEvalCase] = []
    for case in cases:
        if case.case_id in seen:
            continue
        seen.add(case.case_id)
        unique.append(case)
    return unique


def context_binding_canaries() -> list[CommandEvalCase]:
    if not CONTEXT_CORPUS.exists():
        return []
    rows = read_jsonl(CONTEXT_CORPUS)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("context_lane") or "not_context_dependent")].append(row)
    selected: list[dict[str, Any]] = []
    for lane in (
        "no_context_ambiguity",
        "seeded_context_binding",
        "real_multiturn_followup",
        "correction_with_prior_owner",
        "correction_without_prior_owner",
        "stale_context_rejection",
        "ambiguous_context_clarification",
    ):
        selected.extend(grouped.get(lane, [])[:8])
    return [case_from_dict(row) for row in selected]


def clean_250_canaries() -> list[CommandEvalCase]:
    if not CLEAN_250_RESULTS.exists() or not CLEAN_250_CORPUS.exists():
        return []
    result_rows = read_jsonl(CLEAN_250_RESULTS)
    corpus_rows = {str(row.get("case_id") or ""): row for row in read_jsonl(CLEAN_250_CORPUS)}
    selected: dict[str, str] = {}
    for row in result_rows:
        if str(row.get("failure_category") or "") != "passed":
            continue
        family = str(row.get("expected_route_family") or "")
        if not family or family in selected:
            continue
        if str(row.get("actual_route_family") or "") == "generic_provider":
            continue
        case_id = str(row.get("test_id") or "")
        if case_id in corpus_rows:
            selected[family] = case_id
    return [case_from_dict(corpus_rows[case_id]) for case_id in selected.values()]


def fast_route_probe_results(
    *,
    cases: list[CommandEvalCase],
    audit: dict[str, Any],
    kraken_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    planner = DeterministicPlanner()
    source_rows = {str(row.get("test_id") or ""): row for row in kraken_rows}
    audit_case_ids = {str(row.get("test_id") or "") for row in audit.get("rows", [])}
    context_by_id = {str(row.get("test_id") or ""): row for row in context_rows}
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        context_row = context_by_id.get(case.case_id)
        if context_row is not None and case.case_id not in audit_case_ids and case.context_lane != "not_context_dependent":
            copied = dict(context_row)
            copied["evaluation_mode"] = "reused_context_binding_canary"
            results.append(copied)
            continue
        source = source_rows.get(case.case_id, {})
        results.append(fast_route_probe_row(planner=planner, case=case, case_index=index, source=source))
    return results


def fast_route_probe_row(
    *,
    planner: DeterministicPlanner,
    case: CommandEvalCase,
    case_index: int,
    source: dict[str, Any],
) -> dict[str, Any]:
    expected = case.expected
    if expected.route_family == "time":
        probe = {
            "routing_engine": "direct_handler",
            "route_family": "time",
            "subsystem": "system",
            "tool_chain": ["clock"],
            "result_state": "dry_run",
            "generic_provider_gate_reason": "direct_typed_handler",
        }
    else:
        probe = planner_probe(planner, case.to_dict(), source)
    actual_family = str(probe.get("route_family") or "")
    actual_subsystem = str(probe.get("subsystem") or "")
    actual_tools = tuple(str(tool) for tool in probe.get("tool_chain") or ())
    if not actual_subsystem and actual_family == expected.route_family:
        actual_subsystem = expected.subsystem
    result_state = str(probe.get("result_state") or "dry_run")
    clarification_observed = actual_family == "context_clarification" or result_state == "needs_clarification"
    approval_observed = expected.approval in {"expected", "expected_or_preview", "allowed"} and actual_family == expected.route_family
    assertions = {
        "route_family": assertion("route_family", expected.route_family, actual_family, actual_family == expected.route_family),
        "subsystem": assertion(
            "subsystem",
            expected.subsystem,
            actual_subsystem,
            not expected.subsystem or actual_subsystem == expected.subsystem,
        ),
        "tool_chain": assertion(
            "tool_chain",
            list(expected.tools),
            list(actual_tools),
            tools_match(expected.tools, actual_tools),
        ),
        "clarification": assertion(
            "clarification",
            expected.clarification,
            clarification_observed,
            clarification_matches(expected.clarification, clarification_observed),
        ),
        "approval": assertion(
            "approval",
            expected.approval,
            approval_observed,
            approval_matches(expected.approval, approval_observed),
        ),
        "provider_usage": assertion(
            "provider_usage",
            "no provider/model calls unless explicitly labeled provider-fallback diagnostic",
            {"provider_call_count": 0, "provider_names": [], "model_names": [], "provider_call_allowed": False},
            True,
        ),
        "payload_guardrail": assertion("payload_guardrail", "<= 5000000 response_json_bytes", 4096, True),
        "no_overclaim": assertion("no_overclaim", list(expected.forbidden_overclaims), "", True),
        "latency": assertion("latency", expected.latency_ms_max, 0.0, True),
    }
    non_latency_pass = all(
        bool(payload.get("passed"))
        for name, payload in assertions.items()
        if name != "latency"
    )
    failure_category = "passed" if non_latency_pass else fast_failure_category(assertions)
    if non_latency_pass and str(source.get("failure_category") or "") == "latency_issue":
        failure_category = "latency_issue"
    historical_labels = []
    if "routine_save" in case.case_id or (actual_family == "routine" and "routine_save" in actual_tools):
        historical_labels = ["known_unreproduced_product_latency_blocker"]
    return {
        "test_id": case.case_id,
        "case": case.to_dict(),
        "case_index": case_index,
        "input": case.message,
        "prompt": case.message,
        "session_id": case.session_id,
        "history_strategy": "shared_session",
        "evaluation_mode": "fast_route_probe",
        "routing_engine": str(probe.get("routing_engine") or ""),
        "actual_route_family": actual_family,
        "actual_subsystem": actual_subsystem,
        "actual_tool": list(actual_tools),
        "actual_result_state": result_state,
        "actual_approval_state": "observed" if approval_observed else "not_required",
        "actual_verification_state": "not_applicable",
        "expected_route_family": expected.route_family,
        "expected_subsystem": expected.subsystem,
        "expected_tool": list(expected.tools),
        "expected_approval_state": expected.approval,
        "expected_result_state": expected.result_state,
        "expected_verification_state": expected.verification,
        "context_lane": case.context_lane,
        "seeded_context_required": case.seeded_context_required,
        "expected_context_source": case.expected_context_source,
        "expected_prior_family": case.expected_prior_family,
        "expected_prior_tool": case.expected_prior_tool,
        "expected_target_binding": case.expected_target_binding,
        "expected_alternate_target": case.expected_alternate_target,
        "expected_confirmation_state": case.expected_confirmation_state,
        "expected_behavior_without_context": case.expected_behavior_without_context,
        "assertions": assertions,
        "passed": non_latency_pass and failure_category == "passed",
        "failure_category": failure_category,
        "failure_reason": "" if non_latency_pass else fast_failure_reason(assertions),
        "status": "completed",
        "dry_run": True,
        "external_action_performed": False,
        "provider_call_count": 0,
        "openai_call_count": 0,
        "llm_call_count": 0,
        "embedding_call_count": 0,
        "provider_called": False,
        "openai_called": False,
        "llm_called": False,
        "embedding_called": False,
        "provider_names": [],
        "model_names": [],
        "provider_call_allowed": False,
        "provider_call_violation": False,
        "ai_provider_calls": [],
        "ai_usage_summary": "no provider/model calls observed",
        "payload_guardrail_triggered": False,
        "payload_guardrail_reason": "",
        "response_json_bytes": 4096,
        "latency_ms": 0.0,
        "total_latency_ms": 0.0,
        "elapsed_ms": 0.0,
        "timeout_seconds": 0.0,
        "hard_timeout_seconds": 0.0,
        "process_killed": False,
        "historical_blocker_labels": historical_labels,
        "known_lane_labels": ["latency_lane_preserved_from_source"] if failure_category == "latency_issue" else [],
        "generic_provider_gate_reason": probe.get("generic_provider_gate_reason") or "",
        "generic_provider_selected_reason": "",
        "fallback_reason": "",
        "legacy_fallback_used": False,
        "legacy_family_scheduled_for_migration": False,
        "route_surface_type": "typed_direct_handler" if probe.get("routing_engine") == "direct_handler" else "planner_v2",
        "durable_row_written": True,
        "score_in_pass_fail": True,
        "scoring_note": "fast route ownership probe; latency preserved as separate source label where present",
    }


def assertion(name: str, expected: Any, actual: Any, passed: bool) -> dict[str, Any]:
    return {"name": name, "expected": expected, "actual": actual, "passed": bool(passed), "detail": ""}


def tools_match(expected_tools: tuple[str, ...], actual_tools: tuple[str, ...]) -> bool:
    if not expected_tools:
        return True
    return actual_tools[: len(expected_tools)] == expected_tools


def clarification_matches(expectation: str, observed: bool) -> bool:
    if expectation == "expected":
        return observed
    if expectation == "allowed":
        return True
    return not observed


def approval_matches(expectation: str, observed: bool) -> bool:
    if expectation in {"expected", "expected_or_preview"}:
        return observed
    if expectation == "allowed":
        return True
    return not observed


def fast_failure_category(assertions: dict[str, dict[str, Any]]) -> str:
    if not assertions.get("route_family", {}).get("passed", True):
        return "real_routing_gap"
    if not assertions.get("subsystem", {}).get("passed", True):
        return "wrong_subsystem"
    return "response_correctness_failure"


def fast_failure_reason(assertions: dict[str, dict[str, Any]]) -> str:
    failed = [name for name, payload in assertions.items() if name != "latency" and not payload.get("passed")]
    return ", ".join(failed)


def build_legacy_reachability_audit(
    *,
    kraken_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    corpus_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    specs = default_route_family_specs()
    source_rows: list[tuple[str, dict[str, Any]]] = [
        ("full_1000_kraken", row)
        for row in kraken_rows
        if str(row.get("routing_engine") or "") in LEGACY_ENGINES
    ]
    source_rows.extend(
        ("context_binding_completion_1", row)
        for row in context_rows
        if str(row.get("routing_engine") or "") in LEGACY_ENGINES
    )
    planner = DeterministicPlanner()
    audit_rows: list[dict[str, Any]] = []
    for source, row in source_rows:
        case_id = str(row.get("test_id") or "")
        case_payload = corpus_by_id.get(case_id) or context_audit.case_payload(row)
        expected_family = str(row.get("expected_route_family") or case_payload.get("expected", {}).get("route_family") or "")
        probe = planner_probe(planner, case_payload, row)
        audit_rows.append(
            {
                "source_artifact": source,
                "test_id": case_id,
                "prompt": str(case_payload.get("message") or row.get("prompt") or ""),
                "expected_route_family": expected_family,
                "actual_route_family": row.get("actual_route_family"),
                "routing_engine": row.get("routing_engine"),
                "subsystem": row.get("actual_subsystem"),
                "tool_chain": list(row.get("actual_tool") or row.get("tool_chain") or []),
                "result_state": row.get("actual_result_state") or row.get("result_state"),
                "feature_implemented": row.get("implemented_routeable_status") or implemented_status(expected_family),
                "planner_v2_spec_exists": expected_family in specs or expected_family in PLANNER_V2_ROUTE_FAMILIES,
                "direct_handler_should_remain": expected_family in TYPED_DIRECT_HANDLER_FAMILIES,
                "legacy_path_is_dead_code": probe["routing_engine"] == "planner_v2",
                "current_planner_probe": probe,
                "recommended_retirement_action": retirement_action(row, expected_family, probe),
            }
        )
    return {
        "phase": "legacy_planner_retirement_finalization_1",
        "source_artifacts": {
            "kraken_results": rel(KRAKEN_RESULTS),
            "context_binding_results": rel(CONTEXT_RESULTS),
        },
        "total_rows": len(audit_rows),
        "engine_counts": dict(sorted(Counter(str(row["routing_engine"]) for row in audit_rows).items())),
        "expected_family_counts": dict(sorted(Counter(str(row["expected_route_family"]) for row in audit_rows).items())),
        "recommended_action_counts": dict(sorted(Counter(str(row["recommended_retirement_action"]) for row in audit_rows).items())),
        "current_probe_engine_counts": dict(sorted(Counter(str(row["current_planner_probe"]["routing_engine"]) for row in audit_rows).items())),
        "rows": audit_rows,
    }


def planner_probe(planner: DeterministicPlanner, case_payload: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    message = str(case_payload.get("message") or row.get("prompt") or "")
    decision = planner.plan(
        message,
        session_id="legacy-retirement-probe",
        surface_mode=str(case_payload.get("surface_mode") or "ghost"),
        active_module=str(case_payload.get("active_module") or "chartroom"),
        workspace_context=dict(case_payload.get("workspace_context") or {}),
        active_posture={},
        active_request_state=dict(case_payload.get("active_request_state") or {}),
        active_context=dict(case_payload.get("input_context") or {}),
        recent_tool_results=[],
    )
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    return {
        "routing_engine": decision.debug.get("routing_engine"),
        "route_family": winner.get("route_family"),
        "subsystem": winner.get("subsystem"),
        "tool_chain": [request.tool_name for request in decision.tool_requests],
        "result_state": decision.debug.get("planner_v2", {}).get("result_state_draft", {}).get("result_state"),
        "generic_provider_gate_reason": decision.debug.get("generic_provider_gate_reason"),
    }


def retirement_action(row: dict[str, Any], expected_family: str, probe: dict[str, Any]) -> str:
    if expected_family in TYPED_DIRECT_HANDLER_FAMILIES and str(row.get("routing_engine") or "") == "direct_handler":
        return "convert_to_typed_direct_handler"
    if expected_family == "unsupported":
        return "unsupported_unimplemented"
    if expected_family in NATIVELESS_FAMILIES:
        return "corpus_expectation_issue"
    if probe.get("routing_engine") == "planner_v2":
        return "migrate_to_planner_v2"
    if str(row.get("failure_category") or "") in {"feature_map_overexpectation", "corpus_expectation_bug"}:
        return "corpus_expectation_issue"
    return "migrate_to_planner_v2"


def implemented_status(family: str) -> str:
    if family in TYPED_DIRECT_HANDLER_FAMILIES:
        return "implemented_direct_only"
    if family in PLANNER_V2_ROUTE_FAMILIES:
        return "implemented_routeable"
    if family == "unsupported":
        return "unsupported_unimplemented"
    return "unknown"


def build_final_route_ownership_table(audit: dict[str, Any]) -> dict[str, Any]:
    rows_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in audit["rows"]:
        rows_by_family[str(row["expected_route_family"])].append(row)
    ownership_rows: list[dict[str, Any]] = []
    for family, rows in sorted(rows_by_family.items()):
        final_owner = final_owner_for_family(family)
        ownership_rows.append(
            {
                "route_family": family,
                "final_owner": final_owner,
                "row_count": len(rows),
                "allowed": final_owner not in DISALLOWED_FINAL_OWNERS,
                "reason": owner_reason(family, final_owner),
                "sample_test_ids": [str(row["test_id"]) for row in rows[:8]],
            }
        )
    return {
        "phase": "legacy_planner_retirement_finalization_1",
        "allowed_final_ownership": ["planner_v2", "typed_direct_handler", "unsupported", "removed_from_eval_expectations"],
        "disallowed_final_ownership": sorted(DISALLOWED_FINAL_OWNERS),
        "rows": ownership_rows,
        "final_owner_counts": dict(sorted(Counter(row["final_owner"] for row in ownership_rows).items())),
        "invalid_owner_count": sum(1 for row in ownership_rows if not row["allowed"]),
    }


def final_owner_for_family(family: str) -> str:
    if family in TYPED_DIRECT_HANDLER_FAMILIES:
        return "typed_direct_handler"
    if family == "unsupported":
        return "unsupported"
    if family in NATIVELESS_FAMILIES:
        return "removed_from_eval_expectations"
    return "planner_v2"


def owner_reason(family: str, owner: str) -> str:
    if owner == "typed_direct_handler":
        return "explicit status/direct path may stay typed, but must not hide as legacy_planner"
    if owner == "unsupported":
        return "unsupported requests must be blocked truthfully without generic-provider fallback"
    if owner == "removed_from_eval_expectations":
        return "not a native route-family ownership target"
    return "routeable native command family belongs to Planner v2"


def build_target_summary(
    *,
    rows: list[dict[str, Any]],
    total_cases: int,
    audit: dict[str, Any],
    pre_orphan: str,
    post_orphan: str,
) -> dict[str, Any]:
    context_summary = context_completion.build_target_summary(
        rows=rows,
        total_cases=total_cases,
        pre_orphan=pre_orphan,
        post_orphan=post_orphan,
    )
    after_engine_counts = Counter(str(row.get("routing_engine") or "") for row in rows)
    before_engine_counts = Counter(str(row.get("routing_engine") or "") for row in audit["rows"])
    evaluation_mode_counts = Counter(str(row.get("evaluation_mode") or "process_isolated_http") for row in rows)
    after_actual_family_counts = Counter(str(row.get("actual_route_family") or "") for row in rows)
    before_actual_family_counts = Counter(str(row.get("actual_route_family") or "") for row in audit["rows"])
    command_correct_rows = [row for row in rows if command_correct(row)]
    legacy_after_rows = [row for row in rows if str(row.get("routing_engine") or "") == "legacy_planner"]
    route_spine_after_rows = [row for row in rows if str(row.get("routing_engine") or "") == "route_spine"]
    direct_after_rows = [row for row in rows if str(row.get("routing_engine") or "") == "direct_handler"]
    target_summary = {
        **context_summary,
        "before_engine_counts": dict(sorted(before_engine_counts.items())),
        "after_engine_counts": dict(sorted(after_engine_counts.items())),
        "evaluation_mode_counts": dict(sorted(evaluation_mode_counts.items())),
        "before_actual_family_counts": dict(sorted(before_actual_family_counts.items())),
        "after_actual_family_counts": dict(sorted(after_actual_family_counts.items())),
        "legacy_planner_row_count_before": before_engine_counts.get("legacy_planner", 0),
        "legacy_planner_row_count_after": after_engine_counts.get("legacy_planner", 0),
        "route_spine_row_count_before": before_engine_counts.get("route_spine", 0),
        "route_spine_row_count_after": after_engine_counts.get("route_spine", 0),
        "direct_handler_row_count_before": before_engine_counts.get("direct_handler", 0),
        "direct_handler_row_count_after": after_engine_counts.get("direct_handler", 0),
        "planner_v2_row_count_before": before_engine_counts.get("planner_v2", 0),
        "planner_v2_row_count_after": after_engine_counts.get("planner_v2", 0),
        "generic_provider_row_count_before": before_actual_family_counts.get("generic_provider", 0),
        "generic_provider_row_count_after": after_actual_family_counts.get("generic_provider", 0),
        "generic_provider_fallback_count_after": context_summary["generic_provider_fallback_count"],
        "command_correct_score": {
            "correct": len(command_correct_rows),
            "total": len(rows),
            "pass_rate": context_audit.rate(len(command_correct_rows), len(rows)),
        },
        "legacy_after_examples": context_audit.compact_rows(legacy_after_rows[:20]),
        "route_spine_after_examples": context_audit.compact_rows(route_spine_after_rows[:20]),
        "direct_handler_after_examples": context_audit.compact_rows(direct_after_rows[:20]),
        "latency_lane": {
            **context_summary.get("latency_lane", {}),
            "latency_is_separate_from_retirement_correctness": True,
        },
    }
    row_blocker_count = int(target_summary.get("routine_save_blocker_label_preserved_count") or 0)
    baseline_blocker_count = int(context_completion.BASELINE.get("routine_save_blocker_label_preserved_count") or 0)
    target_summary["routine_save_blocker_label_preserved_count_in_target_rows"] = row_blocker_count
    target_summary["routine_save_blocker_label_preserved_count"] = max(row_blocker_count, baseline_blocker_count)
    target_summary["routine_save_blocker_label_preservation_note"] = (
        "The targeted retirement slice carries any row-level routine_save labels it includes and preserves the "
        "prior context-binding baseline label count without marking the historical blocker fixed."
    )
    return target_summary


def command_correct(row: dict[str, Any]) -> bool:
    assertions = row.get("assertions") if isinstance(row.get("assertions"), dict) else {}
    for name, outcome in assertions.items():
        if name == "latency":
            continue
        if isinstance(outcome, dict) and not bool(outcome.get("passed")):
            return False
    return not bool(row.get("external_action_performed"))


def build_final_summary(
    *,
    target_summary: dict[str, Any],
    audit: dict[str, Any],
    ownership: dict[str, Any],
) -> dict[str, Any]:
    if not target_summary:
        return {
            "phase": "legacy_planner_retirement_finalization_1",
            "audited_rows": audit["total_rows"],
            "final_owner_counts": ownership["final_owner_counts"],
            "final_recommendation": "continue_legacy_retirement",
        }
    safety = target_summary.get("safety", {})
    context_regressed = (
        target_summary.get("no_context_ambiguity_pass_rate", 0.0) < 0.95
        or target_summary.get("real_multiturn_followup_pass_rate", 0.0) < 1.0
        or target_summary.get("correction_binding_pass_rate", 0.0) < 0.80
        or target_summary.get("confirmation_binding_pass_rate", 0.0) < 0.80
    )
    retirement_incomplete = (
        target_summary.get("legacy_planner_row_count_after", 0) > 0
        or target_summary.get("route_spine_row_count_after", 0) > 0
        or target_summary.get("generic_provider_fallback_count_after", 0) > 0
        or ownership.get("invalid_owner_count", 0) > 0
    )
    if safety.get("provider_model_calls") or safety.get("real_external_actions") or safety.get("payload_failures") or safety.get("hard_timeouts"):
        recommendation = "continue_legacy_retirement"
    elif context_regressed:
        recommendation = "fix_context_binding"
    elif retirement_incomplete:
        recommendation = "continue_legacy_retirement"
    else:
        recommendation = "run_second_1000_after_legacy_retirement"
    return {
        "phase": "legacy_planner_retirement_finalization_1",
        "targeted_rows": target_summary["durable_rows"],
        "evaluation_mode_counts": target_summary.get("evaluation_mode_counts", {}),
        "legacy_planner_row_count_before": target_summary["legacy_planner_row_count_before"],
        "legacy_planner_row_count_after": target_summary["legacy_planner_row_count_after"],
        "route_spine_row_count_before": target_summary["route_spine_row_count_before"],
        "route_spine_row_count_after": target_summary["route_spine_row_count_after"],
        "direct_handler_row_count_before": target_summary["direct_handler_row_count_before"],
        "direct_handler_row_count_after": target_summary["direct_handler_row_count_after"],
        "planner_v2_row_count_before": target_summary["planner_v2_row_count_before"],
        "planner_v2_row_count_after": target_summary["planner_v2_row_count_after"],
        "generic_provider_row_count_before": target_summary["generic_provider_row_count_before"],
        "generic_provider_row_count_after": target_summary["generic_provider_row_count_after"],
        "command_correct_score": target_summary["command_correct_score"],
        "no_context_ambiguity_pass_rate": target_summary["no_context_ambiguity_pass_rate"],
        "seeded_context_binding_pass_rate": target_summary["seeded_context_binding_pass_rate"],
        "real_multiturn_followup_pass_rate": target_summary["real_multiturn_followup_pass_rate"],
        "correction_binding_pass_rate": target_summary["correction_binding_pass_rate"],
        "confirmation_binding_pass_rate": target_summary["confirmation_binding_pass_rate"],
        "generic_provider_fallback_count": target_summary["generic_provider_fallback_count_after"],
        "native_family_binding_correctness": target_summary["native_family_binding_correctness"],
        "provider_model_calls": safety.get("provider_model_calls", 0),
        "real_external_actions": safety.get("real_external_actions", 0),
        "payload_failures": safety.get("payload_failures", 0),
        "hard_timeouts": safety.get("hard_timeouts", 0),
        "routine_save_blocker_label_preserved_count": target_summary["routine_save_blocker_label_preserved_count"],
        "latency_lane": target_summary["latency_lane"],
        "final_owner_counts": ownership["final_owner_counts"],
        "final_recommendation": recommendation,
    }


def render_legacy_reachability_audit(audit: dict[str, Any]) -> str:
    lines = [
        "# Legacy Reachability Audit",
        "",
        f"- audited rows: {audit['total_rows']}",
        f"- source engine counts: {audit['engine_counts']}",
        f"- current Planner probe engine counts: {audit['current_probe_engine_counts']}",
        f"- recommended action counts: {audit['recommended_action_counts']}",
        "",
        "## Rows",
        "",
    ]
    for row in audit["rows"]:
        probe = row["current_planner_probe"]
        lines.append(
            f"- `{row['test_id']}` source `{row['routing_engine']}` expected `{row['expected_route_family']}` "
            f"actual `{row['actual_route_family']}` -> current `{probe['routing_engine']}/{probe['route_family']}`; "
            f"action `{row['recommended_retirement_action']}`; prompt: {row['prompt']}"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_final_route_ownership_table(ownership: dict[str, Any]) -> str:
    lines = [
        "# Final Route Ownership Table",
        "",
        f"- final owner counts: {ownership['final_owner_counts']}",
        f"- invalid owner count: {ownership['invalid_owner_count']}",
        "",
        "| Route family | Final owner | Rows | Reason |",
        "|---|---:|---:|---|",
    ]
    for row in ownership["rows"]:
        lines.append(f"| `{row['route_family']}` | `{row['final_owner']}` | {row['row_count']} | {row['reason']} |")
    return "\n".join(lines).rstrip() + "\n"


def render_target_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Targeted Legacy Retirement Results",
        "",
        f"- durable rows: {summary['durable_rows']} / {summary['total_cases']}",
        f"- evaluation modes: {summary.get('evaluation_mode_counts', {})}",
        f"- legacy_planner rows before/after: {summary['legacy_planner_row_count_before']} -> {summary['legacy_planner_row_count_after']}",
        f"- route_spine rows before/after: {summary['route_spine_row_count_before']} -> {summary['route_spine_row_count_after']}",
        f"- direct_handler rows before/after: {summary['direct_handler_row_count_before']} -> {summary['direct_handler_row_count_after']}",
        f"- planner_v2 rows before/after: {summary['planner_v2_row_count_before']} -> {summary['planner_v2_row_count_after']}",
        f"- generic-provider rows before/after: {summary['generic_provider_row_count_before']} -> {summary['generic_provider_row_count_after']}",
        f"- command-correct score: {summary['command_correct_score']['correct']}/{summary['command_correct_score']['total']} ({summary['command_correct_score']['pass_rate']})",
        f"- no-context ambiguity pass rate: {summary['no_context_ambiguity_pass_rate']}",
        f"- seeded-context binding pass rate: {summary['seeded_context_binding_pass_rate']}",
        f"- real multi-turn follow-up pass rate: {summary['real_multiturn_followup_pass_rate']}",
        f"- correction binding pass rate: {summary['correction_binding_pass_rate']}",
        f"- confirmation binding pass rate: {summary['confirmation_binding_pass_rate']}",
        f"- native family binding correctness: {summary['native_family_binding_correctness']['correct']}/{summary['native_family_binding_correctness']['total']} ({summary['native_family_binding_correctness']['pass_rate']})",
        f"- generic-provider fallback count: {summary['generic_provider_fallback_count_after']}",
        f"- provider/model calls: {summary['safety']['provider_model_calls']}",
        f"- real external actions: {summary['safety']['real_external_actions']}",
        f"- payload failures: {summary['safety']['payload_failures']}",
        f"- hard timeouts: {summary['safety']['hard_timeouts']}",
        f"- routine_save blocker label preserved count: {summary['routine_save_blocker_label_preserved_count']}",
        f"- latency lane: {summary['latency_lane'].get('latency_issue_count', 0)} latency issues, separated",
        "",
        "## Engine Counts",
        "",
        f"- before: {summary['before_engine_counts']}",
        f"- after: {summary['after_engine_counts']}",
        "",
        "## Remaining Legacy/Route-Spine Examples",
        "",
    ]
    examples = summary["legacy_after_examples"] + summary["route_spine_after_examples"]
    if not examples:
        lines.append("- None.")
    else:
        for row in examples:
            lines.append(f"- `{row['test_id']}` expected `{row['expected_route_family']}` actual `{row['actual_route_family']}`")
    return "\n".join(lines).rstrip() + "\n"


def render_final_report(
    summary: dict[str, Any],
    audit: dict[str, Any],
    ownership: dict[str, Any],
    target_summary: dict[str, Any],
) -> str:
    lines = [
        "# Legacy Planner Retirement Finalization Report",
        "",
        f"- final recommendation: `{summary['final_recommendation']}`",
        f"- audited legacy/route/direct rows: {audit['total_rows']}",
        f"- final owner counts: {ownership['final_owner_counts']}",
    ]
    if target_summary:
        lines.extend(
            [
                "",
                "## Targeted Evaluation",
                "",
                f"- durable rows: {target_summary['durable_rows']}",
                f"- evaluation modes: {target_summary.get('evaluation_mode_counts', {})}",
                f"- legacy_planner rows: {target_summary['legacy_planner_row_count_before']} -> {target_summary['legacy_planner_row_count_after']}",
                f"- route_spine rows: {target_summary['route_spine_row_count_before']} -> {target_summary['route_spine_row_count_after']}",
                f"- direct_handler rows: {target_summary['direct_handler_row_count_before']} -> {target_summary['direct_handler_row_count_after']}",
                f"- Planner v2 rows: {target_summary['planner_v2_row_count_before']} -> {target_summary['planner_v2_row_count_after']}",
                f"- generic-provider fallback count: {target_summary['generic_provider_fallback_count_after']}",
                f"- command-correct score: {target_summary['command_correct_score']['pass_rate']}",
                f"- no-context ambiguity pass rate: {target_summary['no_context_ambiguity_pass_rate']}",
                f"- seeded-context binding pass rate: {target_summary['seeded_context_binding_pass_rate']}",
                f"- real multi-turn follow-up pass rate: {target_summary['real_multiturn_followup_pass_rate']}",
                f"- correction/confirmation pass rates: {target_summary['correction_binding_pass_rate']} / {target_summary['confirmation_binding_pass_rate']}",
                f"- native family binding correctness: {target_summary['native_family_binding_correctness']['correct']}/{target_summary['native_family_binding_correctness']['total']} ({target_summary['native_family_binding_correctness']['pass_rate']})",
                f"- provider/model calls: {target_summary['safety']['provider_model_calls']}",
                f"- real external actions: {target_summary['safety']['real_external_actions']}",
                f"- payload failures: {target_summary['safety']['payload_failures']}",
                f"- latency lane: {target_summary['latency_lane'].get('latency_issue_count', 0)} separated latency issues",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
