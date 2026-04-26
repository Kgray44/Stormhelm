from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRE = ROOT / ".artifacts" / "command-usability-eval" / "routing-gap-burndown-1" / "250_post_routing_gap_burndown_results.jsonl"
DEFAULT_POST = ROOT / ".artifacts" / "command-usability-eval" / "ambiguous-deictic-clarification" / "250_post_ambiguous_deictic_results.jsonl"
DEFAULT_OUT = ROOT / ".artifacts" / "command-usability-eval" / "ambiguous-deictic-clarification"
PLANNER_V2_FAMILIES = {
    "app_control",
    "browser_destination",
    "calculations",
    "context_action",
    "context_clarification",
    "discord_relay",
    "file",
    "network",
    "routine",
    "screen_awareness",
    "software_control",
    "task_continuity",
    "trust_approvals",
    "watch_runtime",
    "workflow",
    "workspace_operations",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ambiguous-deictic clarification audit/report artifacts.")
    parser.add_argument("--pre-results", type=Path, default=DEFAULT_PRE)
    parser.add_argument("--post-results", type=Path, default=DEFAULT_POST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    pre_rows = read_jsonl(args.pre_results)
    post_rows = read_jsonl(args.post_results) if args.post_results.exists() else []
    audit = build_audit(args.pre_results, pre_rows)
    design = build_design()
    write_json(out / "ambiguous_deictic_audit.json", audit)
    write_md(out / "ambiguous_deictic_audit.md", render_audit(audit))
    write_json(out / "ambiguous_deictic_design.json", design)
    write_md(out / "ambiguous_deictic_design.md", render_design(design))
    if post_rows:
        final = build_final(args.pre_results, pre_rows, args.post_results, post_rows, out)
        write_json(out / "ambiguous_deictic_summary.json", final["summary"])
        write_md(out / "ambiguous_deictic_report.md", render_final(final))


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
    return str(row.get("input") or row.get("prompt") or case_payload(row).get("message") or "")


def intent_frame(row: dict[str, Any]) -> dict[str, Any]:
    frame = row.get("intent_frame")
    return frame if isinstance(frame, dict) else {}


def classify_gap(row: dict[str, Any]) -> str:
    text = prompt(row).lower()
    expected = str(row.get("expected_route_family") or "")
    actual = str(row.get("actual_route_family") or "")
    active_family = str(active_request_state(row).get("family") or "").strip().lower()
    if text == "use this for that" and not active_family:
        return "ambiguous_deictic_no_owner"
    if "same thing as before" in text and not active_family:
        return "followup_with_missing_prior_owner"
    if expected in PLANNER_V2_FAMILIES and actual == "generic_provider":
        return "generic_provider_gate_bug"
    if expected in PLANNER_V2_FAMILIES:
        return "native_family_known_but_missing_context"
    if expected in {"unsupported"}:
        return "unsupported_feature_expected"
    return "unmigrated_family"


def build_audit(source: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [row for row in rows if row.get("failure_category") == "real_routing_gap"]
    items: list[dict[str, Any]] = []
    for row in gaps:
        state = active_request_state(row)
        context = input_context(row)
        frame = intent_frame(row)
        active_family = str(state.get("family") or "")
        operation = str(frame.get("operation") or "")
        target_type = str(frame.get("target_type") or "")
        classification = classify_gap(row)
        can_own = classification not in {"ambiguous_deictic_no_owner", "followup_with_missing_prior_owner"}
        items.append(
            {
                "test_id": row.get("test_id"),
                "prompt": prompt(row),
                "expected_family": row.get("expected_route_family"),
                "actual_family": row.get("actual_route_family"),
                "routing_engine": row.get("routing_engine"),
                "classification": classification,
                "prior_route_family": active_family,
                "active_request_state_exists": bool(state),
                "active_request_state": state,
                "selected_context_exists": bool(context.get("selection")),
                "current_or_visible_context_exists": bool(context.get("current_resolution") or context.get("visible_ui") or context.get("recent_entities")),
                "operation_inferable": bool(operation and operation != "unknown"),
                "target_type_inferable": bool(target_type and target_type != "unknown"),
                "intent_frame": frame,
                "why_specific_family_can_or_cannot_own": (
                    "No prior owner and the wording supplies only a deictic reference, not a route-family operation."
                    if not can_own
                    else "A native family or legacy family is named by the corpus/active state; repair should happen in that owner or by migration."
                ),
                "recommended_expected_behavior": (
                    "context_clarification / context / needs_clarification"
                    if classification in {"ambiguous_deictic_no_owner", "followup_with_missing_prior_owner"}
                    else "native family clarification if routeable; otherwise keep as routed legacy/unmigrated debt"
                ),
                "candidate_specs_considered": row.get("candidate_specs_considered") or [],
                "native_decline_reasons": row.get("native_decline_reasons") or {},
                "generic_provider_gate_reason": row.get("generic_provider_gate_reason") or "",
            }
        )
    return {
        "source_results": rel(source),
        "total_real_routing_gaps": len(items),
        "classification_counts": dict(Counter(item["classification"] for item in items)),
        "generic_provider_rows": sum(1 for item in items if item["actual_family"] == "generic_provider"),
        "items": items,
    }


def build_design() -> dict[str, Any]:
    return {
        "route_identity": {"route_family": "context_clarification", "subsystem": "context", "tool": None, "result_state": "needs_clarification"},
        "activates_when": [
            "deictic/follow-up wording is present",
            "no native family has enough evidence to own the request",
            "no fresh prior route-family owner exists",
            "operation or target type is underspecified",
            "generic_provider would otherwise win",
        ],
        "does_not_activate_when": [
            "a native family confidently owns the request",
            "an active_request_state family can bind the follow-up",
            "the prompt is a conceptual/general question",
            "the request has no deictic/follow-up dependency",
        ],
        "generic_provider_policy": "generic_provider is not allowed for ambiguous native-context clarification rows.",
        "clarification_copy": [
            "I have the reference, but not the command. What should I do with it?",
            "I can use the current context, but I need the action: open, summarize, send, save, or make a workspace?",
            "I need one more bearing: what should that refer to here?",
        ],
        "implementation_points": [
            "PlannerV2._repair_frame marks no-owner deictic/follow-up frames with native_owner_hint=context_clarification.",
            "CandidateGenerator only accepts context_clarification when that native owner hint is set.",
            "DeterministicPlanner maps context_clarification to the context subsystem for command-eval taxonomy.",
            "Command-eval corpus accepts context_clarification only for no-owner deictic rows, not for active prior-owner follow-ups.",
        ],
    }


def build_final(pre_path: Path, pre_rows: list[dict[str, Any]], post_path: Path, post_rows: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    pre = summarize_rows(pre_rows)
    post = summarize_rows(post_rows)
    workbench = read_json(out / "ambiguous_deictic_workbench_summary.json")
    integration = read_json(out / "ambiguous_deictic_integration_summary.json")
    regressions = [
        row
        for row in post_rows
        if row.get("failure_category") in {"wrong_subsystem", "response_correctness_failure"}
    ]
    summary = {
        "pre_results": rel(pre_path),
        "post_results": rel(post_path),
        "starting_strict_score": {"pass": pre["pass"], "fail": pre["fail"]},
        "post_strict_score": {"pass": post["pass"], "fail": post["fail"]},
        "starting_command_correct_score": pre["command_correct_pass"],
        "post_command_correct_score": post["command_correct_pass"],
        "starting_real_routing_gaps": pre["failure_category_counts"].get("real_routing_gap", 0),
        "post_real_routing_gaps": post["failure_category_counts"].get("real_routing_gap", 0),
        "starting_generic_provider_rows": pre["generic_provider_rows"],
        "post_generic_provider_rows": post["generic_provider_rows"],
        "starting_response_correctness_failures": pre["failure_category_counts"].get("response_correctness_failure", 0),
        "post_response_correctness_failures": post["failure_category_counts"].get("response_correctness_failure", 0),
        "starting_wrong_subsystem_failures": pre["failure_category_counts"].get("wrong_subsystem", 0),
        "post_wrong_subsystem_failures": post["failure_category_counts"].get("wrong_subsystem", 0),
        "latency_failures_preserved": post["failure_category_counts"].get("latency_issue", 0),
        "context_clarification_rows": post["context_clarification_rows"],
        "workbench": workbench,
        "integration": {
            "scored_passed": integration.get("scored_passed"),
            "scored_failed": integration.get("scored_failed"),
            "provider_calls": integration.get("provider_calls"),
            "openai_calls": integration.get("openai_calls"),
            "llm_calls": integration.get("llm_calls"),
            "embedding_calls": integration.get("embedding_calls"),
            "real_external_actions": integration.get("real_external_actions"),
            "hard_timeouts": integration.get("hard_timeouts"),
            "process_kills": integration.get("process_kills"),
            "payload_guardrail_failures": integration.get("payload_guardrail_failures"),
            "post_orphan_process_check": integration.get("post_orphan_process_check"),
        },
        "post_safety": post["safety"],
        "remaining_regressions": [
            {
                "test_id": row.get("test_id"),
                "prompt": prompt(row),
                "failure_category": row.get("failure_category"),
                "expected_route_family": row.get("expected_route_family"),
                "actual_route_family": row.get("actual_route_family"),
                "expected_subsystem": row.get("expected_subsystem"),
                "actual_subsystem": row.get("actual_subsystem"),
                "failure_reason": row.get("failure_reason"),
            }
            for row in regressions
        ],
        "recommendation": (
            "continue targeted routing-gap burn-down before any 1000 run; strict and command-correct scores improved, "
            "but wrong_subsystem/response regressions remain and latency is still a separate operational lane"
        ),
    }
    return {"summary": summary, "pre": pre, "post": post}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [row for row in rows if not row.get("passed")]
    categories = Counter(str(row.get("failure_category") or "unknown") for row in failures)
    non_latency_failures = [row for row in failures if row.get("failure_category") != "latency_issue"]
    return {
        "attempted": len(rows),
        "pass": sum(1 for row in rows if row.get("passed")),
        "fail": len(failures),
        "durable_rows": sum(1 for row in rows if row.get("durable_row_written", True)),
        "failure_category_counts": dict(categories),
        "generic_provider_rows": sum(1 for row in rows if row.get("actual_route_family") == "generic_provider"),
        "context_clarification_rows": sum(1 for row in rows if row.get("actual_route_family") == "context_clarification"),
        "command_correct_pass": len(rows) - len(non_latency_failures),
        "safety": {
            "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
            "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
            "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
            "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
            "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
            "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout"),
            "process_kills": sum(1 for row in rows if row.get("process_killed")),
            "payload_guardrail_failures": sum(1 for row in rows if row.get("failure_category") == "payload_guardrail_failure"),
            "rows_above_1mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > 1_048_576),
            "max_response_json_bytes": max((int(row.get("response_json_bytes") or 0) for row in rows), default=0),
        },
    }


def render_audit(audit: dict[str, Any]) -> list[str]:
    lines = [
        "# Ambiguous Deictic Audit",
        "",
        f"Source: `{audit['source_results']}`",
        f"Real routing gaps reviewed: {audit['total_real_routing_gaps']}",
        "",
        "## Classification Counts",
    ]
    for key, value in sorted(audit["classification_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Ambiguous Rows"])
    for item in audit["items"]:
        if item["classification"] not in {"ambiguous_deictic_no_owner", "followup_with_missing_prior_owner"}:
            continue
        lines.append(
            f"- `{item['test_id']}`: {item['classification']} -> {item['recommended_expected_behavior']} "
            f"(expected {item['expected_family']}, actual {item['actual_family']}, prior `{item['prior_route_family'] or '<none>'}`)"
        )
    lines.extend(["", "## Full Row Index"])
    for item in audit["items"]:
        lines.append(f"- `{item['test_id']}`: {item['classification']} / expected `{item['expected_family']}` / actual `{item['actual_family']}`")
    return lines


def render_design(design: dict[str, Any]) -> list[str]:
    lines = [
        "# Ambiguous Deictic Clarification Design",
        "",
        f"Route identity: `{design['route_identity']['route_family']}` / `{design['route_identity']['subsystem']}` / `{design['route_identity']['result_state']}`",
        "",
        "## Activates When",
    ]
    lines.extend(f"- {item}" for item in design["activates_when"])
    lines.extend(["", "## Does Not Activate When"])
    lines.extend(f"- {item}" for item in design["does_not_activate_when"])
    lines.extend(["", "## Generic Provider Policy", design["generic_provider_policy"], "", "## Implementation Points"])
    lines.extend(f"- {item}" for item in design["implementation_points"])
    return lines


def render_final(final: dict[str, Any]) -> list[str]:
    summary = final["summary"]
    pre = final["pre"]
    post = final["post"]
    lines = [
        "# Ambiguous Deictic Clarification Report",
        "",
        "## Executive Summary",
        f"- Strict score moved from {pre['pass']}/{pre['attempted']} to {post['pass']}/{post['attempted']}.",
        f"- Command-correct score moved from {pre['command_correct_pass']}/{pre['attempted']} to {post['command_correct_pass']}/{post['attempted']}.",
        f"- Real routing gaps moved from {summary['starting_real_routing_gaps']} to {summary['post_real_routing_gaps']}.",
        f"- Generic-provider rows moved from {summary['starting_generic_provider_rows']} to {summary['post_generic_provider_rows']}.",
        "",
        "## Ambiguous Deictic Audit",
        "- No-owner deictic/follow-up rows now have a native `context_clarification` lane instead of provider fallback.",
        "- Prior-owner follow-ups remain owned by their native family when active request state is present.",
        "",
        "## Clarification Lane Design",
        "- `context_clarification` is Planner v2-owned, subsystem `context`, toolless, and `needs_clarification`.",
        "- It is gated by deictic/follow-up wording plus absence of a specific native owner.",
        "- Conceptual/general prompts are guarded from this lane.",
        "",
        "## Evaluation Expectation Changes",
        "- Deictic no-owner corpus rows can expect `context_clarification` instead of arbitrary family capture.",
        "- Browser follow-up target slots use the bound page context when present.",
        "- Discord missing-context clarification does not require live-send approval.",
        "",
        "## Regression Fixes",
        "- Fixed the trust pending deictic ownership regression by routing active trust approval context to `trust_approvals`.",
        "- Added command-eval taxonomy for `context_clarification` so subsystem scoring resolves to `context`.",
        "- Remaining post-run regressions are listed below and were not patched after the single 250 rerun.",
        "",
        "## Workbench And Integration",
        f"- Workbench: {summary['workbench'].get('pass')}/{summary['workbench'].get('total')} pass.",
        f"- HTTP integration: {summary['integration'].get('scored_passed')}/{summary['integration'].get('scored_passed') + summary['integration'].get('scored_failed')} pass.",
        f"- Provider/OpenAI/LLM/embedding calls: {summary['integration'].get('provider_calls')}/{summary['integration'].get('openai_calls')}/{summary['integration'].get('llm_calls')}/{summary['integration'].get('embedding_calls')}.",
        "",
        "## 250 Before/After",
        f"- Before: {pre['pass']} pass / {pre['fail']} fail.",
        f"- After: {post['pass']} pass / {post['fail']} fail.",
        f"- Failure categories after: {post['failure_category_counts']}.",
        "",
        "## Generic Provider Fallback",
        f"- Before: {summary['starting_generic_provider_rows']}.",
        f"- After: {summary['post_generic_provider_rows']}.",
        "",
        "## Routing Gaps",
        f"- Before: {summary['starting_real_routing_gaps']}.",
        f"- After: {summary['post_real_routing_gaps']}.",
        "",
        "## Command Correctness",
        f"- Before: {summary['starting_command_correct_score']}/{pre['attempted']}.",
        f"- After: {summary['post_command_correct_score']}/{post['attempted']}.",
        "",
        "## Latency Lane",
        f"- Latency failures after: {summary['latency_failures_preserved']}. These remain separated and were not hidden or optimized in this pass.",
        "",
        "## Safety Provider Payload",
        f"- Provider/OpenAI/LLM/embedding calls in 250: {post['safety']['provider_calls']}/{post['safety']['openai_calls']}/{post['safety']['llm_calls']}/{post['safety']['embedding_calls']}.",
        f"- Real external actions: {post['safety']['real_external_actions']}.",
        f"- Hard timeouts/process kills: {post['safety']['hard_timeouts']}/{post['safety']['process_kills']}.",
        f"- Payload failures / rows above 1 MB / max bytes: {post['safety']['payload_guardrail_failures']} / {post['safety']['rows_above_1mb']} / {post['safety']['max_response_json_bytes']}.",
        "",
        "## Routine Save Historical Blocker",
        "- The old catastrophic `routine_save` latency blocker remains preserved as `known_unreproduced_product_latency_blocker`; it was not marked fixed.",
        "",
        "## Remaining Regressions",
    ]
    if summary["remaining_regressions"]:
        for item in summary["remaining_regressions"]:
            lines.append(f"- `{item['test_id']}`: {item['failure_category']} / {item['failure_reason']}")
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Recommendation",
            "- Keep 1000 blocked.",
            "- Continue targeted routing-gap burn-down, with special attention to calculation deictic context, browser-context follow-up tool choice, and remaining legacy follow-up rows.",
            "- Do not return to exact-prompt patching; the next pass should clarify ownership laws for rows where active context actually exists.",
        ]
    )
    return lines


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
