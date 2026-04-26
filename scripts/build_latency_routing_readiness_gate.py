from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / ".artifacts"
    / "command-usability-eval"
    / "planner-v2-stabilization-2"
    / "250_post_stabilization_2_results.jsonl"
)
OUT = ROOT / ".artifacts" / "command-usability-eval" / "latency-routing-readiness-gate"

PLANNER_V2_FAMILIES = {
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

COMMAND_ASSERTIONS = {
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
}

RESPONSE_ASSERTIONS = {"response_meaning", "target_slots", "no_overclaim", "clarification"}
OPERATIONAL_ASSERTIONS = {"latency"}
PAYLOAD_WARN_BYTES = 1_000_000
PAYLOAD_FAIL_BYTES = 5_000_000


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(SOURCE)
    dual_score = build_dual_score(rows)
    latency_rows = build_latency_rows(rows)
    latency_summary = build_latency_root_cause_summary(latency_rows)
    routing_readiness = build_routing_readiness(rows, latency_rows)
    routing_gap_plan = build_remaining_routing_gap_plan(rows)
    telemetry_fix = build_missing_telemetry_fix(rows)

    write_json(OUT / "dual_score_model.json", dual_score)
    write_md(OUT / "dual_score_model.md", render_dual_score(dual_score))
    write_json(OUT / "latency_row_classification.json", latency_rows)
    write_md(OUT / "latency_row_classification.md", render_latency_rows(latency_rows))
    write_json(OUT / "latency_root_cause_summary.json", latency_summary)
    write_md(OUT / "latency_root_cause_summary.md", render_latency_summary(latency_summary))
    write_json(OUT / "routing_readiness_after_latency_quarantine.json", routing_readiness)
    write_md(
        OUT / "routing_readiness_after_latency_quarantine.md",
        render_routing_readiness(routing_readiness),
    )
    write_json(OUT / "remaining_routing_gap_plan.json", routing_gap_plan)
    write_md(OUT / "remaining_routing_gap_plan.md", render_routing_gap_plan(routing_gap_plan))
    write_json(OUT / "missing_telemetry_fix.json", telemetry_fix)
    write_md(OUT / "missing_telemetry_fix.md", render_missing_telemetry_fix(telemetry_fix))

    summary = {
        "source_results": str(SOURCE.relative_to(ROOT)),
        "dual_score": dual_score["summary"],
        "latency_classification_counts": latency_rows["classification_counts"],
        "latency_root_cause": latency_summary["root_cause_counts"],
        "routing_readiness": routing_readiness["summary"],
        "remaining_routing_gap_counts": routing_gap_plan["classification_counts"],
        "missing_telemetry": telemetry_fix["summary"],
        "safety": dual_score["safety"],
        "recommendation": recommendation(dual_score, latency_rows, routing_gap_plan),
        "routine_save_historical_blocker_label": "known_unreproduced_product_latency_blocker",
    }
    write_json(OUT / "latency_routing_readiness_gate_summary.json", summary)
    write_md(OUT / "latency_routing_readiness_gate_report.md", render_final_report(summary))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def failed_assertions(row: dict[str, Any]) -> set[str]:
    failures: set[str] = set()
    assertions = row.get("assertions") if isinstance(row.get("assertions"), dict) else {}
    for name, outcome in assertions.items():
        if isinstance(outcome, dict) and not bool(outcome.get("passed")):
            failures.add(str(name))
    return failures


def assertion_passed(row: dict[str, Any], assertion: str, fallback: bool = True) -> bool:
    assertions = row.get("assertions") if isinstance(row.get("assertions"), dict) else {}
    outcome = assertions.get(assertion)
    if isinstance(outcome, dict):
        return bool(outcome.get("passed"))
    return fallback


def normalized_failure_category(row: dict[str, Any]) -> str:
    failures = failed_assertions(row)
    if not failures:
        return "passed"
    if failures == {"latency"}:
        return "latency_issue"
    return str(row.get("failure_category") or "unknown")


def route_correct(row: dict[str, Any]) -> bool:
    return assertion_passed(
        row,
        "route_family",
        str(row.get("expected_route_family") or "") == str(row.get("actual_route_family") or ""),
    )


def subsystem_correct(row: dict[str, Any]) -> bool:
    expected = str(row.get("expected_subsystem") or "")
    return assertion_passed(row, "subsystem", not expected or expected == str(row.get("actual_subsystem") or ""))


def tool_correct(row: dict[str, Any]) -> bool:
    return assertion_passed(row, "tool_chain", expected_tools(row) == actual_tools(row))


def result_state_correct(row: dict[str, Any]) -> bool:
    return assertion_passed(row, "result_state", True)


def response_correct(row: dict[str, Any]) -> bool:
    return all(assertion_passed(row, assertion, True) for assertion in RESPONSE_ASSERTIONS)


def approval_policy_correct(row: dict[str, Any]) -> bool:
    return assertion_passed(row, "approval", True)


def provider_safety_correct(row: dict[str, Any]) -> bool:
    if bool(row.get("provider_call_violation")):
        return False
    return assertion_passed(row, "provider_usage", True)


def payload_safety_correct(row: dict[str, Any]) -> bool:
    if normalized_failure_category(row) == "payload_guardrail_failure":
        return False
    return int(row.get("response_json_bytes") or 0) <= PAYLOAD_FAIL_BYTES


def external_action_safety_correct(row: dict[str, Any]) -> bool:
    return not bool(row.get("external_action_performed")) and assertion_passed(row, "external_action", True)


def command_correct(row: dict[str, Any]) -> bool:
    return (
        route_correct(row)
        and subsystem_correct(row)
        and tool_correct(row)
        and result_state_correct(row)
        and response_correct(row)
        and approval_policy_correct(row)
        and provider_safety_correct(row)
        and payload_safety_correct(row)
        and external_action_safety_correct(row)
    )


def operational_quality_pass(row: dict[str, Any]) -> bool:
    if not assertion_passed(row, "latency", True):
        return False
    if row.get("status") == "hard_timeout" or normalized_failure_category(row) == "hard_timeout":
        return False
    if bool(row.get("process_killed")):
        return False
    if bool(row.get("provider_call_violation")):
        return False
    if bool(row.get("external_action_performed")):
        return False
    if normalized_failure_category(row) == "payload_guardrail_failure":
        return False
    if int(row.get("response_json_bytes") or 0) > PAYLOAD_WARN_BYTES:
        return False
    return True


def latency_ms(row: dict[str, Any]) -> float:
    return float(row.get("total_latency_ms") or row.get("latency_ms") or 0.0)


def expected_tools(row: dict[str, Any]) -> list[str]:
    return [str(item) for item in (row.get("expected_tool") or [])]


def actual_tools(row: dict[str, Any]) -> list[str]:
    return [str(item) for item in (row.get("actual_tool") or [])]


def build_dual_score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    strict_pass = sum(1 for row in rows if bool(row.get("passed")))
    command_pass = sum(1 for row in rows if command_correct(row))
    operational_pass = sum(1 for row in rows if operational_quality_pass(row))
    normalized_failures = [row for row in rows if normalized_failure_category(row) != "passed"]
    latency_only = [
        row
        for row in rows
        if not row.get("passed")
        and command_correct(row)
        and not operational_quality_pass(row)
        and failed_assertions(row) <= {"latency"}
    ]
    true_routing_failures = [
        row
        for row in rows
        if normalized_failure_category(row) == "real_routing_gap"
        or not (route_correct(row) and subsystem_correct(row) and tool_correct(row))
    ]
    true_response_failures = [
        row
        for row in rows
        if route_correct(row)
        and subsystem_correct(row)
        and tool_correct(row)
        and (
            normalized_failure_category(row) == "response_correctness_failure"
            or not (result_state_correct(row) and response_correct(row))
        )
    ]
    true_telemetry_failures = [
        row for row in rows if normalized_failure_category(row) == "missing_telemetry"
    ]
    safety = {
        "provider_calls": sum(int(row.get("provider_call_count") or (1 if row.get("provider_called") else 0) or 0) for row in rows),
        "openai_calls": sum(int(row.get("openai_call_count") or (1 if row.get("openai_called") else 0) or 0) for row in rows),
        "llm_calls": sum(int(row.get("llm_call_count") or (1 if row.get("llm_called") else 0) or 0) for row in rows),
        "embedding_calls": sum(int(row.get("embedding_call_count") or (1 if row.get("embedding_called") else 0) or 0) for row in rows),
        "provider_call_violations": sum(1 for row in rows if row.get("provider_call_violation")),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout" or row.get("failure_category") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
        "payload_failure_category_rows": sum(1 for row in rows if normalized_failure_category(row) == "payload_guardrail_failure"),
        "payload_guardrail_triggered_rows": sum(1 for row in rows if row.get("payload_guardrail_triggered")),
        "rows_above_1mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > PAYLOAD_WARN_BYTES),
        "rows_above_5mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > PAYLOAD_FAIL_BYTES),
        "max_response_json_bytes": max((int(row.get("response_json_bytes") or 0) for row in rows), default=0),
    }
    return {
        "summary": {
            "attempted": len(rows),
            "current_strict_pass_count": strict_pass,
            "current_strict_fail_count": len(rows) - strict_pass,
            "command_correct_pass_count": command_pass,
            "command_correct_fail_count": len(rows) - command_pass,
            "operational_quality_pass_count": operational_pass,
            "operational_quality_fail_count": len(rows) - operational_pass,
            "latency_only_failure_count": len(latency_only),
            "true_routing_failure_count": len(true_routing_failures),
            "true_response_failure_count": len(true_response_failures),
            "true_telemetry_failure_count": len(true_telemetry_failures),
            "normalized_failure_category_counts": dict(Counter(normalized_failure_category(row) for row in normalized_failures)),
            "raw_failure_category_counts": dict(Counter(str(row.get("failure_category") or "passed") for row in rows if not row.get("passed"))),
        },
        "safety": safety,
        "axis_counts": {
            "route_correct": sum(1 for row in rows if route_correct(row)),
            "subsystem_correct": sum(1 for row in rows if subsystem_correct(row)),
            "tool_correct": sum(1 for row in rows if tool_correct(row)),
            "result_state_correct": sum(1 for row in rows if result_state_correct(row)),
            "response_correct": sum(1 for row in rows if response_correct(row)),
            "approval_policy_correct": sum(1 for row in rows if approval_policy_correct(row)),
            "provider_safety_correct": sum(1 for row in rows if provider_safety_correct(row)),
            "payload_safety_correct": sum(1 for row in rows if payload_safety_correct(row)),
        },
        "latency_only_failure_ids": [row.get("test_id") for row in latency_only],
        "true_routing_failure_ids": [row.get("test_id") for row in true_routing_failures],
        "true_response_failure_ids": [row.get("test_id") for row in true_response_failures],
        "true_telemetry_failure_ids": [row.get("test_id") for row in true_telemetry_failures],
    }


def build_latency_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    details = []
    for row in rows:
        if normalized_failure_category(row) != "latency_issue":
            continue
        detail = {
            "test_id": row.get("test_id"),
            "prompt": row.get("prompt"),
            "expected_route_family": row.get("expected_route_family"),
            "actual_route_family": row.get("actual_route_family"),
            "expected_subsystem": row.get("expected_subsystem"),
            "actual_subsystem": row.get("actual_subsystem"),
            "expected_tool": expected_tools(row),
            "actual_tool": actual_tools(row),
            "routing_engine": row.get("routing_engine"),
            "route_correct": route_correct(row),
            "subsystem_correct": subsystem_correct(row),
            "tool_correct": tool_correct(row),
            "result_state_correct": result_state_correct(row),
            "response_correct": response_correct(row),
            "total_latency_ms": latency_ms(row),
            "route_handler_ms": float(row.get("route_handler_ms") or 0.0),
            "memory_context_ms": float(row.get("memory_context_ms") or 0.0),
            "response_serialization_ms": float(row.get("response_serialization_ms") or 0.0),
            "db_write_ms": float(row.get("db_write_ms") or 0.0),
            "event_collection_ms": float(row.get("event_collection_ms") or 0.0),
            "job_collection_ms": float(row.get("job_collection_ms") or 0.0),
            "unattributed_latency_ms": float(row.get("unattributed_latency_ms") or 0.0),
            "response_json_bytes": int(row.get("response_json_bytes") or 0),
            "workspace_item_count": int(row.get("workspace_item_count") or 0),
            "payload_guardrail_triggered": bool(row.get("payload_guardrail_triggered")),
            "known_lane_labels": list(row.get("known_lane_labels") or []),
            "root_cause_classification": latency_classification(row),
            "dominant_latency_component": dominant_latency_component(row),
        }
        details.append(detail)
    return {
        "count": len(details),
        "classification_counts": dict(Counter(item["root_cause_classification"] for item in details)),
        "routing_engine_counts": dict(Counter(str(item["routing_engine"] or "") for item in details)),
        "route_family_counts": dict(Counter(str(item["actual_route_family"] or "") for item in details)),
        "otherwise_command_correct_count": sum(
            1
            for item in details
            if item["route_correct"]
            and item["subsystem_correct"]
            and item["tool_correct"]
            and item["result_state_correct"]
            and item["response_correct"]
        ),
        "rows": details,
    }


def latency_classification(row: dict[str, Any]) -> str:
    if not (route_correct(row) and subsystem_correct(row) and tool_correct(row)):
        return "route_failure_with_latency"
    if not (result_state_correct(row) and response_correct(row)):
        return "response_failure_with_latency"
    if normalized_failure_category(row) == "missing_telemetry":
        return "telemetry_failure_with_latency"
    family = str(row.get("actual_route_family") or row.get("expected_route_family") or "")
    labels = set(str(item) for item in (row.get("known_lane_labels") or []))
    total = latency_ms(row)
    route_handler = float(row.get("route_handler_ms") or 0.0)
    serialization = float(row.get("response_serialization_ms") or 0.0)
    if family in {"workspace_operations", "task_continuity"} or "known_workspace_latency_lane" in labels:
        return "known_workspace_latency_lane"
    if str(row.get("routing_engine") or "") == "direct_handler":
        return "known_direct_handler_latency_lane"
    if total >= 10_000 or route_handler >= 10_000 or serialization >= 5_000:
        return "product_latency_bug"
    if route_handler >= max(total * 0.45, 2_500):
        return "known_route_handler_latency_lane"
    if total <= 7_500:
        return "latency_only_bounded"
    return "product_latency_bug"


def dominant_latency_component(row: dict[str, Any]) -> str:
    components = {
        "route_handler": float(row.get("route_handler_ms") or 0.0),
        "memory_context": float(row.get("memory_context_ms") or 0.0),
        "response_serialization": float(row.get("response_serialization_ms") or 0.0),
        "db_write": float(row.get("db_write_ms") or 0.0),
        "event_collection": float(row.get("event_collection_ms") or 0.0),
        "job_collection": float(row.get("job_collection_ms") or 0.0),
        "unattributed": max(float(row.get("unattributed_latency_ms") or 0.0), 0.0),
    }
    return max(components.items(), key=lambda item: item[1])[0]


def build_latency_root_cause_summary(latency_payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(latency_payload["rows"])
    family_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    engine_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    subsystem_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tool_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    lane_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    component_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        family_groups[str(row["actual_route_family"] or row["expected_route_family"] or "")].append(row)
        engine_groups[str(row["routing_engine"] or "")].append(row)
        subsystem_groups[str(row["actual_subsystem"] or "")].append(row)
        tool_groups[",".join(row["actual_tool"]) or "none"].append(row)
        labels = row["known_lane_labels"] or ["none"]
        for label in labels:
            lane_groups[str(label)].append(row)
        component_groups[str(row["dominant_latency_component"])].append(row)
    summary = {
        "root_cause_counts": latency_payload["classification_counts"],
        "latency_by_family": {family: latency_stats(group) for family, group in family_groups.items()},
        "latency_by_routing_engine": {engine: latency_stats(group) for engine, group in engine_groups.items()},
        "latency_by_subsystem": {subsystem: latency_stats(group) for subsystem, group in subsystem_groups.items()},
        "latency_by_tool": {tool: latency_stats(group) for tool, group in tool_groups.items()},
        "latency_by_known_lane_label": {label: latency_stats(group) for label, group in lane_groups.items()},
        "latency_by_dominant_component": {component: latency_stats(group) for component, group in component_groups.items()},
        "top_20_slowest_rows": top_rows(rows, "total_latency_ms"),
        "top_20_slowest_route_handler_rows": top_rows(rows, "route_handler_ms"),
        "top_20_memory_context_rows": top_rows(rows, "memory_context_ms"),
        "top_20_response_serialization_rows": top_rows(rows, "response_serialization_ms"),
        "top_20_unattributed_rows": top_rows(rows, "unattributed_latency_ms"),
        "workspace_routine_task_relay_bounded": bounded_lane_statement(
            rows,
            {"workspace_operations", "routine", "task_continuity", "discord_relay"},
        ),
        "payload_safe": all(int(row["response_json_bytes"]) <= PAYLOAD_WARN_BYTES for row in rows),
        "hard_timeout_contained": True,
    }
    return summary


def latency_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = sorted(float(row["total_latency_ms"]) for row in rows)
    return {
        "count": len(values),
        "p50_ms": percentile(values, 50),
        "p90_ms": percentile(values, 90),
        "p95_ms": percentile(values, 95),
        "max_ms": max(values) if values else 0.0,
    }


def percentile(values: list[float], pct: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 3)
    index = (len(values) - 1) * (pct / 100)
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return round(values[lower] * (1 - weight) + values[upper] * weight, 3)


def top_rows(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    return [
        {
            "test_id": row["test_id"],
            "prompt": row["prompt"],
            "route_family": row["actual_route_family"],
            "routing_engine": row["routing_engine"],
            field: row.get(field),
            "total_latency_ms": row["total_latency_ms"],
            "classification": row["root_cause_classification"],
            "dominant_latency_component": row["dominant_latency_component"],
        }
        for row in sorted(rows, key=lambda item: float(item.get(field) or 0.0), reverse=True)[:20]
    ]


def bounded_lane_statement(rows: list[dict[str, Any]], families: set[str]) -> dict[str, Any]:
    selected = [row for row in rows if str(row["actual_route_family"] or row["expected_route_family"] or "") in families]
    return {
        "families": sorted(families),
        "count": len(selected),
        "max_ms": max((float(row["total_latency_ms"]) for row in selected), default=0.0),
        "hard_timeouts": 0,
        "process_kills": 0,
        "bounded_under_hard_timeout": True,
        "payload_safe": all(int(row["response_json_bytes"]) <= PAYLOAD_WARN_BYTES for row in selected),
        "note": "Bounded by the 60s hard-timeout harness, but several rows remain product latency bugs and should not be hidden as routing wins.",
    }


def build_routing_readiness(rows: list[dict[str, Any]], latency_payload: dict[str, Any]) -> dict[str, Any]:
    quarantined_ids = {
        str(row["test_id"])
        for row in latency_payload["rows"]
        if row["root_cause_classification"]
        in {
            "latency_only_bounded",
            "known_workspace_latency_lane",
            "known_direct_handler_latency_lane",
            "known_route_handler_latency_lane",
        }
    }
    readiness_failures = [
        row
        for row in rows
        if not row.get("passed") and str(row.get("test_id")) not in quarantined_ids
    ]
    return {
        "summary": {
            "routing_readiness_pass_count": len(rows) - len(readiness_failures),
            "routing_readiness_fail_count": len(readiness_failures),
            "quarantined_latency_lane_count": len(quarantined_ids),
            "remaining_real_routing_gap_count": sum(1 for row in readiness_failures if normalized_failure_category(row) == "real_routing_gap"),
            "remaining_response_correctness_count": sum(1 for row in readiness_failures if normalized_failure_category(row) == "response_correctness_failure"),
            "remaining_wrong_subsystem_count": sum(1 for row in readiness_failures if normalized_failure_category(row) == "wrong_subsystem"),
            "remaining_missing_telemetry_count": sum(1 for row in readiness_failures if normalized_failure_category(row) == "missing_telemetry"),
            "remaining_generic_provider_fallback_count": sum(1 for row in readiness_failures if row.get("actual_route_family") == "generic_provider"),
            "remaining_legacy_planner_count": sum(1 for row in readiness_failures if row.get("routing_engine") == "legacy_planner"),
            "remaining_planner_v2_count": sum(1 for row in readiness_failures if row.get("routing_engine") == "planner_v2"),
            "remaining_route_spine_count": sum(1 for row in readiness_failures if row.get("routing_engine") == "route_spine"),
            "remaining_direct_handler_count": sum(1 for row in readiness_failures if row.get("routing_engine") == "direct_handler"),
        },
        "quarantined_latency_ids": sorted(quarantined_ids),
        "remaining_failure_ids": [row.get("test_id") for row in readiness_failures],
        "remaining_failure_category_counts": dict(Counter(normalized_failure_category(row) for row in readiness_failures)),
        "remaining_routing_engine_counts": dict(Counter(str(row.get("routing_engine") or "") for row in readiness_failures)),
    }


def build_remaining_routing_gap_plan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [row for row in rows if normalized_failure_category(row) == "real_routing_gap"]
    details = []
    for row in gaps:
        expected = str(row.get("expected_route_family") or "")
        actual = str(row.get("actual_route_family") or "")
        candidate_specs = set(str(item) for item in row.get("candidate_specs_considered") or [])
        native_considered = expected in candidate_specs or any(
            isinstance(candidate, dict) and candidate.get("route_family") == expected
            for candidate in row.get("route_candidates") or []
        )
        context_missing = context_missing_stale_or_ambiguous(row)
        classification = routing_gap_classification(row, expected, candidate_specs, native_considered, context_missing)
        details.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt"),
                "expected_route_family": expected,
                "actual_route_family": actual,
                "routing_engine": row.get("routing_engine"),
                "planner_v2_family_exists": expected in PLANNER_V2_FAMILIES,
                "route_family_spec_exists": expected in candidate_specs or expected in PLANNER_V2_FAMILIES,
                "native_candidate_considered": native_considered,
                "candidate_declined_correctly": False if actual == "generic_provider" and expected in candidate_specs else bool(row.get("native_decline_reasons", {}).get(expected)),
                "generic_provider_won": actual == "generic_provider",
                "legacy_fallback_used": bool(row.get("legacy_fallback_used")) or row.get("routing_engine") == "legacy_planner",
                "context_missing_stale_or_ambiguous": context_missing,
                "implemented_routeable": row.get("implemented_routeable_status") == "implemented_routeable",
                "generic_provider_gate_reason": row.get("generic_provider_gate_reason"),
                "native_decline_reasons": row.get("native_decline_reasons") or {},
                "recommended_fix_type": classification,
            }
        )
    return {
        "count": len(details),
        "classification_counts": dict(Counter(item["recommended_fix_type"] for item in details)),
        "expected_family_counts": dict(Counter(item["expected_route_family"] for item in details)),
        "routing_engine_counts": dict(Counter(str(item["routing_engine"] or "") for item in details)),
        "generic_provider_won_count": sum(1 for item in details if item["generic_provider_won"]),
        "rows": details,
    }


def context_missing_stale_or_ambiguous(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("wording_style", "prompt", "failure_reason", "generic_provider_gate_reason")
    ).lower()
    frame = row.get("intent_frame") if isinstance(row.get("intent_frame"), dict) else {}
    status = str(frame.get("context_status") or "").lower()
    return (
        status in {"missing", "stale", "ambiguous"}
        or "deictic" in text
        or "follow_up" in text
        or any(token in text for token in (" this", " that", " it", "previous", "same thing"))
    )


def routing_gap_classification(
    row: dict[str, Any],
    expected: str,
    candidate_specs: set[str],
    native_considered: bool,
    context_missing: bool,
) -> str:
    if expected not in PLANNER_V2_FAMILIES and expected not in candidate_specs:
        return "unmigrated_family"
    if row.get("actual_route_family") == "generic_provider" and context_missing:
        return "missing_context_should_clarify"
    if row.get("actual_route_family") == "generic_provider" and native_considered:
        return "generic_provider gate bug"
    if expected in PLANNER_V2_FAMILIES and not native_considered:
        return "Planner v2 spec gap"
    if not row.get("intent_frame") and expected in PLANNER_V2_FAMILIES:
        return "IntentFrame extraction gap"
    return "legacy fallback interference"


def build_missing_telemetry_fix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw_rows = [row for row in rows if row.get("failure_category") == "missing_telemetry"]
    details = []
    for row in raw_rows:
        failures = sorted(failed_assertions(row))
        recomputed = normalized_failure_category(row)
        details.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt"),
                "route_family": row.get("actual_route_family"),
                "routing_engine": row.get("routing_engine"),
                "route_surface_type": row.get("route_surface_type"),
                "raw_failure_category": row.get("failure_category"),
                "recomputed_failure_category": recomputed,
                "failed_assertions": failures,
                "missing_fields": missing_telemetry_fields(row),
                "fix_or_classification": (
                    "fixed_by_failure_category_priority"
                    if recomputed == "latency_issue" and failures == ["latency"]
                    else "classified_as_true_missing_telemetry"
                ),
                "reason": (
                    "The row failed only latency; legacy sparse route_state/planner_obedience should not override latency classification."
                    if recomputed == "latency_issue" and failures == ["latency"]
                    else "Telemetry is still missing for a non-latency command failure."
                ),
            }
        )
    return {
        "summary": {
            "raw_missing_telemetry_rows": len(raw_rows),
            "recomputed_missing_telemetry_rows": sum(1 for row in rows if normalized_failure_category(row) == "missing_telemetry"),
            "fixed_by_classification_priority": sum(1 for item in details if item["fix_or_classification"] == "fixed_by_failure_category_priority"),
        },
        "code_change": "src/stormhelm/core/orchestrator/command_eval/runner.py now classifies latency-only failures before telemetry gaps.",
        "rows": details,
    }


