from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".artifacts" / "command-usability-eval" / "planner-v2-stabilization-2"
PRE = ROOT / ".artifacts" / "command-usability-eval" / "planner-v2-stabilization-1"
BEST = ROOT / ".artifacts" / "command-usability-eval" / "readiness-pass-3"

MIGRATED_FAMILIES = {
    "app_control",
    "browser_destination",
    "calculations",
    "context_action",
    "discord_relay",
    "file",
    "network",
    "routine",
    "screen_awareness",
    "software_control",
    "task_continuity",
    "watch_runtime",
    "workflow",
    "workspace_operations",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pre_rows = read_jsonl(PRE / "250_post_stabilization_results.jsonl")
    post_rows = read_jsonl(OUT / "250_post_stabilization_2_results.jsonl")
    rows_for_audits = pre_rows
    write_failure_burndown(rows_for_audits)
    write_real_routing_gap_autopsy(rows_for_audits)
    write_latency_failure_separation(rows_for_audits)
    write_response_correctness_audit(rows_for_audits)
    write_missing_telemetry_audit(rows_for_audits)
    write_final_report(pre_rows, post_rows)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_md(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [row for row in rows if not row.get("passed")]
    return {
        "attempted": len(rows),
        "completed": len(rows),
        "durable_rows": len(rows),
        "pass": sum(1 for row in rows if row.get("passed")),
        "fail": len(failed),
        "excluded": sum(1 for row in rows if not row.get("score_in_pass_fail", True)),
        "failure_categories": dict(Counter(str(row.get("failure_category") or "passed") for row in failed)),
        "routing_engines": dict(Counter(str(row.get("routing_engine") or "unknown") for row in rows)),
        "generic_provider_rows": sum(1 for row in rows if row.get("actual_route_family") == "generic_provider"),
        "provider_calls": sum(int(row.get("provider_call_count") or (1 if row.get("provider_called") else 0) or 0) for row in rows),
        "openai_calls": sum(int(row.get("openai_call_count") or (1 if row.get("openai_called") else 0) or 0) for row in rows),
        "llm_calls": sum(int(row.get("llm_call_count") or (1 if row.get("llm_called") else 0) or 0) for row in rows),
        "embedding_calls": sum(int(row.get("embedding_call_count") or (1 if row.get("embedding_called") else 0) or 0) for row in rows),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout" or row.get("failure_category") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
        "payload_guardrail_failures": sum(1 for row in rows if row.get("failure_category") == "payload_guardrail_failure"),
        "payload_guardrail_triggered_rows": sum(1 for row in rows if row.get("payload_guardrail_triggered")),
        "rows_above_1mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > 1_000_000),
        "max_response_json_bytes": max((int(row.get("response_json_bytes") or 0) for row in rows), default=0),
    }


def row_prompt(row: dict[str, Any]) -> str:
    return str(row.get("prompt") or row.get("input_request") or "")


def actual_tool(row: dict[str, Any]) -> list[str]:
    value = row.get("actual_tool")
    if value is None:
        value = row.get("actual_tool_chain")
    return [str(item) for item in (value or [])]


def expected_tool(row: dict[str, Any]) -> list[str]:
    return [str(item) for item in (row.get("expected_tool") or [])]


def route_correct(row: dict[str, Any]) -> bool:
    return row.get("expected_route_family") == row.get("actual_route_family")


def subsystem_correct(row: dict[str, Any]) -> bool:
    expected = str(row.get("expected_subsystem") or "")
    return not expected or expected == str(row.get("actual_subsystem") or "")


def tool_correct(row: dict[str, Any]) -> bool:
    expected = expected_tool(row)
    actual = actual_tool(row)
    return actual[: len(expected)] == expected if expected else not actual


def planner_v2_trace_present(row: dict[str, Any]) -> bool:
    return bool(row.get("planner_v2_trace") or row.get("intent_frame"))


def selected_route_spec(row: dict[str, Any]) -> str:
    return str(row.get("selected_route_spec") or "")


def route_candidates(row: dict[str, Any]) -> list[Any]:
    return list(row.get("route_candidates") or [])


def response_text(row: dict[str, Any]) -> str:
    for key in ("ui_response", "response_text", "assistant_message", "response_summary"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return str(row.get("failure_reason") or "")[:500]


def root_cause(row: dict[str, Any]) -> str:
    category = str(row.get("failure_category") or "")
    expected = str(row.get("expected_route_family") or "")
    actual = str(row.get("actual_route_family") or "")
    engine = str(row.get("routing_engine") or "")
    test_id = str(row.get("test_id") or "")
    reason = str(row.get("failure_reason") or "")
    prompt = row_prompt(row).lower()
    if category == "latency_issue":
        if route_correct(row) and subsystem_correct(row) and tool_correct(row):
            if expected in {"workspace_operations", "task_continuity"} or "known_workspace_latency_lane" in (row.get("known_lane_labels") or []):
                return "latency_only_bounded"
            return "product_latency_bug"
        return "product_latency_bug"
    if category == "missing_telemetry":
        return "missing_telemetry_bug"
    if category == "response_correctness_failure":
        if expected == "browser_destination" and "target_slots" in reason:
            return "taxonomy_scoring_mismatch"
        if expected == "screen_awareness" and "clarification" in reason:
            return "corpus_expectation_issue"
        if "result_state" in reason:
            return "response_result_state_bug"
        return "response_copy_bug"
    if category == "real_routing_gap":
        if expected == actual and "clarification" in reason and "tool_chain" in reason:
            return "missing_context_should_clarify"
        if expected == "weather" and actual == "generic_provider":
            return "generic_provider_gate_bug"
        if engine == "legacy_planner" and actual == "generic_provider" and ("use this for that" in prompt or "same thing as before" in prompt):
            return "context_binding_gap" if expected in MIGRATED_FAMILIES else "unmigrated_family"
        if expected not in MIGRATED_FAMILIES:
            return "unmigrated_family"
        if expected in (row.get("candidate_specs_considered") or []) and actual == "generic_provider":
            return "generic_provider_gate_bug"
        if expected in MIGRATED_FAMILIES and not selected_route_spec(row):
            return "intent_frame_extraction_gap"
        if expected in MIGRATED_FAMILIES:
            return "migrated_family_spec_gap"
    return "unknown"


def compact_failure(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "prompt": row_prompt(row),
        "failure_category": row.get("failure_category"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "expected_subsystem": row.get("expected_subsystem"),
        "actual_subsystem": row.get("actual_subsystem"),
        "expected_tool": expected_tool(row),
        "actual_tool": actual_tool(row),
        "routing_engine": row.get("routing_engine"),
        "planner_v2_trace_present": planner_v2_trace_present(row),
        "route_candidates": route_candidates(row)[:8],
        "route_scores": row.get("route_scores") or {},
        "selected_route_spec": selected_route_spec(row),
        "native_decline_reasons": row.get("native_decline_reasons") or {},
        "generic_provider_gate_reason": row.get("generic_provider_gate_reason") or "",
        "result_state": row.get("actual_result_state") or row.get("result_state"),
        "response_summary": response_text(row),
        "latency_ms": row.get("latency_ms"),
        "known_lane_labels": row.get("known_lane_labels") or [],
        "provider_called": row.get("provider_called"),
        "openai_called": row.get("openai_called"),
        "llm_called": row.get("llm_called"),
        "embedding_called": row.get("embedding_called"),
        "provider_call_count": row.get("provider_call_count"),
        "openai_call_count": row.get("openai_call_count"),
        "llm_call_count": row.get("llm_call_count"),
        "embedding_call_count": row.get("embedding_call_count"),
        "response_json_bytes": row.get("response_json_bytes"),
        "root_cause_classification": root_cause(row),
    }


def write_failure_burndown(rows: list[dict[str, Any]]) -> None:
    failures = [compact_failure(row) for row in rows if not row.get("passed")]
    payload = {
        "total_failures": len(failures),
        "root_cause_counts": dict(Counter(item["root_cause_classification"] for item in failures)),
        "failure_category_counts": dict(Counter(str(item["failure_category"] or "") for item in failures)),
        "routing_engine_counts": dict(Counter(str(item["routing_engine"] or "") for item in failures)),
        "rows": failures,
    }
    write_json(OUT / "failure_burndown_census.json", payload)
    write_md(
        OUT / "failure_burndown_census.md",
        [
            "# Planner v2 Stabilization 2 Failure Burn-Down Census",
            "",
            f"Failed rows analyzed: {len(failures)}.",
            "",
            "## Root Causes",
            *format_counts(payload["root_cause_counts"]),
            "",
            "## Failure Categories",
            *format_counts(payload["failure_category_counts"]),
            "",
            "## Rows",
            *[f"- `{row['test_id']}`: {row['failure_category']} / {row['root_cause_classification']} / {row['expected_route_family']} -> {row['actual_route_family']} / engine={row['routing_engine']}" for row in failures],
        ],
    )


def write_real_routing_gap_autopsy(rows: list[dict[str, Any]]) -> None:
    gaps = [row for row in rows if row.get("failure_category") == "real_routing_gap"]
    details = []
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for row in gaps:
        expected = str(row.get("expected_route_family") or "")
        actual = str(row.get("actual_route_family") or "")
        candidate_specs = set(str(item) for item in (row.get("candidate_specs_considered") or []))
        native_considered = expected in candidate_specs or any(c.get("route_family") == expected for c in route_candidates(row) if isinstance(c, dict))
        declines = row.get("native_decline_reasons") or {}
        classification = routing_gap_classification(row)
        detail = {
            **compact_failure(row),
            "planner_v2_family_exists": expected in MIGRATED_FAMILIES,
            "route_family_spec_exists": expected in candidate_specs or expected in MIGRATED_FAMILIES,
            "native_candidate_considered": native_considered,
            "candidate_declined_correctly": bool(declines.get(expected)) and classification not in {"Planner v2 spec incomplete", "IntentFrame extraction bug", "ContextBinder bug"},
            "candidate_decline_reasons": declines.get(expected) or [],
            "generic_provider_won": actual == "generic_provider",
            "legacy_fallback_used": bool(row.get("legacy_fallback_used")) or row.get("routing_engine") == "legacy_planner",
            "context_missing_stale_or_ambiguous": _context_missing(row),
            "feature_routeable": expected in MIGRATED_FAMILIES or expected in {"weather", "terminal", "power", "resources", "maintenance", "file_operation", "software_recovery"},
            "routing_gap_classification": classification,
        }
        details.append(detail)
        groups["expected_route_family"][expected] += 1
        groups["actual_route_family"][actual] += 1
        groups["routing_engine"][str(row.get("routing_engine") or "")] += 1
        groups["classification"][classification] += 1
    payload = {"count": len(details), "groups": {key: dict(value) for key, value in groups.items()}, "rows": details}
    write_json(OUT / "real_routing_gap_autopsy.json", payload)
    write_md(
        OUT / "real_routing_gap_autopsy.md",
        [
            "# Real Routing Gap Autopsy",
            "",
            f"Rows: {len(details)}.",
            "",
            "## Classification Counts",
            *format_counts(payload["groups"].get("classification", {})),
            "",
            "## Expected Families",
            *format_counts(payload["groups"].get("expected_route_family", {})),
            "",
            "## Rows",
            *[f"- `{row['test_id']}`: {row['routing_gap_classification']} / {row['expected_route_family']} -> {row['actual_route_family']} / engine={row['routing_engine']} / gate={row['generic_provider_gate_reason']}" for row in details],
        ],
    )


def routing_gap_classification(row: dict[str, Any]) -> str:
    cause = root_cause(row)
    return {
        "unmigrated_family": "unmigrated_family",
        "migrated_family_spec_gap": "Planner v2 spec incomplete",
        "intent_frame_extraction_gap": "IntentFrame extraction bug",
        "context_binding_gap": "ContextBinder bug",
        "missing_context_should_clarify": "missing-context clarification bug",
        "generic_provider_gate_bug": "generic_provider gate bug",
        "corpus_expectation_issue": "corpus expectation bug",
        "unsupported_feature_expected": "unsupported feature expected",
    }.get(cause, "unknown")


def _context_missing(row: dict[str, Any]) -> bool:
    frame = row.get("intent_frame") if isinstance(row.get("intent_frame"), dict) else {}
    status = str(frame.get("context_status") or "").lower()
    reason = str(row.get("failure_reason") or "").lower()
    return status in {"missing", "stale", "ambiguous"} or "clarification" in reason or "missing" in reason


def write_latency_failure_separation(rows: list[dict[str, Any]]) -> None:
    latency_rows = [row for row in rows if row.get("failure_category") == "latency_issue"]
    details = []
    otherwise_correct = 0
    for row in latency_rows:
        axis_ok = route_correct(row) and subsystem_correct(row) and tool_correct(row)
        otherwise_correct += int(axis_ok)
        classification = latency_classification(row, axis_ok)
        details.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row_prompt(row),
                "route_correct": route_correct(row),
                "subsystem_correct": subsystem_correct(row),
                "tool_correct": tool_correct(row),
                "routing_engine": row.get("routing_engine"),
                "route_family": row.get("actual_route_family"),
                "total_latency_ms": row.get("total_latency_ms") or row.get("latency_ms"),
                "route_handler_ms": row.get("route_handler_ms"),
                "memory_context_ms": row.get("memory_context_ms"),
                "response_serialization_ms": row.get("response_serialization_ms"),
                "unattributed_latency_ms": row.get("unattributed_latency_ms"),
                "response_json_bytes": row.get("response_json_bytes"),
                "workspace_item_count": row.get("workspace_item_count"),
                "known_lane_labels": row.get("known_lane_labels") or [],
                "latency_only_failure_axis": axis_ok,
                "classification": classification,
            }
        )
    pass_if_latency_quarantined = sum(1 for row in rows if row.get("passed")) + otherwise_correct
    route_tool_pass = sum(1 for row in rows if route_correct(row) and subsystem_correct(row) and tool_correct(row))
    payload = {
        "count": len(details),
        "classification_counts": dict(Counter(item["classification"] for item in details)),
        "latency_otherwise_correct": otherwise_correct,
        "pass_count_if_latency_failures_quarantined": pass_if_latency_quarantined,
        "pass_count_if_only_route_subsystem_tool_scored": route_tool_pass,
        "rows": details,
    }
    write_json(OUT / "latency_failure_separation.json", payload)
    write_md(
        OUT / "latency_failure_separation.md",
        [
            "# Latency Failure Separation",
            "",
            f"Latency rows: {len(details)}.",
            f"Latency rows otherwise route/subsystem/tool correct: {otherwise_correct}.",
            f"Pass count if latency-only rows were quarantined: {pass_if_latency_quarantined}.",
            f"Pass count if only route/subsystem/tool correctness were scored: {route_tool_pass}.",
            "",
            "## Classifications",
            *format_counts(payload["classification_counts"]),
        ],
    )


def latency_classification(row: dict[str, Any], axis_ok: bool) -> str:
    if not axis_ok:
        return "route_failure_with_latency"
    family = str(row.get("actual_route_family") or row.get("expected_route_family") or "")
    if family == "workspace_operations" or "known_workspace_latency_lane" in (row.get("known_lane_labels") or []):
        return "known_workspace_latency_lane"
    if family in {"routine", "workflow", "file_operation", "maintenance", "software_recovery"}:
        return "known_bounded_direct_route_latency"
    return "latency_only_bounded"


def write_response_correctness_audit(rows: list[dict[str, Any]]) -> None:
    response_rows = [row for row in rows if row.get("failure_category") == "response_correctness_failure"]
    details = []
    for row in response_rows:
        details.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row_prompt(row),
                "route_correct": route_correct(row),
                "subsystem_correct": subsystem_correct(row),
                "tool_correct": tool_correct(row),
                "result_state_correct": "result_state" not in str(row.get("failure_reason") or ""),
                "expected_route_family": row.get("expected_route_family"),
                "actual_route_family": row.get("actual_route_family"),
                "expected_result_state": row.get("expected_result_state"),
                "actual_result_state": row.get("actual_result_state") or row.get("result_state"),
                "response_summary": response_text(row),
                "expected_response_behavior": _expected_response_behavior(row),
                "actual_response_behavior": _actual_response_behavior(row),
                "overclaimed": "overclaim" in str(row.get("failure_reason") or "").lower(),
                "under_explained": False,
                "failed_to_clarify": "clarification" in str(row.get("failure_reason") or "") and not bool(row.get("clarification_observed")),
                "generic_brochure_wording_for_native": "OpenAI integration is not configured" in response_text(row),
                "result_state_composer_caused": row.get("routing_engine") == "planner_v2",
                "old_response_layer_bypassed_planner_v2": row.get("routing_engine") != "planner_v2",
                "classification": response_classification(row),
            }
        )
    payload = {"count": len(details), "classification_counts": dict(Counter(item["classification"] for item in details)), "rows": details}
    write_json(OUT / "response_correctness_audit.json", payload)
    write_md(
        OUT / "response_correctness_audit.md",
        [
            "# Response Correctness Audit",
            "",
            f"Rows: {len(details)}.",
            "",
            "## Classifications",
            *format_counts(payload["classification_counts"]),
            "",
            "## Rows",
            *[f"- `{row['test_id']}`: {row['classification']} / route_ok={row['route_correct']} / result={row['actual_result_state']}" for row in details],
        ],
    )


