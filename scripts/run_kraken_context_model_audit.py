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
from stormhelm.core.orchestrator.command_eval.corpus import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval.feature_audit import build_feature_audit
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl

import run_250_checkpoint as checkpoint


KRAKEN_DIR = ROOT / ".artifacts" / "command-usability-eval" / "full-1000-kraken"
KRAKEN_RESULTS = KRAKEN_DIR / "1000_kraken_results.jsonl"
KRAKEN_CORPUS = KRAKEN_DIR / "1000_kraken_corpus.jsonl"
OUT = ROOT / ".artifacts" / "command-usability-eval" / "kraken-context-model-audit"
RESULTS_NAME = "targeted_context_model_results.jsonl"
LANES = (
    "no_context_ambiguity",
    "seeded_context_binding",
    "real_multiturn_followup",
    "stale_context_rejection",
    "ambiguous_context_clarification",
    "correction_with_prior_owner",
    "correction_without_prior_owner",
)
PATTERNS = (
    r"\bcan you handle this\??\b",
    r"\bhandle this\b",
    r"\buse this\b",
    r"\buse this for that\b",
    r"\bthat\b",
    r"\bit\b",
    r"\bsame thing\b",
    r"\bdo the same thing as before\b",
    r"\bno,\s*use the other one\b",
    r"\bother one\b",
    r"\byes,\s*go ahead\b",
    r"\bconfirm\b",
)
CONTEXT_RE = re.compile("|".join(PATTERNS), re.IGNORECASE)
CONTEXT_STYLES = {"ambiguous", "deictic", "follow_up", "confirm", "correction"}
NATIVELESS_FAMILIES = {"", "generic_provider", "unsupported", "context_clarification", "legacy_planner"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and run the Kraken context-model targeted lane.")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    kraken_rows = read_jsonl(KRAKEN_RESULTS)
    kraken_corpus_rows = read_jsonl(KRAKEN_CORPUS)
    audit = build_context_row_audit(kraken_rows)
    policy = build_policy()
    write_json(out / "context_dependent_row_audit.json", audit)
    (out / "context_dependent_row_audit.md").write_text(render_row_audit(audit), encoding="utf-8")
    write_json(out / "context_dependent_policy.json", policy)
    (out / "context_dependent_policy.md").write_text(render_policy(policy), encoding="utf-8")

    if args.audit_only:
        summary = build_audit_summary(audit=audit, policy=policy, target_summary={})
        write_json(out / "kraken_context_model_audit_summary.json", summary)
        (out / "kraken_context_model_audit_report.md").write_text(render_final_report(summary, audit, policy, {}), encoding="utf-8")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start targeted context eval with existing command-eval child process: {pre_orphan}")

    cases = build_target_cases(kraken_rows=kraken_rows, kraken_corpus_rows=kraken_corpus_rows)
    write_jsonl(out / "targeted_context_model_corpus.jsonl", [case.to_dict() for case in cases])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=out,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="shared_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(cases, results_name=RESULTS_NAME, resume=False)
    target_rows = read_jsonl(out / RESULTS_NAME)
    post_orphan = checkpoint._orphan_process_check_result()
    target_summary = build_target_summary(
        rows=target_rows,
        total_cases=len(cases),
        pre_orphan=pre_orphan,
        post_orphan=post_orphan,
    )
    write_json(out / "targeted_context_model_summary.json", target_summary)
    (out / "targeted_context_model_report.md").write_text(render_target_report(target_summary, target_rows), encoding="utf-8")
    summary = build_audit_summary(audit=audit, policy=policy, target_summary=target_summary)
    write_json(out / "kraken_context_model_audit_summary.json", summary)
    (out / "kraken_context_model_audit_report.md").write_text(render_final_report(summary, audit, policy, target_summary), encoding="utf-8")
    print(
        json.dumps(
            {
                "targeted_cases": len(results),
                "targeted_rows": len(target_rows),
                "recommendation": summary["final_recommendation"],
                "provider_model_calls": target_summary["safety"]["provider_model_calls"],
                "real_external_actions": target_summary["safety"]["real_external_actions"],
                "generic_provider_fallback_count": target_summary["generic_provider_fallback_count"],
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


def case_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("case")
    return payload if isinstance(payload, dict) else {}


def active_request_state(row: dict[str, Any]) -> dict[str, Any]:
    state = case_payload(row).get("active_request_state")
    return state if isinstance(state, dict) else {}


def input_context(row: dict[str, Any]) -> dict[str, Any]:
    context = case_payload(row).get("input_context")
    return context if isinstance(context, dict) else {}


def workspace_context(row: dict[str, Any]) -> dict[str, Any]:
    context = case_payload(row).get("workspace_context")
    return context if isinstance(context, dict) else {}


def prompt(row: dict[str, Any]) -> str:
    return str(row.get("prompt") or row.get("input") or case_payload(row).get("message") or "")


def wording_style(row: dict[str, Any]) -> str:
    style = str(row.get("wording_style") or "")
    if style:
        return style
    case_id = str(row.get("test_id") or case_payload(row).get("case_id") or "")
    for candidate in CONTEXT_STYLES:
        if f"_{candidate}_" in case_id:
            return candidate
    return ""


def native_active_family(state: dict[str, Any]) -> str:
    family = str(state.get("family") or "").strip()
    return "" if family.lower() in NATIVELESS_FAMILIES else family


def parameters(state: dict[str, Any]) -> dict[str, Any]:
    payload = state.get("parameters")
    return payload if isinstance(payload, dict) else {}


def has_prior_action_or_tool(state: dict[str, Any]) -> bool:
    params = parameters(state)
    return any(params.get(key) not in {None, ""} for key in ("tool_name", "operation_type", "operation", "action", "source_case"))


def has_prior_target_or_entity(row: dict[str, Any]) -> bool:
    state = active_request_state(row)
    params = parameters(state)
    context = input_context(row)
    return bool(
        state.get("subject")
        or params.get("target_name")
        or params.get("path")
        or params.get("destination_alias")
        or context.get("recent_entities")
        or workspace_context(row)
    )


def has_alternate_target(row: dict[str, Any]) -> bool:
    state = active_request_state(row)
    params = parameters(state)
    context = input_context(row)
    entities = context.get("recent_entities") if isinstance(context.get("recent_entities"), list) else []
    choices = params.get("ambiguity_choices") if isinstance(params.get("ambiguity_choices"), list) else []
    return bool(params.get("alternate_target") or len(entities) > 1 or len(choices) > 1)


def has_selected_or_current_context(row: dict[str, Any]) -> bool:
    context = input_context(row)
    return bool(
        context.get("selection")
        or context.get("highlighted")
        or context.get("current_resolution")
        or context.get("visible_ui")
        or context.get("recent_entities")
        or workspace_context(row)
    )


def context_freshness(row: dict[str, Any]) -> str:
    state = active_request_state(row)
    params = parameters(state)
    context = input_context(row)
    values: list[str] = []
    if params.get("context_freshness"):
        values.append(str(params["context_freshness"]))
    entities = context.get("recent_entities") if isinstance(context.get("recent_entities"), list) else []
    for entity in entities:
        if isinstance(entity, dict) and entity.get("freshness"):
            values.append(str(entity["freshness"]))
    if any(value.lower() == "stale" for value in values):
        return "stale"
    if any(value.lower() in {"current", "fresh", "active"} for value in values):
        return "current"
    if state or context or workspace_context(row):
        return "unspecified"
    return "none"


def has_pending_confirmation(row: dict[str, Any]) -> bool:
    state = active_request_state(row)
    params = parameters(state)
    stage = str(params.get("request_stage") or "").strip().lower()
    return bool(params.get("pending_preview") or state.get("trust") or stage in {"preview", "awaiting_confirmation"})


def classify_lane(row: dict[str, Any]) -> str:
    text = prompt(row).lower()
    style = wording_style(row)
    state = active_request_state(row)
    active_family = native_active_family(state)
    freshness = context_freshness(row)
    if freshness == "stale":
        return "stale_context_rejection"
    if "other one" in text or style == "correction":
        return "correction_with_prior_owner" if active_family else "correction_without_prior_owner"
    if "yes" in text and "go ahead" in text or "confirm" in text:
        return "seeded_context_binding" if has_pending_confirmation(row) and active_family else "no_context_ambiguity"
    if style == "follow_up" or "same thing" in text:
        if str(row.get("history_strategy") or "") == "shared_session" and int(case_payload(row).get("turn_index") or 0) > 0:
            return "real_multiturn_followup"
        return "seeded_context_binding" if active_family else "no_context_ambiguity"
    if style == "deictic" or "use this" in text or "that" in text or " it" in f" {text}":
        if active_family:
            return "seeded_context_binding"
        return "ambiguous_context_clarification" if has_selected_or_current_context(row) else "no_context_ambiguity"
    if "handle this" in text:
        return "seeded_context_binding" if active_family and has_prior_target_or_entity(row) else "no_context_ambiguity"
    return "no_context_ambiguity"


def expectation_valid_without_context(row: dict[str, Any], lane: str) -> bool:
    expected = str(row.get("expected_route_family") or "")
    if lane in {"no_context_ambiguity", "correction_without_prior_owner", "ambiguous_context_clarification", "stale_context_rejection"}:
        return expected == "context_clarification"
    return bool(expected and expected != "context_clarification")


def build_context_row_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    context_rows: list[dict[str, Any]] = []
    for row in rows:
        text = prompt(row)
        if not CONTEXT_RE.search(text):
            continue
        state = active_request_state(row)
        active_family = native_active_family(state)
        lane = classify_lane(row)
        context_rows.append(
            {
                "test_id": row.get("test_id"),
                "prompt": text,
                "expected_family": row.get("expected_route_family"),
                "actual_family": row.get("actual_route_family"),
                "routing_engine": row.get("routing_engine"),
                "wording_style": wording_style(row),
                "history_strategy": row.get("history_strategy"),
                "active_request_state_present": bool(state),
                "prior_route_family_present": bool(active_family),
                "prior_action_tool_present": has_prior_action_or_tool(state),
                "prior_target_entity_present": has_prior_target_or_entity(row),
                "alternate_target_present": has_alternate_target(row),
                "selected_highlighted_current_context_present": has_selected_or_current_context(row),
                "context_freshness": context_freshness(row),
                "expectation_valid_without_context": expectation_valid_without_context(row, lane),
                "correct_evaluation_lane": lane,
                "provider_called": bool(row.get("provider_called")),
                "generic_provider_selected": row.get("actual_route_family") == "generic_provider",
                "failure_category": row.get("failure_category"),
                "passed": bool(row.get("passed")),
            }
        )
    return {
        "source_results": rel(KRAKEN_RESULTS),
        "source_corpus": rel(KRAKEN_CORPUS),
        "total_context_dependent_rows": len(context_rows),
        "plain_isolated_no_seed_count": sum(1 for row in context_rows if row["correct_evaluation_lane"] == "no_context_ambiguity"),
        "seeded_context_count": sum(1 for row in context_rows if row["prior_route_family_present"] or row["selected_highlighted_current_context_present"]),
        "lane_counts": dict(sorted(Counter(row["correct_evaluation_lane"] for row in context_rows).items())),
        "invalid_without_context_count": sum(1 for row in context_rows if not row["expectation_valid_without_context"]),
        "generic_provider_selected_count": sum(1 for row in context_rows if row["generic_provider_selected"]),
        "rows": context_rows,
    }


def build_policy() -> dict[str, Any]:
    return {
        "no_context": {
            "can you handle this?": "context_clarification",
            "use this for that": "context_clarification",
            "no, use the other one": "context_clarification",
            "yes, go ahead": "no_pending_confirmation_or_context_clarification",
            "approval_policy": "Do not treat yes/go ahead as approval without a pending approval or preview object.",
        },
        "fresh_prior_native_owner": {
            "do the same thing as before": "bind_to_prior_native_family",
            "can you handle this?": "bind_only_when_this_has_clear_prior_or_current_target",
            "no, use the other one": "prior_family_clarification_or_alternate_target_selection_when_seeded",
            "yes, go ahead": "confirmation_only_when_pending_approval_or_preview_exists",
        },
        "stale_or_ambiguous_context": {
            "behavior": "clarify_do_not_guess",
            "generic_provider_policy": "generic_provider must not win when a native clarification lane exists",
        },
        "required_context_lanes": list(LANES),
        "safety": {
            "provider_openai_llm_embedding_calls": 0,
            "real_external_actions": 0,
            "dry_run_required": True,
        },
    }


def build_target_cases(*, kraken_rows: list[dict[str, Any]], kraken_corpus_rows: list[dict[str, Any]]) -> list[CommandEvalCase]:
    current_cases = {case.case_id: case for case in build_command_usability_corpus(min_cases=1000)}
    kraken_context_ids = {
        str(row.get("test_id") or "")
        for row in kraken_rows
        if wording_style(row) in CONTEXT_STYLES or CONTEXT_RE.search(prompt(row))
    }
    selected: list[CommandEvalCase] = []
    for corpus_row in kraken_corpus_rows:
        case_id = str(corpus_row.get("case_id") or "")
        if case_id in kraken_context_ids and case_id in current_cases:
            selected.append(_target_copy(current_cases[case_id], session_id=f"target-{case_id}"))

    selected.extend(_custom_target_cases())
    for canary_id in (
        "calculations_canonical_00",
        "browser_destination_canonical_00",
        "file_external_canonical_00",
        "software_control_install_canonical_00",
        "routine_execute_canonical_00",
        "workspace_save_canonical_00",
        "network_status_canonical_00",
        "context_action_canonical_00",
        "trust_approval_canonical_00",
        "screen_awareness_canonical_00",
    ):
        case = current_cases.get(canary_id)
        if case is not None:
            selected.append(_target_copy(case, session_id=f"canary-{canary_id}"))
    return selected


def _target_copy(case: CommandEvalCase, *, session_id: str) -> CommandEvalCase:
    return replace(case, session_id=session_id)


def _custom_target_cases() -> list[CommandEvalCase]:
    cases = [
        _case("context_no_owner_can_handle_this", "can you handle this?", "context_clarification", "context", context_lane="no_context_ambiguity", clarification="expected"),
        _case("context_no_owner_other_one", "no, use the other one", "context_clarification", "context", context_lane="correction_without_prior_owner", clarification="expected"),
        _case("context_no_pending_yes_go_ahead", "yes, go ahead", "context_clarification", "context", context_lane="no_context_ambiguity", clarification="expected"),
        _case(
            "context_seeded_software_can_handle_this",
            "can you handle this?",
            "software_control",
            "software_control",
            context_lane="seeded_context_binding",
            active_request_state={
                "family": "software_control",
                "subject": "Firefox",
                "parameters": {
                    "operation_type": "install",
                    "target_name": "Firefox",
                    "request_stage": "preview",
                    "context_freshness": "current",
                },
            },
            expected_prior_family="software_control",
            expected_target_binding="active_request_state.parameters.target_name",
            approval="expected_or_preview",
        ),
        _case(
            "context_seeded_browser_other_one",
            "no, use the other one",
            "browser_destination",
            "browser",
            tools=("external_open_url",),
            context_lane="correction_with_prior_owner",
            input_context={
                "recent_entities": [
                    {"kind": "page", "title": "Stormhelm docs", "url": "https://docs.example.com/stormhelm", "freshness": "current"},
                    {"kind": "page", "title": "Example", "url": "https://example.com", "freshness": "current"},
                ]
            },
            active_request_state={
                "family": "browser_destination",
                "subject": "YouTube",
                "parameters": {
                    "source_case": "browser_destination",
                    "tool_name": "external_open_url",
                    "previous_choice": "YouTube",
                    "alternate_target": "Stormhelm docs",
                    "request_stage": "preview",
                    "context_freshness": "current",
                },
            },
            expected_prior_family="browser_destination",
            expected_prior_tool="external_open_url",
            expected_target_binding="input_context.recent_entities",
            expected_alternate_target="Stormhelm docs",
            approval="allowed",
        ),
        _case(
            "context_seeded_file_same_before",
            "do the same thing as before",
            "file",
            "files",
            tools=("external_open_file",),
            context_lane="seeded_context_binding",
            active_request_state={
                "family": "file",
                "subject": str(ROOT / "README.md"),
                "parameters": {
                    "source_case": "file_external",
                    "tool_name": "external_open_file",
                    "path": str(ROOT / "README.md"),
                    "request_stage": "preview",
                    "context_freshness": "current",
                },
            },
            expected_prior_family="file",
            expected_prior_tool="external_open_file",
            expected_target_binding="active_request_state.parameters.path",
            approval="allowed",
        ),
        _case(
            "context_seeded_discord_yes_go_ahead",
            "yes, go ahead",
            "trust_approvals",
            "trust",
            context_lane="seeded_context_binding",
            active_request_state={
                "family": "discord_relay",
                "subject": "Baby",
                "parameters": {
                    "destination_alias": "Baby",
                    "payload_hint": "selected_text",
                    "pending_preview": {"preview_id": "relay-preview-1", "route_mode": "local_client_automation"},
                    "request_stage": "awaiting_confirmation",
                    "context_freshness": "current",
                },
                "trust": {"request_id": "relay-trust-1", "reason": "Discord relay requires preview."},
            },
            expected_prior_family="discord_relay",
            expected_context_source="active_request_state",
            expected_confirmation_state="pending_approval",
            approval="allowed",
        ),
        _case(
            "context_stale_prior_same_before",
            "do the same thing as before",
            "browser_destination",
            "browser",
            context_lane="stale_context_rejection",
            active_request_state={
                "family": "browser_destination",
                "subject": "Old docs",
                "parameters": {
                    "source_case": "browser_destination",
                    "tool_name": "external_open_url",
                    "request_stage": "preview",
                    "context_freshness": "stale",
                },
            },
            expected_prior_family="browser_destination",
            clarification="expected",
        ),
        _case(
            "context_conflicting_use_this_for_that",
            "use this for that",
            "context_clarification",
            "context",
            context_lane="ambiguous_context_clarification",
            input_context={
                "selection": {"kind": "text", "value": "Selected text", "preview": "Selected text"},
                "recent_entities": [
                    {"kind": "page", "title": "Stormhelm docs", "url": "https://docs.example.com/stormhelm", "freshness": "current"},
                    {"kind": "file", "title": "README.md", "path": str(ROOT / "README.md"), "freshness": "current"},
                ],
            },
            clarification="expected",
        ),
    ]
    cases.extend(_real_multiturn_cases())
    return cases


def _real_multiturn_cases() -> list[CommandEvalCase]:
    return [
        _case("mt_browser_setup", "open https://example.com", "browser_destination", "browser", tools=("external_open_url",), session_id="mt-browser", approval="allowed", context_lane="not_context_dependent"),
        _case("mt_browser_followup", "do the same thing as before", "browser_destination", "browser", tools=("external_open_url",), context_lane="real_multiturn_followup", session_id="mt-browser", turn_index=1, seeded_context_required=True, expected_prior_family="browser_destination", expected_prior_tool="external_open_url", expected_behavior_without_context="context_clarification", approval="allowed"),
        _case("mt_file_setup", f"open {ROOT / 'README.md'} externally", "file", "files", tools=("external_open_file",), session_id="mt-file", approval="allowed", context_lane="not_context_dependent"),
        _case("mt_file_followup", "do the same thing as before", "file", "files", tools=("external_open_file",), context_lane="real_multiturn_followup", session_id="mt-file", turn_index=1, seeded_context_required=True, expected_prior_family="file", expected_prior_tool="external_open_file", expected_behavior_without_context="context_clarification", approval="allowed"),
        _case("mt_software_setup", "install Firefox", "software_control", "software_control", session_id="mt-software", approval="expected_or_preview", context_lane="not_context_dependent"),
        _case("mt_software_followup", "can you handle this?", "software_control", "software_control", context_lane="real_multiturn_followup", session_id="mt-software", turn_index=1, seeded_context_required=True, expected_prior_family="software_control", expected_behavior_without_context="context_clarification", approval="expected_or_preview"),
        _case("mt_discord_setup", "send this to Baby on Discord", "discord_relay", "discord_relay", session_id="mt-discord", input_context={"selection": {"kind": "text", "value": "Selected relay text", "preview": "Selected relay text"}}, approval="allowed", context_lane="not_context_dependent"),
        _case("mt_discord_followup", "yes, go ahead", "trust_approvals", "trust", context_lane="real_multiturn_followup", session_id="mt-discord", turn_index=1, seeded_context_required=True, expected_prior_family="discord_relay", expected_behavior_without_context="context_clarification", approval="allowed"),
        _case("mt_workspace_setup", "save this workspace", "workspace_operations", "workspace", tools=("workspace_save",), session_id="mt-workspace", workspace_context=_docs_workspace(), context_lane="not_context_dependent"),
        _case("mt_workspace_followup", "do the same thing as before", "workspace_operations", "workspace", tools=("workspace_save",), context_lane="real_multiturn_followup", session_id="mt-workspace", turn_index=1, seeded_context_required=True, expected_prior_family="workspace_operations", expected_prior_tool="workspace_save", expected_behavior_without_context="context_clarification"),
        _case("mt_routine_setup", "run my cleanup routine", "routine", "routine", tools=("routine_execute",), session_id="mt-routine", context_lane="not_context_dependent"),
        _case("mt_routine_followup", "do the same thing as before", "routine", "routine", tools=("routine_execute",), context_lane="real_multiturn_followup", session_id="mt-routine", turn_index=1, seeded_context_required=True, expected_prior_family="routine", expected_prior_tool="routine_execute", expected_behavior_without_context="context_clarification", approval="allowed"),
    ]


def _case(
    case_id: str,
    message: str,
    route_family: str,
    subsystem: str,
    *,
    tools: tuple[str, ...] = (),
    input_context: dict[str, Any] | None = None,
    active_request_state: dict[str, Any] | None = None,
    workspace_context: dict[str, Any] | None = None,
    context_lane: str,
    session_id: str | None = None,
    turn_index: int = 0,
    seeded_context_required: bool | None = None,
    expected_context_source: str = "",
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
        session_id=session_id or f"target-{case_id}",
        input_context=input_context or {},
        active_request_state=active_request_state or {},
        workspace_context=workspace_context or {},
        context_lane=context_lane,
        seeded_context_required=bool(seeded_context_required if seeded_context_required is not None else context_lane not in {"not_context_dependent", "no_context_ambiguity", "correction_without_prior_owner"}),
        expected_context_source=expected_context_source or ("active_request_state" if active_request_state else "input_context" if input_context else "workspace_context" if workspace_context else "none"),
        expected_prior_family=expected_prior_family,
        expected_prior_tool=expected_prior_tool,
        expected_target_binding=expected_target_binding,
        expected_alternate_target=expected_alternate_target,
        expected_confirmation_state=expected_confirmation_state,
        expected_behavior_without_context=expected_behavior_without_context or ("context_clarification" if context_lane != "not_context_dependent" else ""),
        turn_index=turn_index,
        tags=("kraken_context_model_targeted", context_lane),
    )


def _docs_workspace() -> dict[str, Any]:
    return {"workspace": {"workspaceId": "ws-docs", "name": "Docs Workspace", "topic": "Stormhelm docs"}, "module": "chartroom"}


def assertion_context_pass(row: dict[str, Any]) -> bool:
    assertions = row.get("assertions") if isinstance(row.get("assertions"), dict) else {}
    required = ("route_family", "subsystem", "tool_chain", "clarification", "approval", "provider_usage", "payload_guardrail", "no_overclaim")
    for key in required:
        item = assertions.get(key)
        if isinstance(item, dict) and not bool(item.get("passed")):
            return False
    return not bool(row.get("external_action_performed"))


def build_target_summary(*, rows: list[dict[str, Any]], total_cases: int, pre_orphan: str, post_orphan: str) -> dict[str, Any]:
    lane_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        lane = str(row.get("context_lane") or case_payload(row).get("context_lane") or "not_context_dependent")
        lane_rows[lane].append(row)
    lane_summary = {
        lane: {
            "total": len(items),
            "context_pass": sum(1 for item in items if assertion_context_pass(item)),
            "context_fail": sum(1 for item in items if not assertion_context_pass(item)),
            "pass_rate": rate(sum(1 for item in items if assertion_context_pass(item)), len(items)),
        }
        for lane, items in sorted(lane_rows.items())
    }
    provider_calls = sum(int(row.get("provider_call_count") or 0) for row in rows)
    openai_calls = sum(int(row.get("openai_call_count") or 0) for row in rows)
    llm_calls = sum(int(row.get("llm_call_count") or 0) for row in rows)
    embedding_calls = sum(int(row.get("embedding_call_count") or 0) for row in rows)
    real_external_actions = sum(1 for row in rows if row.get("external_action_performed"))
    generic_provider_rows = [row for row in rows if row.get("actual_route_family") == "generic_provider"]
    context_acceptance = [
        row
        for row in rows
        if row.get("expected_route_family") == "context_clarification"
        and row.get("actual_route_family") == "context_clarification"
        and assertion_context_pass(row)
    ]
    native_binding_rows = [
        row
        for row in rows
        if str(row.get("context_lane") or "") in {"seeded_context_binding", "correction_with_prior_owner", "real_multiturn_followup"}
        and str(row.get("expected_route_family") or "") not in {"context_clarification", "generic_provider", "unsupported"}
    ]
    native_binding_correct = sum(1 for row in native_binding_rows if row.get("actual_route_family") == row.get("expected_route_family"))
    confirmation_rows = [
        row
        for row in rows
        if "yes" in str(row.get("prompt") or "").lower()
        or str(row.get("expected_confirmation_state") or case_payload(row).get("expected_confirmation_state") or "")
    ]
    summary = {
        "total_cases": total_cases,
        "durable_rows": len(rows),
        "pre_orphan_process_check": pre_orphan,
        "post_orphan_process_check": post_orphan,
        "lane_summary": lane_summary,
        "no_context_ambiguity_pass_rate": lane_summary.get("no_context_ambiguity", {}).get("pass_rate", 0.0),
        "seeded_context_binding_pass_rate": lane_summary.get("seeded_context_binding", {}).get("pass_rate", 0.0),
        "real_multiturn_followup_pass_rate": lane_summary.get("real_multiturn_followup", {}).get("pass_rate", 0.0),
        "correction_binding_pass_rate": lane_summary.get("correction_with_prior_owner", {}).get("pass_rate", 0.0),
        "confirmation_binding_pass_rate": rate(sum(1 for row in confirmation_rows if assertion_context_pass(row)), len(confirmation_rows)),
        "generic_provider_fallback_count": len(generic_provider_rows),
        "generic_provider_fallback_examples": compact_rows(generic_provider_rows[:20]),
        "context_clarification_acceptance_count": len(context_acceptance),
        "native_family_binding_correctness": {
            "correct": native_binding_correct,
            "total": len(native_binding_rows),
            "pass_rate": rate(native_binding_correct, len(native_binding_rows)),
        },
        "failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in rows).items())),
        "context_failures": compact_rows([row for row in rows if not assertion_context_pass(row)][:40]),
        "safety": {
            "provider_model_calls": provider_calls + openai_calls + llm_calls + embedding_calls,
            "provider_calls": provider_calls,
            "openai_calls": openai_calls,
            "llm_calls": llm_calls,
            "embedding_calls": embedding_calls,
            "real_external_actions": real_external_actions,
            "payload_failures": sum(1 for row in rows if _payload_guardrail_failed(row)),
            "payload_guardrail_triggered_rows": sum(1 for row in rows if row.get("payload_guardrail_triggered")),
            "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout"),
            "process_kills": sum(1 for row in rows if row.get("process_killed")),
        },
        "routine_save_blocker_label_preserved_count": sum(1 for row in rows if "known_unreproduced_product_latency_blocker" in row.get("historical_blocker_labels", [])),
    }
    return summary


def _payload_guardrail_failed(row: dict[str, Any]) -> bool:
    if row.get("failure_category") == "payload_guardrail_failure":
        return True
    assertions = row.get("assertions") if isinstance(row.get("assertions"), dict) else {}
    payload_assertion = assertions.get("payload_guardrail")
    return isinstance(payload_assertion, dict) and not bool(payload_assertion.get("passed"))


def build_audit_summary(*, audit: dict[str, Any], policy: dict[str, Any], target_summary: dict[str, Any]) -> dict[str, Any]:
    recommendation = "stop_manual_review"
    if target_summary:
        safety = target_summary.get("safety", {})
        context_failures = sum(1 for lane in target_summary.get("lane_summary", {}).values() if lane.get("context_fail"))
        if safety.get("provider_model_calls") or safety.get("real_external_actions") or safety.get("payload_failures") or safety.get("hard_timeouts"):
            recommendation = "continue_targeted_followup"
        elif target_summary.get("generic_provider_fallback_count") or context_failures:
            recommendation = "continue_targeted_followup"
        elif target_summary.get("failure_category_counts", {}).get("latency_issue"):
            recommendation = "fix_latency_lane"
        else:
            recommendation = "run_second_1000_after_context_repairs"
    return {
        "source_results": audit["source_results"],
        "total_context_dependent_rows_audited": audit["total_context_dependent_rows"],
        "lane_counts": audit["lane_counts"],
        "invalid_without_context_count": audit["invalid_without_context_count"],
        "plain_isolated_no_seed_count": audit["plain_isolated_no_seed_count"],
        "seeded_context_count": audit["seeded_context_count"],
        "targeted_summary_available": bool(target_summary),
        "targeted_summary": target_summary,
        "policy_required_lanes": policy["required_context_lanes"],
        "final_recommendation": recommendation,
    }


def compact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "test_id": row.get("test_id"),
            "prompt": row.get("prompt"),
            "context_lane": row.get("context_lane") or case_payload(row).get("context_lane"),
            "expected_route_family": row.get("expected_route_family"),
            "actual_route_family": row.get("actual_route_family"),
            "routing_engine": row.get("routing_engine"),
            "failure_category": row.get("failure_category"),
            "failure_reason": row.get("failure_reason"),
        }
        for row in rows
    ]


def render_row_audit(audit: dict[str, Any]) -> str:
    lines = [
        "# Kraken Context-Dependent Row Audit",
        "",
        f"- source results: `{audit['source_results']}`",
        f"- source corpus: `{audit['source_corpus']}`",
        f"- audited rows: {audit['total_context_dependent_rows']}",
        f"- plain isolated/no-seed rows: {audit['plain_isolated_no_seed_count']}",
        f"- seeded-context rows: {audit['seeded_context_count']}",
        f"- invalid-without-context expectations: {audit['invalid_without_context_count']}",
        f"- generic-provider selected rows: {audit['generic_provider_selected_count']}",
        "",
        "## Lane Counts",
        "",
        *[f"- {lane}: {count}" for lane, count in audit["lane_counts"].items()],
        "",
        "## Rows",
        "",
        "| test_id | prompt | expected | actual | engine | style | history | active | prior_family | prior_tool | prior_target | alternate | selected/current | freshness | valid_without_context | lane |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in audit["rows"]:
        lines.append(
            "| {test_id} | {prompt} | {expected_family} | {actual_family} | {routing_engine} | {wording_style} | {history_strategy} | {active_request_state_present} | {prior_route_family_present} | {prior_action_tool_present} | {prior_target_entity_present} | {alternate_target_present} | {selected_highlighted_current_context_present} | {context_freshness} | {expectation_valid_without_context} | {correct_evaluation_lane} |".format(
                **{key: md_cell(value) for key, value in row.items()}
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def render_policy(policy: dict[str, Any]) -> str:
    lines = [
        "# Context-Dependent Evaluation Policy",
        "",
        "## No Context",
        "",
    ]
    lines.extend(f"- `{key}` -> {value}" for key, value in policy["no_context"].items())
    lines.extend(["", "## Fresh Prior Native Owner", ""])
    lines.extend(f"- `{key}` -> {value}" for key, value in policy["fresh_prior_native_owner"].items())
    lines.extend(["", "## Stale Or Ambiguous Prior Context", ""])
    lines.extend(f"- {key}: {value}" for key, value in policy["stale_or_ambiguous_context"].items())
    lines.extend(["", "## Lanes", ""])
    lines.extend(f"- `{lane}`" for lane in policy["required_context_lanes"])
    lines.extend(["", "## Safety", ""])
    lines.extend(f"- {key}: {value}" for key, value in policy["safety"].items())
    return "\n".join(lines).rstrip() + "\n"


def render_target_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Targeted Context Model Results",
        "",
        f"- durable rows: {summary['durable_rows']} / {summary['total_cases']}",
        f"- generic-provider fallback count: {summary['generic_provider_fallback_count']}",
        f"- context clarification acceptance count: {summary['context_clarification_acceptance_count']}",
        f"- provider/model calls: {summary['safety']['provider_model_calls']}",
        f"- real external actions: {summary['safety']['real_external_actions']}",
        f"- payload failures: {summary['safety']['payload_failures']}",
        f"- routine_save blocker label preserved count: {summary['routine_save_blocker_label_preserved_count']}",
        "",
        "## Lane Pass Rates",
        "",
    ]
    for lane, payload in summary["lane_summary"].items():
        lines.append(f"- {lane}: {payload['context_pass']}/{payload['total']} ({payload['pass_rate']})")
    lines.extend(
        [
            "",
            "## Required Metrics",
            "",
            f"- no-context ambiguity pass rate: {summary['no_context_ambiguity_pass_rate']}",
            f"- seeded-context binding pass rate: {summary['seeded_context_binding_pass_rate']}",
            f"- real multi-turn follow-up pass rate: {summary['real_multiturn_followup_pass_rate']}",
            f"- correction binding pass rate: {summary['correction_binding_pass_rate']}",
            f"- confirmation binding pass rate: {summary['confirmation_binding_pass_rate']}",
            f"- native family binding correctness: {summary['native_family_binding_correctness']['correct']}/{summary['native_family_binding_correctness']['total']} ({summary['native_family_binding_correctness']['pass_rate']})",
            "",
            "## Failure Categories",
            "",
        ]
    )
    lines.extend(f"- {key}: {value}" for key, value in summary["failure_category_counts"].items())
    lines.extend(["", "## Context Failures", ""])
    for row in summary["context_failures"]:
        lines.append(f"- `{row['test_id']}` `{row['context_lane']}` expected `{row['expected_route_family']}`, actual `{row['actual_route_family']}` via `{row['routing_engine']}`: {row['failure_category']}")
    if not summary["context_failures"]:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def render_final_report(summary: dict[str, Any], audit: dict[str, Any], policy: dict[str, Any], target_summary: dict[str, Any]) -> str:
    lines = [
        "# Kraken Context Model Audit Report",
        "",
        f"- audited context-dependent Kraken rows: {audit['total_context_dependent_rows']}",
        f"- invalid without-context expectations found: {audit['invalid_without_context_count']}",
        f"- policy lanes defined: {', '.join(policy['required_context_lanes'])}",
        f"- final recommendation: `{summary['final_recommendation']}`",
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
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def md_cell(value: Any) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")[:180]


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except Exception:
        return str(path)


if __name__ == "__main__":
    main()