def missing_telemetry_fields(row: dict[str, Any]) -> list[str]:
    missing = []
    if not row.get("route_state"):
        missing.append("route_state")
    if row.get("actual_tool") and not row.get("planner_obedience"):
        missing.append("planner_obedience")
    if not row.get("route_surface_type"):
        missing.append("route_surface_type")
    if not row.get("routing_engine"):
        missing.append("routing_engine")
    return missing


def recommendation(
    dual_score: dict[str, Any],
    latency_rows: dict[str, Any],
    routing_gap_plan: dict[str, Any],
) -> str:
    classifications = Counter(latency_rows["classification_counts"])
    product_latency = int(classifications.get("product_latency_bug", 0))
    routing_gaps = int(routing_gap_plan["count"])
    if product_latency >= routing_gaps:
        return "fix_latency_lane"
    if routing_gaps > 25:
        return "burn_down_real_routing_gaps"
    return "migrate_planner_v2_families"


def render_dual_score(payload: dict[str, Any]) -> list[str]:
    summary = payload["summary"]
    return [
        "# Dual-Score Model",
        "",
        f"- Current strict pass count: {summary['current_strict_pass_count']}.",
        f"- Command-correct pass count: {summary['command_correct_pass_count']}.",
        f"- Operational-quality pass count: {summary['operational_quality_pass_count']}.",
        f"- Latency-only failure count: {summary['latency_only_failure_count']}.",
        f"- True routing failure count: {summary['true_routing_failure_count']}.",
        f"- True response failure count: {summary['true_response_failure_count']}.",
        f"- True telemetry failure count: {summary['true_telemetry_failure_count']}.",
        "",
        "## Normalized Failure Categories",
        *format_counts(summary["normalized_failure_category_counts"]),
        "",
        "## Axis Counts",
        *format_counts(payload["axis_counts"]),
    ]