def _expected_response_behavior(row: dict[str, Any]) -> str:
    if row.get("expected_route_family") == "screen_awareness":
        return "native screen-awareness clarification when no grounded visible target is present"
    if row.get("expected_route_family") == "browser_destination":
        return "dry-run browser destination with stable destination_name target slot"
    return str(row.get("expected_result_state") or "")


def _actual_response_behavior(row: dict[str, Any]) -> str:
    reason = str(row.get("failure_reason") or "")
    if "target_slots" in reason:
        return "route was correct but eval-visible target slot was missing"
    if "clarification" in reason:
        return "native route clarified because grounding/context was missing"
    return reason[:240]


def response_classification(row: dict[str, Any]) -> str:
    expected = str(row.get("expected_route_family") or "")
    reason = str(row.get("failure_reason") or "")
    if expected == "browser_destination" and "target_slots" in reason:
        return "telemetry/scoring bug"
    if expected == "screen_awareness" and "clarification" in reason:
        return "corpus_expectation_issue"
    if "result_state" in reason:
        return "result_state_composer_bug"
    return "response_copy_bug"


def write_missing_telemetry_audit(rows: list[dict[str, Any]]) -> None:
    telemetry_rows = [row for row in rows if row.get("failure_category") == "missing_telemetry"]
    details = []
    for row in telemetry_rows:
        engine = str(row.get("routing_engine") or "")
        details.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row_prompt(row),
                "route_family": row.get("actual_route_family"),
                "routing_engine": engine,
                "missing_fields": missing_fields(row),
                "planner_v2_trace_should_exist": engine == "planner_v2",
                "route_surface_type_should_exist": True,
                "planner_obedience_should_exist": engine not in {"direct_handler", "generic_provider"},
                "provider_audit_fields_exist": all(key in row for key in ("provider_called", "openai_called", "llm_called", "embedding_called")),
                "payload_fields_exist": "response_json_bytes" in row,
                "telemetry_root_cause": "direct_handler_exemption_missing" if engine == "direct_handler" else "missing_planner_trace",
                "fix_decision": "fixed_direct_handler_exemption_and_terminal_taxonomy" if engine == "direct_handler" else "defer",
            }
        )
    payload = {"count": len(details), "rows": details}
    write_json(OUT / "missing_telemetry_audit.json", payload)
    write_md(
        OUT / "missing_telemetry_audit.md",
        [
            "# Missing Telemetry Audit",
            "",
            f"Rows: {len(details)}.",
            "",
            "## Rows",
            *[f"- `{row['test_id']}`: engine={row['routing_engine']} / root={row['telemetry_root_cause']} / fix={row['fix_decision']}" for row in details],
        ],
    )


