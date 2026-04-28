from __future__ import annotations

import argparse
import json
import re
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

import run_250_checkpoint as checkpoint
import run_kraken_context_model_audit as context_audit
import run_real_multiturn_continuity_parity as multiturn


BASE_DIR = ROOT / ".artifacts" / "command-usability-eval" / "real-multiturn-continuity-parity-1"
BASE_RESULTS = BASE_DIR / "targeted_multiturn_results.jsonl"
KRAKEN_DIR = ROOT / ".artifacts" / "command-usability-eval" / "full-1000-kraken"
KRAKEN_RESULTS = KRAKEN_DIR / "1000_kraken_results.jsonl"
KRAKEN_CORPUS = KRAKEN_DIR / "1000_kraken_corpus.jsonl"
OUT = ROOT / ".artifacts" / "command-usability-eval" / "context-binding-completion-1"
RESULTS_NAME = "targeted_context_binding_results.jsonl"

BASELINE = {
    "targeted_rows": 365,
    "no_context_ambiguity_pass_rate": 0.9808,
    "seeded_context_binding_pass_rate": 0.7170,
    "real_multiturn_followup_pass_rate": 1.0000,
    "correction_binding_pass_rate": 0.7059,
    "confirmation_binding_pass_rate": 0.7308,
    "native_family_binding_correctness": 0.9821,
    "generic_provider_fallback_count": 0,
    "provider_model_calls": 0,
    "real_external_actions": 0,
    "payload_failures": 0,
    "routine_save_blocker_label_preserved_count": 6,
}