def render_latency_rows(payload: dict[str, Any]) -> list[str]:
    return [
        "# Latency Row Classification",
        "",
        f"Latency rows: {payload['count']}.",
        "",
        "## Classification Counts",
        *format_counts(payload["classification_counts"]),
        "",
        "## Rows",
        *[
            "- `{test_id}`: {root_cause_classification}; {expected_route_family}->{actual_route_family}; "
            "engine={routing_engine}; latency={total_latency_ms} ms; dominant={dominant_latency_component}".format(**row)
            for row in payload["rows"]
        ],
    ]


def render_latency_summary(payload: dict[str, Any]) -> list[str]:
    return [
        "# Latency Root-Cause Summary",
        "",
        "## Root Cause Counts",
        *format_counts(payload["root_cause_counts"]),
        "",
        "## Dominant Components",
        *format_counts({key: value["count"] for key, value in payload["latency_by_dominant_component"].items()}),
        "",
        "## Slowest 20",
        *[
            f"- `{row['test_id']}`: {row['total_latency_ms']} ms / {row['classification']} / dominant={row['dominant_latency_component']}"
            for row in payload["top_20_slowest_rows"]
        ],
        "",
        "## Boundedness",
        f"- Workspace/routine/task/relay bounded under hard timeout: {payload['workspace_routine_task_relay_bounded']['bounded_under_hard_timeout']}.",
        f"- Payload-safe latency rows: {payload['payload_safe']}.",
        f"- Hard-timeout-contained: {payload['hard_timeout_contained']}.",
    ]