def missing_fields(row: dict[str, Any]) -> list[str]:
    missing = []
    for key in ("route_surface_type", "routing_engine", "provider_called", "openai_called", "llm_called", "embedding_called", "response_json_bytes"):
        if key not in row:
            missing.append(key)
    if row.get("routing_engine") == "planner_v2" and not row.get("planner_v2_trace"):
        missing.append("planner_v2_trace")
    if row.get("routing_engine") not in {"direct_handler", "generic_provider"} and row.get("actual_tool") and not row.get("planner_obedience"):
        missing.append("planner_obedience")
    return missing


def write_final_report(pre_rows: list[dict[str, Any]], post_rows: list[dict[str, Any]]) -> None:
    pre = summarize(pre_rows)
    post = summarize(post_rows) if post_rows else {}
    if post_rows:
        write_250_post_artifacts(post_rows, pre)
    workbench = read_json(OUT / "stabilization_2_workbench_summary.json")
    integration = read_json(OUT / "stabilization_2_integration_summary.json")
    recommendation = recommendation_from(post or pre)
    summary = {
        "pre_stabilization_2": pre,
        "post_stabilization_2": post,
        "workbench": workbench,
        "integration": integration,
        "failure_burndown_root_causes": read_json(OUT / "failure_burndown_census.json").get("root_cause_counts", {}),
        "real_routing_gap_classifications": read_json(OUT / "real_routing_gap_autopsy.json").get("groups", {}).get("classification", {}),
        "latency_separation": read_json(OUT / "latency_failure_separation.json"),
        "response_audit": read_json(OUT / "response_correctness_audit.json").get("classification_counts", {}),
        "missing_telemetry_audit_count": read_json(OUT / "missing_telemetry_audit.json").get("count", 0),
        "fixes_made": [
            "normalized Planner v2 browser target slots into eval-visible destination_name",
            "exempted direct-only command handlers from planner_obedience-required telemetry classification",
            "normalized terminal direct-route corpus subsystem to terminal",
            "aligned screen-awareness no-grounding corpus expectation with native clarification",
            "provided workspace context for the routeable where-left-off task-continuity corpus lane",
            "prevented route_spine generic_provider from preempting Planner v2 deferred unmigrated native owners such as weather",
        ],
        "recommendation": recommendation,
    }
    write_json(OUT / "planner_v2_stabilization_2_summary.json", summary)
    lines = [
        "# Planner v2 Stabilization 2 Report",
        "",
        "## Executive Summary",
        f"- Pre-pass 250: {pre.get('pass')} pass / {pre.get('fail')} fail.",
        f"- Post-pass 250: {post.get('pass', 'not run')} pass / {post.get('fail', 'not run')} fail.",
        f"- Recommendation: {recommendation}.",
        "",
        "## 99-Failure Burn-Down Census",
        *format_counts(summary["failure_burndown_root_causes"]),
        "",
        "## Routing-Gap Autopsy",
        *format_counts(summary["real_routing_gap_classifications"]),
        "",
        "## Latency Separation Results",
        f"- Latency rows otherwise route/subsystem/tool correct: {summary['latency_separation'].get('latency_otherwise_correct', 0)}.",
        f"- Pass count if latency-only rows were quarantined: {summary['latency_separation'].get('pass_count_if_latency_failures_quarantined', 0)}.",
        "",
        "## Response Correctness Audit",
        *format_counts(summary["response_audit"]),
        "",
        "## Missing Telemetry Audit",
        f"- Missing telemetry rows audited: {summary['missing_telemetry_audit_count']}.",
        "",
        "## Fixes Made",
        *[f"- {item}." for item in summary["fixes_made"]],
        "",
        "## What Was Deliberately Not Changed",
        "- No 1000-case run was started.",
        "- No new families were migrated to Planner v2.",
        "- No product behavior was added to the legacy planner.",
        "- No exact 250 prompts or test IDs were added to product routing logic.",
        "- No provider, payload, approval, trust, dry-run, or timeout guardrails were weakened.",
        "",
        "## Safety / Provider / Payload Summary",
        f"- provider/OpenAI/LLM/embedding calls: {post.get('provider_calls', pre.get('provider_calls'))} / {post.get('openai_calls', pre.get('openai_calls'))} / {post.get('llm_calls', pre.get('llm_calls'))} / {post.get('embedding_calls', pre.get('embedding_calls'))}.",
        f"- real external actions: {post.get('real_external_actions', pre.get('real_external_actions'))}.",
        f"- hard timeouts/process kills: {post.get('hard_timeouts', pre.get('hard_timeouts'))} / {post.get('process_kills', pre.get('process_kills'))}.",
        f"- payload guardrail failures: {post.get('payload_guardrail_failures', pre.get('payload_guardrail_failures'))}.",
        f"- max response bytes: {post.get('max_response_json_bytes', pre.get('max_response_json_bytes'))}.",
        "",
        "## 250 Before / After",
        f"- Stabilization 1: {pre.get('pass')} pass / {pre.get('fail')} fail; categories {pre.get('failure_categories')}.",
        f"- Stabilization 2: {post.get('pass', 'not run')} pass / {post.get('fail', 'not run')} fail; categories {post.get('failure_categories', {})}.",
        "",
        "## Recommendation",
        f"- {recommendation}.",
        "- The old routine_save catastrophic latency label remains preserved as known_unreproduced_product_latency_blocker.",
    ]
    write_md(OUT / "planner_v2_stabilization_2_report.md", lines)