CORRECTION_RE = re.compile(
    r"\b(?:no,\s*use the other one|not that one|use the other one|other (?:file|page|app|target|one)|the other one)\b",
    re.IGNORECASE,
)
CONFIRMATION_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|confirm|go ahead|do it|approve|proceed|continue)\b|"
    r"\b(?:yes,\s*go ahead|go ahead with that preview)\b",
    re.IGNORECASE,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Context Binding Completion Pass 1.")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--summarize-existing", action="store_true")
    args = parser.parse_args()

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    baseline_rows = context_audit.read_jsonl(BASE_RESULTS)
    seeded_audit = build_seeded_context_failure_audit(baseline_rows)
    correction_audit = build_correction_binding_audit(baseline_rows)
    confirmation_audit = build_confirmation_binding_audit(baseline_rows)
    write_json(out / "seeded_context_failure_audit.json", seeded_audit)
    (out / "seeded_context_failure_audit.md").write_text(render_seeded_audit(seeded_audit), encoding="utf-8")
    write_json(out / "correction_binding_audit.json", correction_audit)
    (out / "correction_binding_audit.md").write_text(render_correction_audit(correction_audit), encoding="utf-8")
    write_json(out / "confirmation_binding_audit.json", confirmation_audit)
    (out / "confirmation_binding_audit.md").write_text(render_confirmation_audit(confirmation_audit), encoding="utf-8")

    if args.audit_only:
        summary = build_final_summary({}, seeded_audit, correction_audit, confirmation_audit)
        write_json(out / "context_binding_completion_summary.json", summary)
        (out / "context_binding_completion_report.md").write_text(
            render_final_report(summary, seeded_audit, correction_audit, confirmation_audit, {}),
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    if args.summarize_existing:
        rows = context_audit.read_jsonl(out / RESULTS_NAME)
        post_orphan = checkpoint._orphan_process_check_result()
        target_summary = build_target_summary(
            rows=rows,
            total_cases=len(rows),
            pre_orphan="not_rechecked_for_summarize_existing",
            post_orphan=post_orphan,
        )
        write_json(out / "targeted_context_binding_summary.json", target_summary)
        (out / "targeted_context_binding_report.md").write_text(
            render_target_report(target_summary),
            encoding="utf-8",
        )
        summary = build_final_summary(target_summary, seeded_audit, correction_audit, confirmation_audit)
        write_json(out / "context_binding_completion_summary.json", summary)
        (out / "context_binding_completion_report.md").write_text(
            render_final_report(summary, seeded_audit, correction_audit, confirmation_audit, target_summary),
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing targeted binding eval with existing command-eval child process: {pre_orphan}")

    kraken_rows = context_audit.read_jsonl(KRAKEN_RESULTS)
    kraken_corpus_rows = context_audit.read_jsonl(KRAKEN_CORPUS)
    cases = build_target_cases(kraken_rows=kraken_rows, kraken_corpus_rows=kraken_corpus_rows)
    write_jsonl(out / "targeted_context_binding_corpus.jsonl", [case.to_dict() for case in cases])

    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=out,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="shared_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    harness.run(cases, results_name=RESULTS_NAME, resume=False)
    rows = context_audit.read_jsonl(out / RESULTS_NAME)
    post_orphan = checkpoint._orphan_process_check_result()
    target_summary = build_target_summary(
        rows=rows,
        total_cases=len(cases),
        pre_orphan=pre_orphan,
        post_orphan=post_orphan,
    )
    write_json(out / "targeted_context_binding_summary.json", target_summary)
    (out / "targeted_context_binding_report.md").write_text(
        render_target_report(target_summary),
        encoding="utf-8",
    )
    summary = build_final_summary(target_summary, seeded_audit, correction_audit, confirmation_audit)
    write_json(out / "context_binding_completion_summary.json", summary)
    (out / "context_binding_completion_report.md").write_text(
        render_final_report(summary, seeded_audit, correction_audit, confirmation_audit, target_summary),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "targeted_rows": target_summary["durable_rows"],
                "seeded_context_binding_pass_rate": target_summary["seeded_context_binding_pass_rate"],
                "correction_binding_pass_rate": target_summary["correction_binding_pass_rate"],
                "confirmation_binding_pass_rate": target_summary["confirmation_binding_pass_rate"],
                "real_multiturn_followup_pass_rate": target_summary["real_multiturn_followup_pass_rate"],
                "no_context_ambiguity_pass_rate": target_summary["no_context_ambiguity_pass_rate"],
                "generic_provider_fallback_count": target_summary["generic_provider_fallback_count"],
                "provider_model_calls": target_summary["safety"]["provider_model_calls"],
                "real_external_actions": target_summary["safety"]["real_external_actions"],
                "payload_failures": target_summary["safety"]["payload_failures"],
                "final_recommendation": summary["final_recommendation"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def build_target_cases(*, kraken_rows: list[dict[str, Any]], kraken_corpus_rows: list[dict[str, Any]]) -> list[CommandEvalCase]:
    base_cases = multiturn.build_target_cases(kraken_rows=kraken_rows, kraken_corpus_rows=kraken_corpus_rows)
    combined = base_cases + completion_cases()
    seen: set[str] = set()
    unique: list[CommandEvalCase] = []
    for case in combined:
        if case.case_id in seen:
            continue
        seen.add(case.case_id)
        unique.append(case)
    return unique


def completion_cases() -> list[CommandEvalCase]:
    readme = str(ROOT / "README.md")
    return [
        _case(
            "binding_correction_with_prior_owner_alternate",
            "no, use the other one",
            "browser_destination",
            "browser",
            tools=("external_open_url",),
            context_lane="correction_with_prior_owner",
            active_request_state={
                "family": "browser_destination",
                "subject": "Example",
                "route": {"tool_name": "external_open_url"},
                "parameters": {
                    "tool_name": "external_open_url",
                    "url": "https://example.com",
                    "previous_choice": "Example",
                    "alternate_target": "Stormhelm docs",
                    "alternate_target_url": "https://docs.example.com/stormhelm",
                    "context_freshness": "current",
                },
            },
            expected_prior_family="browser_destination",
            expected_prior_tool="external_open_url",
            expected_alternate_target="Stormhelm docs",
        ),
        _case(
            "binding_correction_prior_owner_no_alternate",
            "no, use the other one",
            "browser_destination",
            "browser",
            tools=("external_open_url",),
            context_lane="ambiguous_context_clarification",
            active_request_state={
                "family": "browser_destination",
                "subject": "Example",
                "route": {"tool_name": "external_open_url"},
                "parameters": {
                    "tool_name": "external_open_url",
                    "url": "https://example.com",
                    "context_freshness": "current",
                },
            },
            clarification="expected",
            expected_prior_family="browser_destination",
            expected_prior_tool="external_open_url",
        ),
        _case(
            "binding_correction_without_prior_owner",
            "no, use the other one",
            "context_clarification",
            "context",
            context_lane="correction_without_prior_owner",
            clarification="expected",
            seeded_context_required=False,
        ),
        _case(
            "binding_confirmation_with_pending_preview",
            "yes, go ahead with that preview",
            "browser_destination",
            "browser",
            tools=("external_open_url",),
            context_lane="seeded_context_binding",
            active_request_state={
                "family": "browser_destination",
                "subject": "Example",
                "route": {"tool_name": "external_open_url"},
                "parameters": {
                    "tool_name": "external_open_url",
                    "url": "https://example.com",
                    "pending_preview": {"id": "preview-browser-1", "status": "pending"},
                    "request_stage": "preview",
                    "context_freshness": "current",
                },
            },
            approval="expected_or_preview",
            expected_prior_family="browser_destination",
            expected_prior_tool="external_open_url",
            expected_confirmation_state="pending_preview",
        ),
        _case(
            "binding_confirmation_without_pending_preview",
            "yes, go ahead",
            "context_clarification",
            "context",
            context_lane="no_context_ambiguity",
            active_request_state={
                "family": "browser_destination",
                "subject": "Example",
                "route": {"tool_name": "external_open_url"},
                "parameters": {
                    "tool_name": "external_open_url",
                    "url": "https://example.com",
                    "context_freshness": "current",
                },
            },
            clarification="expected",
            expected_prior_family="browser_destination",
        ),
        _case(
            "binding_stale_confirmation_preview",
            "yes, go ahead",
            "context_clarification",
            "context",
            context_lane="stale_context_rejection",
            active_request_state={
                "family": "browser_destination",
                "subject": "Example",
                "route": {"tool_name": "external_open_url"},
                "context_reusable": False,
                "parameters": {
                    "tool_name": "external_open_url",
                    "url": "https://example.com",
                    "pending_preview": {"id": "preview-browser-old", "status": "pending"},
                    "request_stage": "preview",
                    "context_freshness": "stale",
                },
            },
            clarification="expected",
            expected_prior_family="browser_destination",
            expected_confirmation_state="pending_preview",
        ),
        _case(
            "binding_seeded_file_prior_route_tool_target",
            "do the same thing as before",
            "file",
            "files",
            tools=("file_reader",),
            context_lane="seeded_context_binding",
            active_request_state={
                "family": "file",
                "subject": readme,
                "route": {"tool_name": "file_reader"},
                "parameters": {"tool_name": "file_reader", "path": readme, "context_freshness": "current"},
            },
            expected_prior_family="file",
            expected_prior_tool="file_reader",
            expected_target_binding="active_request_state.parameters.path",
        ),
        _case(
            "binding_seeded_file_missing_required_path",
            "do the same thing as before",
            "file",
            "files",
            tools=("file_reader",),
            context_lane="ambiguous_context_clarification",
            active_request_state={
                "family": "file",
                "subject": "file",
                "route": {"tool_name": "file_reader"},
                "parameters": {"tool_name": "file_reader", "context_freshness": "current"},
            },
            clarification="expected",
            expected_prior_family="file",
            expected_prior_tool="file_reader",
        ),
    ]


def _case(
    case_id: str,
    message: str,
    route_family: str,
    subsystem: str,
    *,
    context_lane: str,
    tools: tuple[str, ...] = (),
    active_request_state: dict[str, Any] | None = None,
    input_context: dict[str, Any] | None = None,
    workspace_context: dict[str, Any] | None = None,
    seeded_context_required: bool | None = None,
    expected_prior_family: str = "",
    expected_prior_tool: str = "",
    expected_target_binding: str = "",
    expected_alternate_target: str = "",
    expected_confirmation_state: str = "",
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
        session_id=f"context-binding-{case_id}",
        active_request_state=active_request_state or {},
        input_context=input_context or {},
        workspace_context=workspace_context or {},
        context_lane=context_lane,
        seeded_context_required=bool(
            seeded_context_required
            if seeded_context_required is not None
            else context_lane not in {"no_context_ambiguity", "correction_without_prior_owner"}
        ),
        expected_context_source="active_request_state" if active_request_state else "none",
        expected_prior_family=expected_prior_family,
        expected_prior_tool=expected_prior_tool,
        expected_target_binding=expected_target_binding,
        expected_alternate_target=expected_alternate_target,
        expected_confirmation_state=expected_confirmation_state,
        expected_behavior_without_context="context_clarification" if context_lane != "not_context_dependent" else "",
        tags=("context_binding_completion_1", context_lane),
    )


def build_seeded_context_failure_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [
        row
        for row in rows
        if str(row.get("context_lane") or "") == "seeded_context_binding"
        and not context_audit.assertion_context_pass(row)
    ]
    audit_rows = [seeded_failure_row(row) for row in failures]
    return {
        "source_results": str(BASE_RESULTS),
        "total_seeded_context_failures": len(audit_rows),
        "root_cause_counts": dict(Counter(item["root_cause"] for item in audit_rows)),
        "rows": audit_rows,
    }


def seeded_failure_row(row: dict[str, Any]) -> dict[str, Any]:
    state = active_state(row)
    params = parameters(state)
    return {
        "test_id": test_id(row),
        "prompt": prompt(row),
        "expected": expected_shape(row),
        "actual": actual_shape(row),
        "seeded_context_fields": seeded_fields(row),
        "active_request_state_fields": sorted(state.keys()),
        "prior_route_family": state.get("family", ""),
        "prior_tool_action": tool_from_state(state),
        "prior_target_entity": target_from_state(state),
        "pending_approval_preview": pending_preview_summary(state),
        "expected_binding_source": row.get("expected_context_source") or case_payload(row).get("expected_context_source") or "",
        "actual_binding_source": actual_binding_source(row),
        "context_freshness": freshness_from_state(state),
        "why_binding_failed": failure_reason(row),
        "root_cause": classify_seeded_root_cause(row, state, params),
    }


def build_correction_binding_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    correction_rows = [row for row in rows if is_correction_row(row)]
    audit_rows = [correction_row(row) for row in correction_rows if not context_audit.assertion_context_pass(row)]
    return {
        "source_results": str(BASE_RESULTS),
        "total_correction_rows": len(correction_rows),
        "total_correction_failures": len(audit_rows),
        "root_cause_counts": dict(Counter(item["root_cause"] for item in audit_rows)),
        "policy": {
            "prior_owner_and_alternate_target": "prior native family with alternate target",
            "prior_owner_without_alternate": "native clarification",
            "no_prior_owner": "context_clarification",
            "generic_provider": "must not win",
        },
        "rows": audit_rows,
    }


def correction_row(row: dict[str, Any]) -> dict[str, Any]:
    state = active_state(row)
    prior_owner = bool(native_family(state))
    alternate = has_alternate_target(state)
    prior_target = bool(target_from_state(state))
    actual_family = str(row.get("actual_route_family") or "")
    expected_family = str(row.get("expected_route_family") or "")
    clarification = bool(row.get("observation", {}).get("clarification_observed")) if isinstance(row.get("observation"), dict) else False
    return {
        "test_id": test_id(row),
        "prompt": prompt(row),
        "expected": expected_shape(row),
        "actual": actual_shape(row),
        "prior_owner_present": prior_owner,
        "prior_target_present": prior_target,
        "alternate_target_present": alternate,
        "correction_phrase_strength": correction_strength(prompt(row)),
        "can_honestly_bind": prior_owner and alternate,
        "clarification_is_correct": (prior_owner and not alternate and clarification) or (not prior_owner and actual_family == "context_clarification"),
        "native_family_should_own": prior_owner,
        "expected_alternate_target_seeded": bool(row.get("expected_alternate_target") or case_payload(row).get("expected_alternate_target")),
        "actual_generic_provider": actual_family == "generic_provider",
        "root_cause": classify_correction_root_cause(row, prior_owner, alternate, expected_family, actual_family, clarification),
    }


def build_confirmation_binding_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    confirmation_rows = [row for row in rows if is_confirmation_row(row)]
    audit_rows = [confirmation_row(row) for row in confirmation_rows if not context_audit.assertion_context_pass(row)]
    return {
        "source_results": str(BASE_RESULTS),
        "total_confirmation_rows": len(confirmation_rows),
        "total_confirmation_failures": len(audit_rows),
        "root_cause_counts": dict(Counter(item["root_cause"] for item in audit_rows)),
        "policy": {
            "fresh_pending_preview": "approval/preview path without live external action",
            "no_pending_preview": "no_pending_confirmation or context clarification",
            "stale_confirmation": "clarification or rejection",
            "direct_execution": "not allowed",
        },
        "rows": audit_rows,
    }


def confirmation_row(row: dict[str, Any]) -> dict[str, Any]:
    state = active_state(row)
    params = parameters(state)
    pending = has_pending_confirmation(state)
    actual = actual_shape(row)
    expected = expected_shape(row)
    return {
        "test_id": test_id(row),
        "prompt": prompt(row),
        "pending_approval_preview_present": pending,
        "pending_confirmation_id": pending_confirmation_id(state),
        "prior_route_family": state.get("family", ""),
        "risk_level": params.get("risk_level") or params.get("risk") or "",
        "approval_required": row.get("expected_approval_state") in {"expected", "expected_or_preview", "allowed"},
        "preview_required": bool(row.get("expected_confirmation_state") or params.get("pending_preview")),
        "expected_confirmation_behavior": expected,
        "actual_confirmation_behavior": actual,
        "action_execution_attempted": bool(row.get("external_action_performed")),
        "dry_run_preserved": bool(row.get("dry_run")) or str(row.get("actual_result_state") or "") in {"dry_run", "dry_run_ready", "needs_clarification"},
        "confirmation_stale_expired_missing": confirmation_staleness(state),
        "root_cause": classify_confirmation_root_cause(row, pending),
    }


def build_target_summary(*, rows: list[dict[str, Any]], total_cases: int, pre_orphan: str, post_orphan: str) -> dict[str, Any]:
    summary = context_audit.build_target_summary(
        rows=rows,
        total_cases=total_cases,
        pre_orphan=pre_orphan,
        post_orphan=post_orphan,
    )
    lane_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        lane_rows[str(row.get("context_lane") or case_payload(row).get("context_lane") or "")].append(row)
    confirmation_rows = [row for row in rows if is_confirmation_row(row)]
    correction_rows = [row for row in rows if str(row.get("context_lane") or "") == "correction_with_prior_owner"]
    latency_rows = [row for row in rows if row.get("failure_category") == "latency_issue"]
    native_rows = [
        row
        for row in rows
        if str(row.get("context_lane") or "") in {"seeded_context_binding", "correction_with_prior_owner", "real_multiturn_followup"}
        and str(row.get("expected_route_family") or "") not in {"context_clarification", "generic_provider", "unsupported"}
    ]
    native_correct = sum(1 for row in native_rows if row.get("actual_route_family") == row.get("expected_route_family"))
    summary["confirmation_binding_pass_rate"] = rate(
        sum(1 for row in confirmation_rows if context_audit.assertion_context_pass(row)),
        len(confirmation_rows),
    )
    summary["confirmation_binding_rows"] = len(confirmation_rows)
    summary["correction_binding_pass_rate"] = rate(
        sum(1 for row in correction_rows if context_audit.assertion_context_pass(row)),
        len(correction_rows),
    )
    summary["correction_binding_rows"] = len(correction_rows)
    summary["native_family_binding_correctness"] = {
        "correct": native_correct,
        "total": len(native_rows),
        "pass_rate": rate(native_correct, len(native_rows)),
    }
    summary["latency_lane"] = {
        "latency_issue_count": len(latency_rows),
        "latency_is_separate_from_context_correctness": True,
        "examples": context_audit.compact_rows(latency_rows[:20]),
    }
    summary["baseline"] = dict(BASELINE)
    summary["deltas"] = {
        key: round(float(summary.get(key) or 0) - float(value), 4)
        for key, value in BASELINE.items()
        if key in summary
        and isinstance(summary.get(key), (int, float, str))
        and isinstance(value, (int, float, str))
    }
    summary["seeded_context_failures"] = context_audit.compact_rows(
        [row for row in lane_rows.get("seeded_context_binding", []) if not context_audit.assertion_context_pass(row)][:40]
    )
    summary["correction_failures"] = context_audit.compact_rows(
        [row for row in correction_rows if not context_audit.assertion_context_pass(row)][:40]
    )
    summary["confirmation_failures"] = context_audit.compact_rows(
        [row for row in confirmation_rows if not context_audit.assertion_context_pass(row)][:40]
    )
    summary["provider_model_calls"] = summary["safety"]["provider_model_calls"]
    summary["real_external_actions"] = summary["safety"]["real_external_actions"]
    summary["payload_failures"] = summary["safety"]["payload_failures"]
    return summary


def build_final_summary(
    target_summary: dict[str, Any],
    seeded_audit: dict[str, Any],
    correction_audit: dict[str, Any],
    confirmation_audit: dict[str, Any],
) -> dict[str, Any]:
    if not target_summary:
        return {
            "phase": "context_binding_completion_1",
            "baseline_targeted_rows": BASELINE["targeted_rows"],
            "seeded_context_failure_count": seeded_audit["total_seeded_context_failures"],
            "correction_failure_count": correction_audit["total_correction_failures"],
            "confirmation_failure_count": confirmation_audit["total_confirmation_failures"],
            "final_recommendation": "continue_targeted_context_binding",
        }
    success = (
        target_summary["real_multiturn_followup_pass_rate"] >= 1.0
        and target_summary["no_context_ambiguity_pass_rate"] >= 0.95
        and target_summary["seeded_context_binding_pass_rate"] > 0.80
        and target_summary["correction_binding_pass_rate"] > 0.80
        and target_summary["confirmation_binding_pass_rate"] > 0.80
        and target_summary["generic_provider_fallback_count"] == 0
        and target_summary["safety"]["provider_model_calls"] == 0
        and target_summary["safety"]["real_external_actions"] == 0
        and target_summary["safety"]["payload_failures"] == 0
    )
    recommendation = "continue_targeted_context_binding"
    if success and target_summary.get("latency_lane", {}).get("latency_issue_count", 0):
        recommendation = "fix_latency_lane"
    elif success:
        recommendation = "run_second_1000_after_context_repairs"
    return {
        "phase": "context_binding_completion_1",
        "targeted_rows": target_summary["durable_rows"],
        "no_context_ambiguity_pass_rate": target_summary["no_context_ambiguity_pass_rate"],
        "seeded_context_binding_pass_rate": target_summary["seeded_context_binding_pass_rate"],
        "real_multiturn_followup_pass_rate": target_summary["real_multiturn_followup_pass_rate"],
        "correction_binding_pass_rate": target_summary["correction_binding_pass_rate"],
        "confirmation_binding_pass_rate": target_summary["confirmation_binding_pass_rate"],
        "native_family_binding_correctness": target_summary["native_family_binding_correctness"],
        "generic_provider_fallback_count": target_summary["generic_provider_fallback_count"],
        "provider_model_calls": target_summary["safety"]["provider_model_calls"],
        "real_external_actions": target_summary["safety"]["real_external_actions"],
        "payload_failures": target_summary["safety"]["payload_failures"],
        "hard_timeouts": target_summary["safety"]["hard_timeouts"],
        "routine_save_blocker_label_preserved_count": target_summary["routine_save_blocker_label_preserved_count"],
        "latency_lane": target_summary["latency_lane"],
        "baseline": dict(BASELINE),
        "seeded_context_audit_root_causes": seeded_audit["root_cause_counts"],
        "correction_audit_root_causes": correction_audit["root_cause_counts"],
        "confirmation_audit_root_causes": confirmation_audit["root_cause_counts"],
        "success_criteria_met": success,
        "final_recommendation": recommendation,
    }


def classify_seeded_root_cause(row: dict[str, Any], state: dict[str, Any], params: dict[str, Any]) -> str:
    if is_confirmation_row(row) and not has_pending_confirmation(state):
        return "confirmation_state_missing"
    if is_correction_row(row) and not has_alternate_target(state):
        return "correction_alternate_missing"
    if row.get("actual_route_family") == row.get("expected_route_family") and row.get("actual_result_state") == "needs_clarification":
        return "missing_seed_field"
    if native_family(state) and native_family(state) != row.get("expected_route_family"):
        return "corpus_expectation_issue"
    if not tool_from_state(state):
        return "tool_binding_gap"
    if not target_from_state(state):
        return "target_binding_gap"
    if row.get("actual_route_family") == "context_clarification":
        return "ambiguous_context_correctly_clarified"
    if row.get("actual_tool") != row.get("expected_tool"):
        return "tool_binding_gap"
    return "planner_context_adapter_gap"


def classify_correction_root_cause(
    row: dict[str, Any],
    prior_owner: bool,
    alternate: bool,
    expected_family: str,
    actual_family: str,
    clarification: bool,
) -> str:
    if not prior_owner and actual_family == "context_clarification":
        return "ambiguous_context_correctly_clarified"
    if prior_owner and not alternate and clarification:
        return "ambiguous_context_correctly_clarified"
    if prior_owner and not alternate:
        return "correction_alternate_missing"
    if not prior_owner:
        return "missing_seed_field"
    if actual_family != expected_family:
        return "planner_context_adapter_gap"
    return "target_binding_gap"


def classify_confirmation_root_cause(row: dict[str, Any], pending: bool) -> str:
    state = active_state(row)
    if not pending:
        return "confirmation_state_missing"
    if confirmation_staleness(state) != "fresh":
        return "stale_context_correctly_rejected"
    if row.get("external_action_performed"):
        return "result_state_policy_gap"
    if row.get("actual_result_state") == "needs_clarification":
        return "missing_seed_field"
    if row.get("actual_route_family") != row.get("expected_route_family"):
        return "planner_context_adapter_gap"
    return "result_state_policy_gap"


def is_correction_row(row: dict[str, Any]) -> bool:
    lane = str(row.get("context_lane") or case_payload(row).get("context_lane") or "")
    return lane.startswith("correction_") or bool(CORRECTION_RE.search(prompt(row)))


def is_confirmation_row(row: dict[str, Any]) -> bool:
    if is_correction_row(row):
        return False
    text = prompt(row)
    expected_state = str(row.get("expected_confirmation_state") or case_payload(row).get("expected_confirmation_state") or "")
    style = str(row.get("wording_style") or "")
    return style == "confirm" or bool(expected_state) or bool(CONFIRMATION_RE.search(text))


def case_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("case")
    return payload if isinstance(payload, dict) else {}


def active_state(row: dict[str, Any]) -> dict[str, Any]:
    state = case_payload(row).get("active_request_state")
    return state if isinstance(state, dict) else {}


def parameters(state: dict[str, Any]) -> dict[str, Any]:
    payload = state.get("parameters")
    return payload if isinstance(payload, dict) else {}


def native_family(state: dict[str, Any]) -> str:
    family = str(state.get("family") or "").strip()
    return "" if family in {"", "generic_provider", "unsupported", "context_clarification"} else family


def tool_from_state(state: dict[str, Any]) -> str:
    params = parameters(state)
    route = state.get("route") if isinstance(state.get("route"), dict) else {}
    return str(params.get("tool_name") or params.get("operation_type") or params.get("operation") or params.get("source_case") or route.get("tool_name") or "").strip()


def target_from_state(state: dict[str, Any]) -> str:
    params = parameters(state)
    return str(
        params.get("target_name")
        or params.get("path")
        or params.get("target_path")
        or params.get("url")
        or params.get("target_url")
        or params.get("destination_alias")
        or params.get("destination_name")
        or params.get("new_name")
        or state.get("subject")
        or ""
    ).strip()


def has_alternate_target(state: dict[str, Any]) -> bool:
    params = parameters(state)
    return bool(params.get("alternate_target") or params.get("alternate_target_url") or params.get("alternate_target_path"))


def has_pending_confirmation(state: dict[str, Any]) -> bool:
    params = parameters(state)
    preview = params.get("pending_preview")
    trust = state.get("trust") if isinstance(state.get("trust"), dict) else {}
    return bool(preview or params.get("pending_confirmation_id") or params.get("pending_preview_id") or trust.get("request_id"))


def pending_confirmation_id(state: dict[str, Any]) -> str:
    params = parameters(state)
    preview = params.get("pending_preview") if isinstance(params.get("pending_preview"), dict) else {}
    trust = state.get("trust") if isinstance(state.get("trust"), dict) else {}
    return str(params.get("pending_confirmation_id") or params.get("pending_preview_id") or preview.get("id") or trust.get("request_id") or "")


def freshness_from_state(state: dict[str, Any]) -> str:
    params = parameters(state)
    return str(params.get("context_freshness") or state.get("context_freshness") or "none").strip().lower()


def confirmation_staleness(state: dict[str, Any]) -> str:
    if not has_pending_confirmation(state):
        return "missing"
    freshness = freshness_from_state(state)
    if freshness in {"stale", "expired"} or state.get("context_reusable") is False:
        return "stale"
    return "fresh"


def pending_preview_summary(state: dict[str, Any]) -> dict[str, Any]:
    params = parameters(state)
    preview = params.get("pending_preview") if isinstance(params.get("pending_preview"), dict) else {}
    return {
        "present": has_pending_confirmation(state),
        "id": pending_confirmation_id(state),
        "request_stage": params.get("request_stage", ""),
        "preview_keys": sorted(preview.keys()),
    }


def seeded_fields(row: dict[str, Any]) -> dict[str, bool]:
    state = active_state(row)
    return {
        "active_request_state": bool(state),
        "prior_route_family": bool(native_family(state)),
        "prior_tool_action": bool(tool_from_state(state)),
        "prior_target_entity": bool(target_from_state(state)),
        "pending_approval_preview": has_pending_confirmation(state),
        "alternate_target": has_alternate_target(state),
    }


def actual_binding_source(row: dict[str, Any]) -> str:
    intent = row.get("intent_frame") if isinstance(row.get("intent_frame"), dict) else {}
    extracted = intent.get("extracted_entities") if isinstance(intent.get("extracted_entities"), dict) else {}
    selected = extracted.get("selected_context") if isinstance(extracted.get("selected_context"), dict) else {}
    return str(selected.get("source") or row.get("expected_context_source") or "")


def expected_shape(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "family": row.get("expected_route_family"),
        "subsystem": row.get("expected_subsystem"),
        "tool": row.get("expected_tool"),
        "result_state": row.get("expected_result_state"),
    }


def actual_shape(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "family": row.get("actual_route_family"),
        "subsystem": row.get("actual_subsystem"),
        "tool": row.get("actual_tool"),
        "result_state": row.get("actual_result_state"),
    }


def failure_reason(row: dict[str, Any]) -> str:
    failed = []
    assertions = row.get("assertions") if isinstance(row.get("assertions"), dict) else {}
    for name, payload in assertions.items():
        if isinstance(payload, dict) and not payload.get("passed"):
            failed.append(name)
    reason = str(row.get("failure_reason") or row.get("failure_category") or "")
    return ", ".join(failed) + (f" ({reason})" if reason else "")


def test_id(row: dict[str, Any]) -> str:
    return str(row.get("test_id") or case_payload(row).get("case_id") or "")


def prompt(row: dict[str, Any]) -> str:
    return str(row.get("prompt") or row.get("input") or case_payload(row).get("message") or "")


def correction_strength(text: str) -> str:
    lower = text.lower()
    if "no," in lower or "not that" in lower:
        return "strong"
    if "other" in lower:
        return "medium"
    return "weak"


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def render_seeded_audit(audit: dict[str, Any]) -> str:
    lines = [
        "# Seeded Context Failure Audit",
        "",
        f"- source results: `{audit['source_results']}`",
        f"- seeded-context failures: {audit['total_seeded_context_failures']}",
        "",
        "## Root Causes",
        "",
        *[f"- {key}: {value}" for key, value in sorted(audit["root_cause_counts"].items())],
        "",
        "## Rows",
        "",
    ]
    for row in audit["rows"]:
        lines.append(
            f"- `{row['test_id']}` `{row['prompt']}` expected `{row['expected']['family']}`/`{row['expected']['tool']}` "
            f"actual `{row['actual']['family']}`/`{row['actual']['tool']}` root `{row['root_cause']}`: {row['why_binding_failed']}"
        )
    if not audit["rows"]:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def render_correction_audit(audit: dict[str, Any]) -> str:
    lines = [
        "# Correction Binding Audit",
        "",
        f"- source results: `{audit['source_results']}`",
        f"- correction rows: {audit['total_correction_rows']}",
        f"- correction failures: {audit['total_correction_failures']}",
        "",
        "## Root Causes",
        "",
        *[f"- {key}: {value}" for key, value in sorted(audit["root_cause_counts"].items())],
        "",
        "## Failure Rows",
        "",
    ]
    for row in audit["rows"]:
        lines.append(
            f"- `{row['test_id']}` prior_owner={row['prior_owner_present']} alternate={row['alternate_target_present']} "
            f"can_bind={row['can_honestly_bind']} native_should_own={row['native_family_should_own']} root `{row['root_cause']}`"
        )
    if not audit["rows"]:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def render_confirmation_audit(audit: dict[str, Any]) -> str:
    lines = [
        "# Confirmation Binding Audit",
        "",
        f"- source results: `{audit['source_results']}`",
        f"- confirmation rows: {audit['total_confirmation_rows']}",
        f"- confirmation failures: {audit['total_confirmation_failures']}",
        "",
        "## Root Causes",
        "",
        *[f"- {key}: {value}" for key, value in sorted(audit["root_cause_counts"].items())],
        "",
        "## Failure Rows",
        "",
    ]
    for row in audit["rows"]:
        lines.append(
            f"- `{row['test_id']}` pending={row['pending_approval_preview_present']} id=`{row['pending_confirmation_id']}` "
            f"stale={row['confirmation_stale_expired_missing']} action_attempted={row['action_execution_attempted']} root `{row['root_cause']}`"
        )
    if not audit["rows"]:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def render_target_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Targeted Context Binding Results",
        "",
        f"- durable rows: {summary['durable_rows']} / {summary['total_cases']}",
        f"- no-context ambiguity pass rate: {summary['no_context_ambiguity_pass_rate']}",
        f"- seeded-context binding pass rate: {summary['seeded_context_binding_pass_rate']}",
        f"- real multi-turn follow-up pass rate: {summary['real_multiturn_followup_pass_rate']}",
        f"- correction binding pass rate: {summary['correction_binding_pass_rate']}",
        f"- confirmation binding pass rate: {summary['confirmation_binding_pass_rate']}",
        f"- native family binding correctness: {summary['native_family_binding_correctness']['correct']}/{summary['native_family_binding_correctness']['total']} ({summary['native_family_binding_correctness']['pass_rate']})",
        f"- generic-provider fallback count: {summary['generic_provider_fallback_count']}",
        f"- provider/model calls: {summary['safety']['provider_model_calls']}",
        f"- real external actions: {summary['safety']['real_external_actions']}",
        f"- payload failures: {summary['safety']['payload_failures']}",
        f"- hard timeouts: {summary['safety']['hard_timeouts']}",
        f"- routine_save blocker label preserved count: {summary['routine_save_blocker_label_preserved_count']}",
        f"- latency lane: {summary['latency_lane']['latency_issue_count']} latency issues, separated",
        "",
        "## Lane Pass Rates",
        "",
    ]
    for lane, payload in summary["lane_summary"].items():
        lines.append(f"- {lane}: {payload['context_pass']}/{payload['total']} ({payload['pass_rate']})")
    lines.extend(["", "## Remaining Context Failures", ""])
    failures = summary["seeded_context_failures"] + summary["correction_failures"] + summary["confirmation_failures"]
    for row in failures[:80]:
        lines.append(
            f"- `{row['test_id']}` `{row['context_lane']}` expected `{row['expected_route_family']}`, "
            f"actual `{row['actual_route_family']}`: {row['failure_category']}"
        )
    if not failures:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def render_final_report(
    summary: dict[str, Any],
    seeded_audit: dict[str, Any],
    correction_audit: dict[str, Any],
    confirmation_audit: dict[str, Any],
    target_summary: dict[str, Any],
) -> str:
    lines = [
        "# Context Binding Completion Report",
        "",
        f"- final recommendation: `{summary['final_recommendation']}`",
        f"- baseline targeted rows: {BASELINE['targeted_rows']}",
        f"- seeded-context failures audited: {seeded_audit['total_seeded_context_failures']}",
        f"- correction failures audited: {correction_audit['total_correction_failures']}",
        f"- confirmation failures audited: {confirmation_audit['total_confirmation_failures']}",
    ]
    if target_summary:
        lines.extend(
            [
                "",
                "## Targeted Evaluation",
                "",
                f"- durable rows: {target_summary['durable_rows']}",
                f"- no-context ambiguity pass rate: {target_summary['no_context_ambiguity_pass_rate']}",
                f"- seeded-context binding pass rate: {target_summary['seeded_context_binding_pass_rate']}",
                f"- real multi-turn follow-up pass rate: {target_summary['real_multiturn_followup_pass_rate']}",
                f"- correction binding pass rate: {target_summary['correction_binding_pass_rate']}",
                f"- confirmation binding pass rate: {target_summary['confirmation_binding_pass_rate']}",
                f"- generic-provider fallback count: {target_summary['generic_provider_fallback_count']}",
                f"- provider/model calls: {target_summary['safety']['provider_model_calls']}",
                f"- real external actions: {target_summary['safety']['real_external_actions']}",
                f"- payload failures: {target_summary['safety']['payload_failures']}",
                f"- latency lane: {target_summary['latency_lane']['latency_issue_count']} separated latency issues",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    main()