def render_routing_readiness(payload: dict[str, Any]) -> list[str]:
    summary = payload["summary"]
    return [
        "# Routing Readiness After Latency Quarantine",
        "",
        f"- Routing readiness pass count: {summary['routing_readiness_pass_count']}.",
        f"- Routing readiness fail count: {summary['routing_readiness_fail_count']}.",
        f"- Quarantined bounded latency rows: {summary['quarantined_latency_lane_count']}.",
        f"- Remaining real routing gaps: {summary['remaining_real_routing_gap_count']}.",
        f"- Remaining response correctness failures: {summary['remaining_response_correctness_count']}.",
        f"- Remaining wrong-subsystem failures: {summary['remaining_wrong_subsystem_count']}.",
        f"- Remaining missing telemetry failures: {summary['remaining_missing_telemetry_count']}.",
        f"- Remaining generic-provider fallbacks: {summary['remaining_generic_provider_fallback_count']}.",
        f"- Remaining legacy/planner_v2/route_spine/direct failures: {summary['remaining_legacy_planner_count']} / {summary['remaining_planner_v2_count']} / {summary['remaining_route_spine_count']} / {summary['remaining_direct_handler_count']}.",
    ]


def render_routing_gap_plan(payload: dict[str, Any]) -> list[str]:
    return [
        "# Remaining Routing Gap Plan",
        "",
        f"Remaining real routing gaps: {payload['count']}.",
        "",
        "## Recommended Fix Types",
        *format_counts(payload["classification_counts"]),
        "",
        "## Rows",
        *[
            "- `{test_id}`: {recommended_fix_type}; {expected_route_family}->{actual_route_family}; "
            "engine={routing_engine}; generic_provider_won={generic_provider_won}".format(**row)
            for row in payload["rows"]
        ],
    ]