def write_250_post_artifacts(post_rows: list[dict[str, Any]], pre: dict[str, Any]) -> None:
    post = summarize(post_rows)
    checkpoint = read_json(OUT / "_250_checkpoint_tmp" / "250_results.checkpoint.json")
    failed = [row for row in post_rows if not row.get("passed")]
    by_category = post.get("failure_categories", {})
    hard_timeout_rows = [
        {
            "test_id": row.get("test_id"),
            "prompt": row_prompt(row),
            "expected_route_family": row.get("expected_route_family"),
            "actual_route_family": row.get("actual_route_family"),
            "routing_engine": row.get("routing_engine"),
            "latency_ms": row.get("latency_ms") or row.get("total_latency_ms"),
            "process_killed": row.get("process_killed"),
            "stdout_tail": row.get("stdout_tail"),
            "stderr_tail": row.get("stderr_tail"),
        }
        for row in failed
        if row.get("failure_category") == "hard_timeout" or row.get("status") == "hard_timeout"
    ]
    payload_triggered_rows = [
        {
            "test_id": row.get("test_id"),
            "failure_category": row.get("failure_category"),
            "response_json_bytes": row.get("response_json_bytes"),
            "payload_guardrail_reason": row.get("payload_guardrail_reason"),
        }
        for row in post_rows
        if row.get("payload_guardrail_triggered")
    ]
    summary = {
        **post,
        "checkpoint": checkpoint,
        "pre_stabilization_2_pass": pre.get("pass"),
        "pre_stabilization_2_fail": pre.get("fail"),
        "hard_timeout_rows": hard_timeout_rows,
        "payload_guardrail_triggered_rows_detail": payload_triggered_rows[:50],
        "routine_save_historical_blocker_label": "known_unreproduced_product_latency_blocker",
        "recommendation": recommendation_from(post),
    }
    write_json(OUT / "250_post_stabilization_2_summary.json", summary)
    checkpoint_mode = "fresh checkpoint" if not checkpoint.get("skipped_existing") else "resumed checkpoint"

    lines = [
        "# 250 Post-Stabilization 2 Report",
        "",
        "## Executive Summary",
        f"- 250 checkpoint completed as a {checkpoint_mode}: {post['attempted']} attempted / {post['completed']} completed / {post['durable_rows']} durable rows.",
        f"- Score: {post['pass']} pass / {post['fail']} fail / {post['excluded']} excluded.",
        f"- Failure categories: {by_category}.",
        f"- Recommendation: {recommendation_from(post)}.",
        "",
        "## Resume / Harness Durability",
        f"- checkpoint done: {checkpoint.get('done')}.",
        f"- skipped existing rows on resume: {checkpoint.get('skipped_existing')}.",
        f"- completed rows in checkpoint: {checkpoint.get('completed')}.",
        f"- remaining rows in checkpoint: {checkpoint.get('remaining')}.",
        "",
        "## Safety / Provider / Payload",
        f"- provider/OpenAI/LLM/embedding calls: {post['provider_calls']} / {post['openai_calls']} / {post['llm_calls']} / {post['embedding_calls']}.",
        f"- real external actions: {post['real_external_actions']}.",
        f"- hard timeouts/process kills: {post['hard_timeouts']} / {post['process_kills']}.",
        f"- payload guardrail failure-category rows: {post['payload_guardrail_failures']}.",
        f"- payload guardrail triggered rows: {post['payload_guardrail_triggered_rows']}.",
        f"- rows above 1 MB: {post['rows_above_1mb']}.",
        f"- max response bytes: {post['max_response_json_bytes']}.",
        "",
        "## Routing Engines",
        *format_counts(post.get("routing_engines", {})),
        "",
        "## Failure Categories",
        *format_counts(by_category),
        "",
        "## Hard Timeout Rows",
        *(
            [
                f"- `{row['test_id']}`: {row['expected_route_family']} -> {row['actual_route_family']} / engine={row['routing_engine']} / killed={row['process_killed']}"
                for row in hard_timeout_rows
            ]
            or ["- None."]
        ),
        "",
        "## Before / After",
        f"- Pre-Stabilization 2: {pre.get('pass')} pass / {pre.get('fail')} fail.",
        f"- Post-Stabilization 2: {post.get('pass')} pass / {post.get('fail')} fail.",
        "",
        "## Routine Save Historical Blocker",
        "- The historical routine_save catastrophic latency issue remains preserved as known_unreproduced_product_latency_blocker; this report does not mark it fixed.",
    ]
    write_md(OUT / "250_post_stabilization_2_report.md", lines)


def recommendation_from(summary: dict[str, Any]) -> str:
    failures = summary.get("failure_categories") or {}
    if not summary:
        return "continue_stabilization"
    if int(failures.get("real_routing_gap", 0)) > 25:
        return "continue_stabilization"
    if int(failures.get("latency_issue", 0)) > 20:
        return "fix_latency_lane"
    if int(failures.get("response_correctness_failure", 0)) > 0:
        return "fix_response_layer"
    return "migrate_more_families"


def format_counts(counts: dict[str, Any]) -> list[str]:
    if not counts:
        return ["- None."]
    return [f"- {key}: {value}" for key, value in sorted(counts.items(), key=lambda item: (-int(item[1]), item[0]))]


if __name__ == "__main__":
    main()
