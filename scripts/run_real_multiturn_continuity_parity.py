from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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


BASE_CONTEXT_DIR = ROOT / ".artifacts" / "command-usability-eval" / "kraken-context-model-audit"
BASE_RESULTS = BASE_CONTEXT_DIR / "targeted_context_model_results.jsonl"
KRAKEN_DIR = ROOT / ".artifacts" / "command-usability-eval" / "full-1000-kraken"
KRAKEN_RESULTS = KRAKEN_DIR / "1000_kraken_results.jsonl"
KRAKEN_CORPUS = KRAKEN_DIR / "1000_kraken_corpus.jsonl"
OUT = ROOT / ".artifacts" / "command-usability-eval" / "real-multiturn-continuity-parity-1"
RESULTS_NAME = "targeted_multiturn_results.jsonl"
BASELINE = {
    "no_context_ambiguity_pass_rate": 0.9804,
    "seeded_context_binding_pass_rate": 0.7170,
    "real_multiturn_followup_pass_rate": 0.3333,
    "correction_binding_pass_rate": 0.7059,
    "confirmation_binding_pass_rate": 0.7226,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the real multi-turn continuity parity targeted pass.")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    baseline_rows = context_audit.read_jsonl(BASE_RESULTS)
    diff_audit = build_real_vs_seeded_diff(baseline_rows)
    contract = build_session_continuity_contract()
    write_json(out / "real_vs_seeded_context_diff.json", diff_audit)
    (out / "real_vs_seeded_context_diff.md").write_text(render_real_vs_seeded_diff(diff_audit), encoding="utf-8")
    write_json(out / "session_continuity_contract.json", contract)
    (out / "session_continuity_contract.md").write_text(render_session_contract(contract), encoding="utf-8")

    if args.audit_only:
        summary = build_final_summary(target_summary={}, diff_audit=diff_audit)
        write_json(out / "real_multiturn_continuity_parity_summary.json", summary)
        (out / "real_multiturn_continuity_parity_report.md").write_text(
            render_final_report(summary, diff_audit, contract, {}),
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing targeted continuity eval with existing command-eval child process: {pre_orphan}")

    kraken_rows = context_audit.read_jsonl(KRAKEN_RESULTS)
    kraken_corpus_rows = context_audit.read_jsonl(KRAKEN_CORPUS)
    cases = build_target_cases(kraken_rows=kraken_rows, kraken_corpus_rows=kraken_corpus_rows)
    write_jsonl(out / "targeted_multiturn_corpus.jsonl", [case.to_dict() for case in cases])
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
    write_json(out / "targeted_multiturn_summary.json", target_summary)
    (out / "targeted_multiturn_report.md").write_text(
        render_targeted_multiturn_report(target_summary, rows),
        encoding="utf-8",
    )
    summary = build_final_summary(target_summary=target_summary, diff_audit=diff_audit)
    write_json(out / "real_multiturn_continuity_parity_summary.json", summary)
    (out / "real_multiturn_continuity_parity_report.md").write_text(
        render_final_report(summary, diff_audit, contract, target_summary),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "targeted_cases": len(cases),
                "targeted_rows": len(rows),
                "real_multiturn_followup_pass_rate": target_summary["real_multiturn_followup_pass_rate"],
                "seeded_context_binding_pass_rate": target_summary["seeded_context_binding_pass_rate"],
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
    base_cases = [
        repair_base_target_case(case)
        for case in context_audit.build_target_cases(kraken_rows=kraken_rows, kraken_corpus_rows=kraken_corpus_rows)
    ]
    combined = base_cases + parity_cases()
    seen: set[str] = set()
    unique: list[CommandEvalCase] = []
    for case in combined:
        if case.case_id in seen:
            continue
        seen.add(case.case_id)
        unique.append(case)
    return unique


def repair_base_target_case(case: CommandEvalCase) -> CommandEvalCase:
    if case.case_id != "mt_discord_followup":
        return case
    expected = ExpectedBehavior(
        route_family="discord_relay",
        subsystem="discord_relay",
        tools=(),
        clarification="none",
        approval="expected_or_preview",
        latency_ms_max=case.expected.latency_ms_max,
    )
    return replace(
        case,
        expected=expected,
        expected_confirmation_state="pending_preview",
        expected_prior_family="discord_relay",
        expected_behavior_without_context="context_clarification",
    )


def parity_cases() -> list[CommandEvalCase]:
    readme = str(ROOT / "README.md")
    return [
        _case("parity_browser_setup", "open https://example.com", "browser_destination", "browser", tools=("external_open_url",), session_id="parity-browser", approval="allowed", context_lane="not_context_dependent"),
        _case("parity_browser_followup", "do the same thing as before", "browser_destination", "browser", tools=("external_open_url",), session_id="parity-browser", turn_index=1, approval="allowed", context_lane="real_multiturn_followup", expected_prior_family="browser_destination", expected_prior_tool="external_open_url", expected_target_binding="response_active_request_state.parameters.url"),
        _case("parity_file_setup", f"open {readme} externally", "file", "files", tools=("external_open_file",), session_id="parity-file", approval="allowed", context_lane="not_context_dependent"),
        _case("parity_file_followup", "do the same thing as before", "file", "files", tools=("external_open_file",), session_id="parity-file", turn_index=1, approval="allowed", context_lane="real_multiturn_followup", expected_prior_family="file", expected_prior_tool="external_open_file", expected_target_binding="response_active_request_state.parameters.path"),
        _case("parity_software_setup", "install Firefox", "software_control", "software_control", session_id="parity-software", approval="expected_or_preview", context_lane="not_context_dependent"),
        _case("parity_software_followup", "can you handle this?", "software_control", "software_control", session_id="parity-software", turn_index=1, approval="expected_or_preview", context_lane="real_multiturn_followup", expected_prior_family="software_control", expected_target_binding="response_active_request_state.parameters.target_name"),
        _case("parity_discord_setup", "send this to Baby on Discord", "discord_relay", "discord_relay", session_id="parity-discord", input_context={"selection": {"kind": "text", "value": "Selected relay text", "preview": "Selected relay text"}}, approval="allowed", context_lane="not_context_dependent"),
        _case("parity_discord_followup", "yes, go ahead", "discord_relay", "discord_relay", session_id="parity-discord", turn_index=1, approval="expected_or_preview", context_lane="real_multiturn_followup", expected_prior_family="discord_relay", expected_confirmation_state="pending_preview"),
        _case("parity_workspace_setup", "save this workspace", "workspace_operations", "workspace", tools=("workspace_save",), session_id="parity-workspace", workspace_context=docs_workspace(), context_lane="not_context_dependent"),
        _case("parity_workspace_followup", "do the same thing as before", "workspace_operations", "workspace", tools=("workspace_save",), session_id="parity-workspace", turn_index=1, context_lane="real_multiturn_followup", expected_prior_family="workspace_operations", expected_prior_tool="workspace_save"),
        _case("parity_routine_setup", "run my cleanup routine", "routine", "routine", tools=("routine_execute",), session_id="parity-routine", approval="allowed", context_lane="not_context_dependent"),
        _case("parity_routine_followup", "do the same thing as before", "routine", "routine", tools=("routine_execute",), session_id="parity-routine", turn_index=1, approval="allowed", context_lane="real_multiturn_followup", expected_prior_family="routine", expected_prior_tool="routine_execute"),
        _case("parity_correction_setup", "open https://example.com", "browser_destination", "browser", tools=("external_open_url",), session_id="parity-correction", approval="allowed", context_lane="not_context_dependent"),
        _case("parity_correction_followup", "no, use the other one", "context_clarification", "context", session_id="parity-correction", turn_index=1, clarification="expected", context_lane="ambiguous_context_clarification", expected_prior_family="browser_destination", expected_behavior_without_context="context_clarification"),
        _case("parity_no_context_setup", "what time is it", "time", "system", tools=("clock",), session_id="parity-no-context", context_lane="not_context_dependent"),
        _case("parity_no_context_other_one", "no, use the other one", "context_clarification", "context", session_id="parity-no-context", turn_index=1, clarification="expected", context_lane="correction_without_prior_owner", seeded_context_required=False),
        _case("parity_stale_setup", "open https://example.com", "browser_destination", "browser", tools=("external_open_url",), session_id="parity-stale", approval="allowed", context_lane="not_context_dependent"),
        _case(
            "parity_stale_followup",
            "do the same thing as before",
            "context_clarification",
            "context",
            session_id="parity-stale",
            turn_index=1,
            clarification="expected",
            context_lane="stale_context_rejection",
            active_request_state={
                "family": "browser_destination",
                "subject": "https://example.com",
                "route": {"tool_name": "external_open_url"},
                "context_freshness": "stale",
                "context_reusable": False,
                "parameters": {"url": "https://example.com", "tool_name": "external_open_url", "context_freshness": "stale"},
            },
            expected_prior_family="browser_destination",
        ),
        _case("parity_cross_session_setup", "open https://example.com", "browser_destination", "browser", tools=("external_open_url",), session_id="parity-cross-a", approval="allowed", context_lane="not_context_dependent"),
        _case("parity_cross_session_followup", "do the same thing as before", "context_clarification", "context", session_id="parity-cross-b", turn_index=1, clarification="expected", context_lane="no_context_ambiguity", seeded_context_required=False),
    ]


def _case(
    case_id: str,
    message: str,
    route_family: str,
    subsystem: str,
    *,
    context_lane: str,
    tools: tuple[str, ...] = (),
    input_context: dict[str, Any] | None = None,
    active_request_state: dict[str, Any] | None = None,
    workspace_context: dict[str, Any] | None = None,
    session_id: str | None = None,
    turn_index: int = 0,
    seeded_context_required: bool | None = None,
    expected_prior_family: str = "",
    expected_prior_tool: str = "",
    expected_target_binding: str = "",
    expected_alternate_target: str = "",
    expected_confirmation_state: str = "",
    expected_behavior_without_context: str = "",
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
        session_id=session_id or f"parity-{case_id}",
        input_context=input_context or {},
        active_request_state=active_request_state or {},
        workspace_context=workspace_context or {},
        context_lane=context_lane,
        seeded_context_required=bool(
            seeded_context_required
            if seeded_context_required is not None
            else context_lane not in {"not_context_dependent", "no_context_ambiguity", "correction_without_prior_owner"}
        ),
        expected_context_source="active_request_state" if active_request_state else "real_http_session" if turn_index else "none",
        expected_prior_family=expected_prior_family,
        expected_prior_tool=expected_prior_tool,
        expected_target_binding=expected_target_binding,
        expected_alternate_target=expected_alternate_target,
        expected_confirmation_state=expected_confirmation_state,
        expected_behavior_without_context=expected_behavior_without_context or ("context_clarification" if context_lane != "not_context_dependent" else ""),
        sequence_id=session_id or "",
        turn_index=turn_index,
        tags=("real_multiturn_continuity_parity_1", context_lane),
    )


def docs_workspace() -> dict[str, Any]:
    return {
        "workspace": {"workspaceId": "ws-docs", "name": "Docs Workspace", "topic": "Stormhelm docs"},
        "module": "chartroom",
    }


def build_real_vs_seeded_diff(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(row.get("test_id") or ""): row for row in rows}
    mappings = {
        "mt_browser_followup": ("browser_destination_follow_up_00", "planner_context_adapter_gap"),
        "mt_software_followup": ("software_control_install_follow_up_00", "active_request_state_not_rehydrated"),
        "mt_discord_followup": ("discord_relay_confirm_00", "corpus_expectation_issue"),
        "mt_workspace_followup": ("workspace_save_follow_up_00", "prior_tool_missing"),
    }
    audit_rows: list[dict[str, Any]] = []
    for real_id, (seeded_id, root_cause) in mappings.items():
        real = by_id.get(real_id, {})
        seeded = by_id.get(seeded_id, {})
        seeded_state = context_state(seeded)
        real_response_state = state_from_row(real, "response_active_request_state")
        real_snapshot_state = state_from_row(real, "snapshot_active_request_state")
        real_state = real_response_state or real_snapshot_state or context_state(real)
        audit_rows.append(
            {
                "test_id": real_id,
                "prompt": str(real.get("prompt") or ""),
                "expected": expected_shape(real),
                "actual": actual_shape(real),
                "context_lane": str(real.get("context_lane") or ""),
                "seeded_equivalent_test_id": seeded_id,
                "seeded_equivalent_passed": bool(seeded.get("passed")),
                "seeded_context_fields_present": continuity_fields(seeded_state),
                "real_http_context_fields_present": continuity_fields(real_state),
                "session_id": str(real.get("session_id") or ""),
                "conversation_id_or_equivalent": str(real.get("session_id") or ""),
                "active_request_state_present": bool(real_state),
                "prior_route_family_present": bool(real_state.get("family")),
                "prior_tool_action_present": bool(tool_from_state(real_state)),
                "prior_target_entity_present": bool(target_from_state(real_state)),
                "pending_approval_preview_present": has_pending_preview(real_state),
                "alternate_target_present": has_alternate_target(real_state),
                "context_freshness": freshness_from_state(real_state),
                "context_source": str(real_state.get("context_source") or "not_exposed_in_baseline_telemetry"),
                "where_state_is_lost_or_altered": state_loss_note(real_id, real_state),
                "root_cause": root_cause,
            }
        )
    counts = dict(Counter(row["root_cause"] for row in audit_rows))
    return {
        "source_results": str(BASE_RESULTS),
        "total_affected_rows": len(audit_rows),
        "root_cause_counts": counts,
        "rows": audit_rows,
    }


def context_state(row: dict[str, Any]) -> dict[str, Any]:
    case = row.get("case") if isinstance(row.get("case"), dict) else {}
    state = case.get("active_request_state") if isinstance(case.get("active_request_state"), dict) else {}
    return dict(state)


def state_from_row(row: dict[str, Any], key: str) -> dict[str, Any]:
    state = row.get(key)
    if isinstance(state, dict):
        return dict(state)
    observation = row.get("observation") if isinstance(row.get("observation"), dict) else {}
    state = observation.get(key)
    return dict(state) if isinstance(state, dict) else {}


def continuity_fields(state: dict[str, Any]) -> dict[str, bool]:
    return {
        "active_request_state": bool(state),
        "prior_route_family": bool(state.get("family")),
        "prior_subsystem": bool(state.get("subsystem") or state.get("request_type")),
        "prior_tool_action": bool(tool_from_state(state)),
        "prior_result_state": bool(state.get("result_state")),
        "prior_target_entity": bool(target_from_state(state)),
        "source_text": bool(state.get("source_text")),
        "target_summary": bool(state.get("target_summary") or state.get("subject")),
        "risk_approval_posture": bool(state.get("trust") or parameters(state).get("request_stage")),
        "pending_approval_preview": has_pending_preview(state),
        "alternate_targets": has_alternate_target(state),
        "timestamp_freshness": bool(state.get("captured_at") or freshness_from_state(state)),
        "task_workspace_session_binding": bool(state.get("task_id") or state.get("session_id")),
        "context_reusable": state.get("context_reusable") is not False,
        "stale_or_ambiguous_marker": freshness_from_state(state) in {"stale", "expired", "ambiguous", "conflicting"},
    }


def parameters(state: dict[str, Any]) -> dict[str, Any]:
    payload = state.get("parameters")
    return dict(payload) if isinstance(payload, dict) else {}


def tool_from_state(state: dict[str, Any]) -> str:
    params = parameters(state)
    route = state.get("route") if isinstance(state.get("route"), dict) else {}
    return str(params.get("tool_name") or params.get("source_case") or route.get("tool_name") or params.get("operation_type") or "").strip()


def target_from_state(state: dict[str, Any]) -> str:
    params = parameters(state)
    return str(params.get("target_name") or params.get("path") or params.get("url") or params.get("destination_alias") or state.get("subject") or "").strip()


def freshness_from_state(state: dict[str, Any]) -> str:
    params = parameters(state)
    return str(params.get("context_freshness") or state.get("context_freshness") or "none").strip().lower()


def has_pending_preview(state: dict[str, Any]) -> bool:
    params = parameters(state)
    stage = str(params.get("request_stage") or "").strip().lower()
    return bool(params.get("pending_preview") or state.get("trust") or stage in {"preview", "awaiting_confirmation"})


def has_alternate_target(state: dict[str, Any]) -> bool:
    params = parameters(state)
    return bool(params.get("alternate_target") or params.get("previous_choice") or params.get("ambiguity_choices"))


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


def state_loss_note(test_id: str, state: dict[str, Any]) -> str:
    if test_id == "mt_browser_followup":
        return "Prior browser owner was present enough to select browser_destination, but target URL was not bound into the follow-up plan."
    if test_id == "mt_software_followup":
        return "Turn 2 did not see a reusable software_control owner/target state and clarified instead."
    if test_id == "mt_discord_followup":
        return "Observed route stayed in discord_relay; baseline expectation required trust_approvals even though the product path was preview/approval relay handling."
    if test_id == "mt_workspace_followup":
        return "Prior workspace owner survived, but prior tool/action was altered from workspace_save to workspace_assemble."
    return "unknown"


def build_session_continuity_contract() -> dict[str, Any]:
    fields = [
        "prior_route_family",
        "prior_subsystem",
        "prior_tool_action",
        "prior_result_state",
        "prior_target_entity_slots",
        "source_text",
        "target_summary",
        "risk_approval_posture",
        "pending_approval_preview_id",
        "alternate_target_candidates",
        "timestamp_freshness",
        "task_workspace_session_binding",
        "context_reusable",
        "context_stale_or_ambiguous",
    ]
    return {
        "required_continuity_fields": fields,
        "rules": {
            "fresh_unambiguous_context": "Reusable only while fresh and unambiguous.",
            "missing_or_stale_context": "Clarify instead of guessing.",
            "session_isolation": "Prior owner must not leak across unrelated sessions.",
            "confirmation_binding": "Confirmation binds only to pending approval or preview state.",
            "correction_binding": "Correction binds only to a prior owner and an alternate target candidate.",
            "followup_binding": "Follow-up binds only to a reusable prior route/action/target.",
            "generic_provider": "Generic provider is not a success for native-capable context-dependent requests.",
        },
        "non_goals": [
            "No legacy planner behavior changes.",
            "No exact prompt patches.",
            "No stale-context promotion.",
            "No real external action execution.",
        ],
    }


def build_target_summary(*, rows: list[dict[str, Any]], total_cases: int, pre_orphan: str, post_orphan: str) -> dict[str, Any]:
    summary = context_audit.build_target_summary(
        rows=rows,
        total_cases=total_cases,
        pre_orphan=pre_orphan,
        post_orphan=post_orphan,
    )
    latency_rows = [row for row in rows if row.get("failure_category") == "latency_issue"]
    context_phrase_rows = [
        row
        for row in rows
        if str(row.get("context_lane") or "") in {
            "no_context_ambiguity",
            "seeded_context_binding",
            "real_multiturn_followup",
            "stale_context_rejection",
            "ambiguous_context_clarification",
            "correction_with_prior_owner",
            "correction_without_prior_owner",
        }
    ]
    summary["baseline"] = dict(BASELINE)
    summary["deltas"] = {
        key: round(float(summary.get(key) or 0.0) - float(value), 4)
        for key, value in BASELINE.items()
    }
    summary["latency_lane"] = {
        "latency_issue_count": len(latency_rows),
        "latency_issue_examples": context_audit.compact_rows(latency_rows[:20]),
        "latency_is_separate_from_context_correctness": True,
    }
    summary["context_dependent_generic_provider_fallback_count"] = sum(
        1 for row in context_phrase_rows if row.get("actual_route_family") == "generic_provider"
    )
    summary["context_dependent_rows"] = len(context_phrase_rows)
    summary["real_multiturn_failures"] = context_audit.compact_rows(
        [
            row
            for row in rows
            if str(row.get("context_lane") or "") == "real_multiturn_followup"
            and not context_audit.assertion_context_pass(row)
        ][:40]
    )
    summary["provider_model_calls"] = summary["safety"]["provider_model_calls"]
    summary["real_external_actions"] = summary["safety"]["real_external_actions"]
    summary["payload_failures"] = summary["safety"]["payload_failures"]
    return summary


def build_final_summary(*, target_summary: dict[str, Any], diff_audit: dict[str, Any]) -> dict[str, Any]:
    if not target_summary:
        return {
            "phase": "real_multiturn_continuity_parity_1",
            "diff_rows": diff_audit["total_affected_rows"],
            "final_recommendation": "continue_targeted_multiturn_followup",
        }
    return {
        "phase": "real_multiturn_continuity_parity_1",
        "targeted_rows": target_summary["durable_rows"],
        "no_context_ambiguity_pass_rate": target_summary["no_context_ambiguity_pass_rate"],
        "seeded_context_binding_pass_rate": target_summary["seeded_context_binding_pass_rate"],
        "real_multiturn_followup_pass_rate": target_summary["real_multiturn_followup_pass_rate"],
        "correction_binding_pass_rate": target_summary["correction_binding_pass_rate"],
        "confirmation_binding_pass_rate": target_summary["confirmation_binding_pass_rate"],
        "generic_provider_fallback_count": target_summary["generic_provider_fallback_count"],
        "context_dependent_generic_provider_fallback_count": target_summary["context_dependent_generic_provider_fallback_count"],
        "native_family_binding_correctness": target_summary["native_family_binding_correctness"],
        "provider_model_calls": target_summary["safety"]["provider_model_calls"],
        "real_external_actions": target_summary["safety"]["real_external_actions"],
        "payload_failures": target_summary["safety"]["payload_failures"],
        "hard_timeouts": target_summary["safety"]["hard_timeouts"],
        "latency_lane": target_summary["latency_lane"],
        "routine_save_blocker_label_preserved_count": target_summary["routine_save_blocker_label_preserved_count"],
        "baseline": target_summary["baseline"],
        "deltas": target_summary["deltas"],
        "success_criteria": {
            "real_multiturn_materially_improved": target_summary["real_multiturn_followup_pass_rate"] > BASELINE["real_multiturn_followup_pass_rate"],
            "seeded_context_not_regressed": target_summary["seeded_context_binding_pass_rate"] >= BASELINE["seeded_context_binding_pass_rate"],
            "no_context_not_regressed": target_summary["no_context_ambiguity_pass_rate"] >= BASELINE["no_context_ambiguity_pass_rate"],
            "generic_provider_remains_zero": target_summary["generic_provider_fallback_count"] == 0,
            "provider_calls_zero": target_summary["safety"]["provider_model_calls"] == 0,
            "external_actions_zero": target_summary["safety"]["real_external_actions"] == 0,
            "payload_failures_zero": target_summary["safety"]["payload_failures"] == 0,
        },
        "final_recommendation": "continue_targeted_multiturn_followup",
    }


def render_real_vs_seeded_diff(audit: dict[str, Any]) -> str:
    lines = [
        "# Real vs Seeded Context Diff",
        "",
        f"- affected rows: {audit['total_affected_rows']}",
        f"- root causes: {json.dumps(audit['root_cause_counts'], sort_keys=True)}",
        "",
        "| test_id | prompt | expected | actual | seeded fields | real fields | root cause | state loss |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in audit["rows"]:
        lines.append(
            "| "
            + " | ".join(
                md_cell(value)
                for value in (
                    row["test_id"],
                    row["prompt"],
                    row["expected"],
                    row["actual"],
                    row["seeded_context_fields_present"],
                    row["real_http_context_fields_present"],
                    row["root_cause"],
                    row["where_state_is_lost_or_altered"],
                )
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_session_contract(contract: dict[str, Any]) -> str:
    lines = ["# Session Continuity Contract", "", "## Required Fields", ""]
    lines.extend(f"- `{field}`" for field in contract["required_continuity_fields"])
    lines.extend(["", "## Rules", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in contract["rules"].items())
    lines.extend(["", "## Non-Goals", ""])
    lines.extend(f"- {item}" for item in contract["non_goals"])
    return "\n".join(lines).rstrip() + "\n"


def render_targeted_multiturn_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Targeted Real Multi-Turn Continuity Results",
        "",
        f"- durable rows: {summary['durable_rows']} / {summary['total_cases']}",
        f"- no-context ambiguity pass rate: {summary['no_context_ambiguity_pass_rate']} (delta {summary['deltas']['no_context_ambiguity_pass_rate']})",
        f"- seeded-context binding pass rate: {summary['seeded_context_binding_pass_rate']} (delta {summary['deltas']['seeded_context_binding_pass_rate']})",
        f"- real multi-turn follow-up pass rate: {summary['real_multiturn_followup_pass_rate']} (delta {summary['deltas']['real_multiturn_followup_pass_rate']})",
        f"- correction binding pass rate: {summary['correction_binding_pass_rate']} (delta {summary['deltas']['correction_binding_pass_rate']})",
        f"- confirmation binding pass rate: {summary['confirmation_binding_pass_rate']} (delta {summary['deltas']['confirmation_binding_pass_rate']})",
        f"- generic-provider fallback count: {summary['generic_provider_fallback_count']}",
        f"- context-dependent generic-provider fallback count: {summary['context_dependent_generic_provider_fallback_count']}",
        f"- native family binding correctness: {summary['native_family_binding_correctness']['correct']}/{summary['native_family_binding_correctness']['total']} ({summary['native_family_binding_correctness']['pass_rate']})",
        f"- provider/model calls: {summary['safety']['provider_model_calls']}",
        f"- real external actions: {summary['safety']['real_external_actions']}",
        f"- payload failures: {summary['safety']['payload_failures']}",
        f"- hard timeouts: {summary['safety']['hard_timeouts']}",
        f"- routine_save blocker label preserved count: {summary['routine_save_blocker_label_preserved_count']}",
        f"- latency lane issue count: {summary['latency_lane']['latency_issue_count']}",
        "",
        "## Lane Pass Rates",
        "",
    ]
    for lane, payload in summary["lane_summary"].items():
        lines.append(f"- {lane}: {payload['context_pass']}/{payload['total']} ({payload['pass_rate']})")
    lines.extend(["", "## Real Multi-Turn Failures", ""])
    for row in summary["real_multiturn_failures"]:
        lines.append(f"- `{row['test_id']}` expected `{row['expected_route_family']}`, actual `{row['actual_route_family']}`: {row['failure_category']}")
    if not summary["real_multiturn_failures"]:
        lines.append("- none")
    lines.extend(["", "## Failure Categories", ""])
    lines.extend(f"- {key}: {value}" for key, value in summary["failure_category_counts"].items())
    return "\n".join(lines).rstrip() + "\n"


def render_final_report(
    summary: dict[str, Any],
    diff_audit: dict[str, Any],
    contract: dict[str, Any],
    target_summary: dict[str, Any],
) -> str:
    lines = [
        "# Real Multi-Turn Continuity Parity Report",
        "",
        f"- phase: `{summary['phase']}`",
        f"- affected diff rows audited: {diff_audit['total_affected_rows']}",
        f"- continuity contract fields: {len(contract['required_continuity_fields'])}",
        f"- final recommendation: `{summary['final_recommendation']}`",
    ]
    if target_summary:
        lines.extend(
            [
                "",
                "## Targeted Evaluation",
                "",
                f"- targeted rows: {summary['targeted_rows']}",
                f"- no-context ambiguity pass rate: {summary['no_context_ambiguity_pass_rate']}",
                f"- seeded-context binding pass rate: {summary['seeded_context_binding_pass_rate']}",
                f"- real multi-turn follow-up pass rate: {summary['real_multiturn_followup_pass_rate']}",
                f"- correction binding pass rate: {summary['correction_binding_pass_rate']}",
                f"- confirmation binding pass rate: {summary['confirmation_binding_pass_rate']}",
                f"- generic-provider fallback count: {summary['generic_provider_fallback_count']}",
                f"- provider/model calls: {summary['provider_model_calls']}",
                f"- real external actions: {summary['real_external_actions']}",
                f"- payload failures: {summary['payload_failures']}",
                f"- hard timeouts: {summary['hard_timeouts']}",
                f"- latency lane issue count: {summary['latency_lane']['latency_issue_count']}",
                "",
                "## Success Criteria",
                "",
            ]
        )
        lines.extend(f"- {key}: {value}" for key, value in summary["success_criteria"].items())
    return "\n".join(lines).rstrip() + "\n"


def md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")[:240]


if __name__ == "__main__":
    main()
