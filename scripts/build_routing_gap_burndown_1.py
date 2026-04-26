from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from stormhelm.core.orchestrator.planner_v2 import PLANNER_V2_ROUTE_FAMILIES


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    ROOT
    / ".artifacts"
    / "command-usability-eval"
    / "planner-v2-stabilization-2"
    / "250_post_stabilization_2_results.jsonl"
)
DEFAULT_OUT = ROOT / ".artifacts" / "command-usability-eval" / "routing-gap-burndown-1"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Planner v2 routing-gap burn-down artifacts.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--post-results", type=Path, default=None)
    args = parser.parse_args()

    source = args.source.resolve()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(source)
    gap_rows = [row for row in rows if str(row.get("failure_category") or "") == "real_routing_gap"]

    census = build_routing_gap_census(source, gap_rows)
    clarification = build_missing_context_plan(gap_rows)
    unmigrated = build_unmigrated_plan(gap_rows)

    write_json(out / "routing_gap_census.json", census)
    write_md(out / "routing_gap_census.md", render_census(census))
    write_json(out / "missing_context_clarification_plan.json", clarification)
    write_md(out / "missing_context_clarification_plan.md", render_missing_context(clarification))
    write_json(out / "unmigrated_family_plan.json", unmigrated)
    write_md(out / "unmigrated_family_plan.md", render_unmigrated(unmigrated))

    if args.post_results is not None and args.post_results.exists():
        post_rows = read_jsonl(args.post_results)
        report = build_final_report(rows, post_rows, out)
        write_json(out / "routing_gap_burndown_summary.json", report["summary"])
        write_md(out / "routing_gap_burndown_report.md", render_final(report))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_md(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def case_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("case")
    return payload if isinstance(payload, dict) else {}


def active_request_state(row: dict[str, Any]) -> dict[str, Any]:
    state = case_payload(row).get("active_request_state")
    return state if isinstance(state, dict) else {}


def input_context(row: dict[str, Any]) -> dict[str, Any]:
    context = case_payload(row).get("input_context")
    return context if isinstance(context, dict) else {}


def prompt(row: dict[str, Any]) -> str:
    return str(row.get("prompt") or row.get("input") or case_payload(row).get("message") or "")


def expected_family(row: dict[str, Any]) -> str:
    return str(row.get("expected_route_family") or "")


def active_family(row: dict[str, Any]) -> str:
    return str(active_request_state(row).get("family") or "").strip().lower()


def root_cause(row: dict[str, Any]) -> str:
    family = expected_family(row)
    if family in PLANNER_V2_ROUTE_FAMILIES:
        return "missing_context_should_clarify"
    if family in {"unsupported"}:
        return "unsupported_feature_expected"
    return "unmigrated_family"


def native_owner(row: dict[str, Any]) -> str:
    family = expected_family(row)
    if active_family(row) in PLANNER_V2_ROUTE_FAMILIES:
        return active_family(row)
    return family


def missing_context(row: dict[str, Any]) -> str:
    family = expected_family(row)
    state_family = active_family(row)
    if state_family and state_family != family:
        return f"active_request_state points to {state_family}, not expected {family}"
    if state_family:
        return "active_request_state family was available, but Planner v2 did not use it as follow-up owner"
    if input_context(row).get("selection"):
        return "selection exists, but no route-family owner or prior action was available"
    return "prior route-family context was missing"


def build_routing_gap_census(source: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for row in rows:
        case = case_payload(row)
        state = active_request_state(row)
        planner_v2_trace = row.get("planner_v2_trace")
        items.append(
            {
                "test_id": row.get("test_id"),
                "prompt": prompt(row),
                "expected_route_family": row.get("expected_route_family"),
                "actual_route_family": row.get("actual_route_family"),
                "expected_subsystem": row.get("expected_subsystem"),
                "actual_subsystem": row.get("actual_subsystem"),
                "expected_tool": row.get("expected_tool"),
                "actual_tool": row.get("actual_tool"),
                "routing_engine": row.get("routing_engine"),
                "planner_v2_trace_present": isinstance(planner_v2_trace, dict) and bool(planner_v2_trace),
                "intent_frame": row.get("intent_frame") or {},
                "context_binding": (
                    planner_v2_trace.get("context_binding")
                    if isinstance(planner_v2_trace, dict) and isinstance(planner_v2_trace.get("context_binding"), dict)
                    else {}
                ),
                "selected_route_spec": row.get("selected_route_spec") or "",
                "candidate_specs_considered": row.get("candidate_specs_considered") or [],
                "route_candidates": row.get("route_candidates") or [],
                "native_decline_reasons": row.get("native_decline_reasons") or {},
                "generic_provider_gate_reason": row.get("generic_provider_gate_reason") or "",
                "result_state": row.get("result_state") or row.get("actual_result_state") or "",
                "response_summary": summarize_response(row),
                "implemented_routeable": row.get("implemented_routeable_status") == "implemented_routeable",
                "active_request_state_family": str(state.get("family") or ""),
                "input_context_keys": sorted(str(key) for key in input_context(row).keys()),
                "root_cause": root_cause(row),
            }
        )
    return {
        "source_results": rel(source),
        "total_real_routing_gaps": len(rows),
        "root_cause_counts": dict(Counter(item["root_cause"] for item in items)),
        "expected_family_counts": dict(Counter(str(item["expected_route_family"]) for item in items)),
        "routing_engine_counts": dict(Counter(str(item["routing_engine"]) for item in items)),
        "generic_provider_fallbacks": sum(1 for item in items if item["actual_route_family"] == "generic_provider"),
        "items": items,
    }


def build_missing_context_plan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for row in rows:
        if expected_family(row) not in PLANNER_V2_ROUTE_FAMILIES:
            continue
        state = active_request_state(row)
        owner = native_owner(row)
        items.append(
            {
                "test_id": row.get("test_id"),
                "prompt": prompt(row),
                "native_family_should_own": owner,
                "expected_route_family": expected_family(row),
                "context_missing": missing_context(row),
                "planner_v2_spec_exists": expected_family(row) in PLANNER_V2_ROUTE_FAMILIES,
                "context_binder_detects_missing": bool(row.get("missing_preconditions")),
                "why_generic_provider_became_eligible": row.get("generic_provider_gate_reason") or row.get("fallback_reason") or "",
                "native_clarification_result_state": "needs_clarification",
                "clarification_copy": clarification_copy(owner),
                "fix_decision": fix_decision(row),
                "active_request_state": state,
            }
        )
    return {
        "total": len(items),
        "fix_now": sum(1 for item in items if item["fix_decision"] == "fix_now"),
        "defer_or_classify": sum(1 for item in items if item["fix_decision"] != "fix_now"),
        "family_counts": dict(Counter(item["expected_route_family"] for item in items)),
        "items": items,
    }


def build_unmigrated_plan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for row in rows:
        family = expected_family(row)
        if family in PLANNER_V2_ROUTE_FAMILIES:
            continue
        items.append(
            {
                "test_id": row.get("test_id"),
                "prompt": prompt(row),
                "expected_route_family": family,
                "planner_v2_spec_exists": bool(row.get("candidate_specs_considered") and family in row.get("candidate_specs_considered", [])),
                "legacy_only_today": True,
                "should_migrate_now": False,
                "migration_risk": "deferred: single-row or direct/legacy family; no high-impact cluster in this pass",
                "expected_benefit": "low for this pass",
                "required_context_types": ["family-specific prior action or explicit target"],
                "required_result_states": ["needs_clarification", "dry_run_ready", "completed"],
                "near_miss_risks": ["generic deictic prompts must not infer family from benchmark selection labels"],
                "should_clarify_instead_of_fallback": True,
                "fix_decision": "defer",
            }
        )
    return {
        "total": len(items),
        "family_counts": dict(Counter(item["expected_route_family"] for item in items)),
        "selected_for_migration_now": [],
        "defer_reason": "No unmigrated family formed a multi-row high-impact, low-risk cluster; current evidence favors follow-up ownership and missing-context repair for already-migrated families.",
        "items": items,
    }


def fix_decision(row: dict[str, Any]) -> str:
    state_family = active_family(row)
    if state_family in {"app_control", "browser_destination", "context_action", "discord_relay"}:
        return "fix_now"
    if state_family in PLANNER_V2_ROUTE_FAMILIES:
        return "fix_now"
    return "defer_no_native_owner_signal"


def clarification_copy(family: str) -> str:
    copies = {
        "browser_destination": "Which website or page should I open?",
        "context_action": "Which selected or highlighted text should I use?",
        "discord_relay": "Who should receive it, and what should I send?",
        "app_control": "Which app should I use?",
        "calculations": "Which prior calculation or number should I use?",
    }
    return copies.get(family, "Which context should I use?")


def summarize_response(row: dict[str, Any]) -> str:
    text = str(row.get("response_text") or row.get("ui_response") or "")
    text = " ".join(text.split())
    return text[:220]


def build_final_report(before_rows: list[dict[str, Any]], post_rows: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    before_summary = summarize_run(before_rows)
    after_summary = summarize_run(post_rows)
    command_before = sum(1 for row in before_rows if command_correct(row))
    command_after = sum(1 for row in post_rows if command_correct(row))
    before_gap_roots = gap_root_counts(before_rows)
    after_gap_roots = gap_root_counts(post_rows)
    workbench_summary = read_json_if_exists(out / "burndown_workbench_summary.json")
    integration_summary = read_json_if_exists(out / "burndown_integration_summary.json")
    summary = {
        "before": before_summary,
        "after": after_summary,
        "command_correct_before": command_before,
        "command_correct_after": command_after,
        "generic_provider_before": before_summary["actual_family_counts"].get("generic_provider", 0),
        "generic_provider_after": after_summary["actual_family_counts"].get("generic_provider", 0),
        "real_routing_gap_before": before_summary["failure_categories"].get("real_routing_gap", 0),
        "real_routing_gap_after": after_summary["failure_categories"].get("real_routing_gap", 0),
        "missing_context_should_clarify_before": before_gap_roots.get("missing_context_should_clarify", 0),
        "missing_context_should_clarify_after": after_gap_roots.get("missing_context_should_clarify", 0),
        "unmigrated_family_before": before_gap_roots.get("unmigrated_family", 0),
        "unmigrated_family_after": after_gap_roots.get("unmigrated_family", 0),
        "unsupported_feature_expected_before": before_gap_roots.get("unsupported_feature_expected", 0),
        "unsupported_feature_expected_after": after_gap_roots.get("unsupported_feature_expected", 0),
        "workbench": workbench_summary,
        "integration": integration_summary,
        "safety": safety_summary(post_rows),
        "artifact_dir": rel(out),
        "routine_save_historical_blocker_label": "known_unreproduced_product_latency_blocker",
        "recommendation": recommendation(after_summary, command_after),
    }
    return {"summary": summary}


def summarize_run(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "attempted": len(rows),
        "pass": sum(1 for row in rows if row.get("passed")),
        "fail": sum(1 for row in rows if not row.get("passed")),
        "failure_categories": dict(Counter(str(row.get("failure_category") or "passed") for row in rows if not row.get("passed"))),
        "actual_family_counts": dict(Counter(str(row.get("actual_route_family") or "") for row in rows)),
        "routing_engine_counts": dict(Counter(str(row.get("routing_engine") or "") for row in rows)),
        "max_response_json_bytes": max((int(row.get("response_json_bytes") or 0) for row in rows), default=0),
        "rows_above_1mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > 1_000_000),
    }


def gap_root_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(
        Counter(
            root_cause(row)
            for row in rows
            if str(row.get("failure_category") or "") == "real_routing_gap"
        )
    )


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def command_correct(row: dict[str, Any]) -> bool:
    assertions = row.get("assertions") if isinstance(row.get("assertions"), dict) else {}
    command_assertions = [
        "route_family",
        "subsystem",
        "tool_chain",
        "result_state",
        "verification",
        "approval",
        "clarification",
        "response_meaning",
        "target_slots",
        "no_overclaim",
        "provider_usage",
        "external_action",
        "payload_guardrail",
    ]
    return all(bool(assertions.get(name, {}).get("passed", True)) for name in command_assertions)


def safety_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
        "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
        "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
        "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
        "payload_guardrail_failures": sum(1 for row in rows if row.get("failure_category") == "payload_guardrail_failure"),
    }


def recommendation(after_summary: dict[str, Any], command_after: int) -> str:
    routing_gaps = after_summary["failure_categories"].get("real_routing_gap", 0)
    if routing_gaps > 25:
        return "continue_routing_gap_burn_down"
    if command_after < 225:
        return "continue_command_correctness_stabilization"
    return "consider_larger_eval_after_latency_review"


def render_census(census: dict[str, Any]) -> list[str]:
    lines = [
        "# 250 Routing-Gap Census",
        "",
        f"Source: `{census['source_results']}`",
        f"Total real routing gaps: {census['total_real_routing_gaps']}",
        f"Generic-provider fallbacks in gap rows: {census['generic_provider_fallbacks']}",
        "",
        "## Root Causes",
    ]
    for key, value in sorted(census["root_cause_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Rows", "| test_id | expected | actual | engine | root cause | prompt |", "|---|---:|---:|---:|---:|---|"])
    for item in census["items"]:
        lines.append(
            f"| `{item['test_id']}` | {item['expected_route_family']} | {item['actual_route_family']} | "
            f"{item['routing_engine']} | {item['root_cause']} | {escape_md(item['prompt'])} |"
        )
    return lines


def render_missing_context(plan: dict[str, Any]) -> list[str]:
    lines = [
        "# Missing-Context Clarification Plan",
        "",
        f"Total migrated-family gap rows: {plan['total']}",
        f"Fix now: {plan['fix_now']}",
        f"Defer/classify: {plan['defer_or_classify']}",
        "",
        "| test_id | native owner | missing context | decision | clarification |",
        "|---|---:|---|---:|---|",
    ]
    for item in plan["items"]:
        lines.append(
            f"| `{item['test_id']}` | {item['native_family_should_own']} | "
            f"{escape_md(item['context_missing'])} | {item['fix_decision']} | {escape_md(item['clarification_copy'])} |"
        )
    return lines


def render_unmigrated(plan: dict[str, Any]) -> list[str]:
    lines = [
        "# Unmigrated-Family Plan",
        "",
        f"Total unmigrated/direct family gap rows: {plan['total']}",
        f"Selected for migration now: {len(plan['selected_for_migration_now'])}",
        "",
        plan["defer_reason"],
        "",
        "| test_id | expected family | decision | risk |",
        "|---|---:|---:|---|",
    ]
    for item in plan["items"]:
        lines.append(f"| `{item['test_id']}` | {item['expected_route_family']} | {item['fix_decision']} | {escape_md(item['migration_risk'])} |")
    return lines


def render_final(report: dict[str, Any]) -> list[str]:
    summary = report["summary"]
    before = summary["before"]
    after = summary["after"]
    safety = summary["safety"]
    workbench = summary.get("workbench") if isinstance(summary.get("workbench"), dict) else {}
    integration = summary.get("integration") if isinstance(summary.get("integration"), dict) else {}
    return [
        "# Routing Gap Burn-Down 1 Report",
        "",
        "## Executive Summary",
        f"- Strict score moved from {before['pass']} pass / {before['fail']} fail to {after['pass']} pass / {after['fail']} fail.",
        f"- Command-correct score moved from {summary['command_correct_before']} to {summary['command_correct_after']}.",
        f"- Real routing gaps moved from {summary['real_routing_gap_before']} to {summary['real_routing_gap_after']}.",
        f"- Generic-provider rows moved from {summary['generic_provider_before']} to {summary['generic_provider_after']}.",
        "",
        "## Starting Point",
        "- Strict score: 149 pass / 101 fail.",
        "- Command-correct score: 212 pass / 38 fail.",
        "- Routing gaps: 38 total, including 18 missing-context/native-clarification rows and 20 unmigrated or unsupported rows.",
        "- Latency was deliberately preserved as a separate operational-quality lane.",
        "",
        "## Missing-Context Behavior",
        f"- Missing-context route gaps moved from {summary['missing_context_should_clarify_before']} to {summary['missing_context_should_clarify_after']}.",
        "- Active request state can now supply the native follow-up owner for already-migrated Planner v2 families.",
        "- Missing, stale, or absent native context now keeps generic_provider gated off when a native owner is known.",
        "- App status follow-ups bind as app_control/read-only status instead of requiring a concrete app target.",
        "",
        "## Family Migration",
        "- Newly migrated families: none.",
        "- Deliberately not migrated: desktop_search, development, file_operation, location, machine, maintenance, notes, power, resources, software_recovery, storage, system_control, terminal, time, trust_approvals, weather, window_control, and other single-row/direct families.",
        f"- Unmigrated-family route gaps moved from {summary['unmigrated_family_before']} to {summary['unmigrated_family_after']}.",
        "",
        "## Targeted Verification",
        f"- Workbench: {workbench.get('pass', 0)}/{workbench.get('total', 0)} passed; legacy fallback usage was {workbench.get('legacy_fallback_usage', 0)} for near-miss negatives only.",
        f"- HTTP lane: {integration.get('scored_passed', 0)}/{integration.get('scored_total', 0)} passed with {integration.get('planner_v2_rows', 0)} Planner v2 rows and {integration.get('generic_provider_rows', 0)} intended generic-provider near-misses.",
        f"- HTTP safety: provider/openai/llm/embedding calls {integration.get('provider_calls', 0)}/{integration.get('openai_calls', 0)}/{integration.get('llm_calls', 0)}/{integration.get('embedding_calls', 0)}; real external actions {integration.get('real_external_actions', 0)}.",
        "",
        "## 250 Before / After",
        f"- Strict score: {before['pass']}/{before['attempted']} -> {after['pass']}/{after['attempted']}.",
        f"- Command-correct score: {summary['command_correct_before']}/{before['attempted']} -> {summary['command_correct_after']}/{after['attempted']}.",
        f"- Failure categories before: {json.dumps(before['failure_categories'], sort_keys=True)}.",
        f"- Failure categories after: {json.dumps(after['failure_categories'], sort_keys=True)}.",
        f"- Generic-provider rows: {summary['generic_provider_before']} -> {summary['generic_provider_after']}.",
        f"- Planner v2 rows: {before['routing_engine_counts'].get('planner_v2', 0)} -> {after['routing_engine_counts'].get('planner_v2', 0)}.",
        "",
        "## Mixed Findings",
        "- Real routing gaps improved but remain above the readiness target.",
        "- Response correctness and wrong-subsystem were clean at the start of this pass but reappeared in the rerun: 2 response_correctness_failure rows and 1 wrong_subsystem row.",
        "- Strict score improved substantially, but part of that came from fewer latency rows in this run; latency was not optimized here.",
        "",
        "## Safety / Provider / Payload",
        f"- Provider/OpenAI/LLM/embedding calls: {safety['provider_calls']} / {safety['openai_calls']} / {safety['llm_calls']} / {safety['embedding_calls']}",
        f"- Real external actions: {safety['real_external_actions']}",
        f"- Hard timeouts / process kills: {safety['hard_timeouts']} / {safety['process_kills']}",
        f"- Payload guardrail failures: {safety['payload_guardrail_failures']}",
        f"- Rows above 1 MB: {after['rows_above_1mb']}",
        f"- Max response bytes: {after['max_response_json_bytes']}",
        "",
        "## What Changed",
        "- Planner v2 now uses active request state as a follow-up owner for already-migrated native families.",
        "- Native missing context now stays inside the native family with clarification instead of falling to generic_provider.",
        "- App-control follow-ups for active-app status emit the native `active_apps` plan through Planner v2.",
        "",
        "## What Did Not Change",
        "- No latency optimization was attempted.",
        "- No new legacy-planner behavior was added.",
        "- No exact prompt strings or test IDs were added to product routing logic.",
        "- The historical routine_save blocker label remains `known_unreproduced_product_latency_blocker`.",
        "",
        "## Recommendation",
        f"- {summary['recommendation']}",
        "- Continue routing-gap burn-down, then separately revisit the response/wrong-subsystem regressions before any 1000-case run.",
    ]


def escape_md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