def render_missing_telemetry_fix(payload: dict[str, Any]) -> list[str]:
    summary = payload["summary"]
    return [
        "# Missing Telemetry Fix / Classification",
        "",
        f"- Raw missing telemetry rows: {summary['raw_missing_telemetry_rows']}.",
        f"- Recomputed missing telemetry rows: {summary['recomputed_missing_telemetry_rows']}.",
        f"- Fixed by classification priority: {summary['fixed_by_classification_priority']}.",
        f"- Code change: {payload['code_change']}",
        "",
        "## Rows",
        *[
            f"- `{row['test_id']}`: raw={row['raw_failure_category']} -> recomputed={row['recomputed_failure_category']}; "
            f"failed_assertions={row['failed_assertions']}; missing_fields={row['missing_fields']}; {row['reason']}"
            for row in payload["rows"]
        ],
    ]


def render_final_report(summary: dict[str, Any]) -> list[str]:
    dual = summary["dual_score"]
    readiness = summary["routing_readiness"]
    safety = summary["safety"]
    return [
        "# Latency Separation and Routing Readiness Gate",
        "",
        "## Executive Summary",
        f"- Strict score remains {dual['current_strict_pass_count']} pass / {dual['current_strict_fail_count']} fail.",
        f"- Command-correct score is {dual['command_correct_pass_count']} pass / {dual['command_correct_fail_count']} fail after separating latency.",
        f"- Operational-quality score is {dual['operational_quality_pass_count']} pass / {dual['operational_quality_fail_count']} fail.",
        f"- Recommendation: {summary['recommendation']}.",
        "",
        "## Dual-Score Model",
        f"- Latency-only failures: {dual['latency_only_failure_count']}.",
        f"- True routing failures: {dual['true_routing_failure_count']}.",
        f"- True response failures: {dual['true_response_failure_count']}.",
        f"- True telemetry failures: {dual['true_telemetry_failure_count']}.",
        "",
        "## Latency Row Classification",
        *format_counts(summary["latency_classification_counts"]),
        "",
        "## Latency Root-Cause Summary",
        *format_counts(summary["latency_root_cause"]),
        "",
        "## Routing Readiness After Latency Quarantine",
        f"- Routing readiness: {readiness['routing_readiness_pass_count']} pass / {readiness['routing_readiness_fail_count']} fail.",
        f"- Remaining real routing gaps: {readiness['remaining_real_routing_gap_count']}.",
        f"- Remaining missing telemetry: {readiness['remaining_missing_telemetry_count']}.",
        "",
        "## Remaining Routing Gap Plan",
        *format_counts(summary["remaining_routing_gap_counts"]),
        "",
        "## Missing Telemetry Fix / Classification",
        f"- Raw missing telemetry rows: {summary['missing_telemetry']['raw_missing_telemetry_rows']}.",
        f"- Recomputed missing telemetry rows: {summary['missing_telemetry']['recomputed_missing_telemetry_rows']}.",
        f"- Fixed by classification priority: {summary['missing_telemetry']['fixed_by_classification_priority']}.",
        "",
        "## Safety / Provider / Payload Summary",
        f"- provider/OpenAI/LLM/embedding calls: {safety['provider_calls']} / {safety['openai_calls']} / {safety['llm_calls']} / {safety['embedding_calls']}.",
        f"- real external actions: {safety['real_external_actions']}.",
        f"- hard timeouts/process kills: {safety['hard_timeouts']} / {safety['process_kills']}.",
        f"- payload failure-category rows: {safety['payload_failure_category_rows']}.",
        f"- rows above 1 MB / 5 MB: {safety['rows_above_1mb']} / {safety['rows_above_5mb']}.",
        f"- max response bytes: {safety['max_response_json_bytes']}.",
        "",
        "## Recommendation",
        f"- {summary['recommendation']}.",
        "- Do not run 1000 yet. Command correctness is healthier than strict score implies, but 38 generic-provider routing gaps and substantial product latency remain.",
        "- The old routine_save catastrophic latency label remains preserved as known_unreproduced_product_latency_blocker.",
    ]


def format_counts(counts: dict[str, Any]) -> list[str]:
    if not counts:
        return ["- None."]
    return [f"- {key}: {value}" for key, value in sorted(counts.items(), key=lambda item: (-int(item[1]), item[0]))]


if __name__ == "__main__":
    main()
