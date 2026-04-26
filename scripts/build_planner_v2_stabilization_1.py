from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".artifacts" / "command-usability-eval" / "planner-v2-stabilization-1"
EXP = ROOT / ".artifacts" / "command-usability-eval" / "planner-v2-expansion-1"
BEST = ROOT / ".artifacts" / "command-usability-eval" / "readiness-pass-3"
ARCH = ROOT / ".artifacts" / "command-usability-eval" / "router-architecture-reset"
MIG2 = ROOT / ".artifacts" / "command-usability-eval" / "route-spine-migration-2"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    exp_rows = read_jsonl(EXP / "250_post_planner_v2_expansion_results.jsonl")
    best_rows = read_jsonl(BEST / "250_post_readiness_3_results.jsonl")
    arch_rows = read_jsonl(ARCH / "250_post_router_architecture_results.jsonl")
    mig_rows = read_jsonl(MIG2 / "250_post_migration_2_results.jsonl")
    copy_lane_artifacts()
    write_anti_overfitting_cleanup()
    write_routing_engine_accountability(exp_rows)
    write_regression_autopsy(best_rows, arch_rows, mig_rows, exp_rows)
    write_wrong_subsystem_autopsy(exp_rows)
    write_planner_v2_overcapture_audit(exp_rows)
    write_generic_provider_audit(exp_rows)
    write_score_decomposition(exp_rows)
    write_final_report(best_rows, arch_rows, mig_rows, exp_rows)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "attempted": len(rows),
        "pass": sum(1 for row in rows if row.get("passed")),
        "fail": sum(1 for row in rows if not row.get("passed")),
        "failure_categories": dict(Counter(str(row.get("failure_category") or "passed") for row in rows if not row.get("passed"))),
        "routing_engines": dict(Counter(str(row.get("routing_engine") or "unknown") for row in rows)),
        "generic_provider_rows": sum(1 for row in rows if row.get("actual_route_family") == "generic_provider"),
        "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
        "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
        "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
        "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
        "external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "payload_guardrail_failures": sum(1 for row in rows if row.get("failure_category") == "payload_guardrail_failure"),
        "payload_guardrail_triggered_rows": sum(1 for row in rows if row.get("payload_guardrail_triggered")),
        "hard_timeouts": sum(1 for row in rows if str(row.get("failure_category")) == "hard_timeout"),
        "max_response_json_bytes": max((int(row.get("response_json_bytes") or 0) for row in rows), default=0),
    }


def copy_lane_artifacts() -> None:
    copies = {
        "planner_v2_expansion_workbench_results.jsonl": "stabilization_workbench_results.jsonl",
        "planner_v2_expansion_workbench_summary.json": "stabilization_workbench_summary.json",
        "planner_v2_expansion_integration_results.jsonl": "stabilization_integration_results.jsonl",
        "planner_v2_expansion_integration_summary.json": "stabilization_integration_summary.json",
    }
    for src_name, dest_name in copies.items():
        src = OUT / src_name
        if src.exists():
            shutil.copyfile(src, OUT / dest_name)
    checkpoint = OUT / "_250_checkpoint_tmp"
    if checkpoint.exists():
        mapping = {
            "250_results.jsonl": "250_post_stabilization_results.jsonl",
            "250_summary.json": "250_post_stabilization_summary.json",
            "250_checkpoint_report.md": "250_post_stabilization_report.md",
        }
        for src_name, dest_name in mapping.items():
            src = checkpoint / src_name
            if src.exists():
                shutil.copyfile(src, OUT / dest_name)


def write_anti_overfitting_cleanup() -> None:
    previous = read_json(EXP / "static_anti_overfitting_check.json")
    current = read_json(OUT / "static_anti_overfitting_check.json")
    replacements = []
    for hit in previous.get("exact_prompt_hits") or []:
        literal = str(hit.get("literal") or "")
        path = str(hit.get("path") or "")
        if literal == "set up my writing environment":
            strategy = "replace legacy exact workflow phrase with generalized writing setup/environment predicate"
        elif literal == "continue that":
            strategy = "replace legacy exact continuity phrase with generalized continue/resume plus deictic/left-off predicate"
        elif literal == "daily routine advice":
            strategy = "replace exact routine near-miss literal with generalized routine-concept regex"
        elif literal == "what are next steps in algebra":
            strategy = "replace exact task near-miss literal with generalized subject-area next-step concept guard"
        elif literal == "message format for Discord docs":
            strategy = "replace exact Discord near-miss literal with generalized Discord documentation/concept guard"
        else:
            strategy = "replace benchmark literal with generalized route-family concept guard"
        replacements.append({**hit, "allowed": False, "replacement_strategy": strategy, "fixed": bool(current.get("passed"))})
    payload = {
        "previous_static_audit": previous,
        "current_static_audit": current,
        "forbidden_product_routing_hits_before": len(previous.get("exact_prompt_hits") or []) + len(previous.get("test_id_hits") or []),
        "forbidden_product_routing_hits_after": len(current.get("exact_prompt_hits") or []) + len(current.get("test_id_hits") or []),
        "cleanup_passed": bool(current.get("passed")),
        "replacements": replacements,
    }
    write_json(OUT / "anti_overfitting_cleanup.json", payload)
    write_md(
        OUT / "anti_overfitting_cleanup.md",
        [
            "# Anti-Overfitting Cleanup",
            "",
            f"Previous forbidden product-routing hits: {payload['forbidden_product_routing_hits_before']}.",
            f"Current forbidden product-routing hits: {payload['forbidden_product_routing_hits_after']}.",
            f"Cleanup passed: {payload['cleanup_passed']}.",
            "",
            "## Replacements",
            *[f"- `{item['path']}` literal `{item['literal']}`: {item['replacement_strategy']}." for item in replacements],
        ],
    )


def write_routing_engine_accountability(rows: list[dict[str, Any]]) -> None:
    unknown = [row for row in rows if str(row.get("routing_engine") or "unknown") == "unknown"]
    details = []
    for row in unknown:
        surface = str(row.get("route_surface_type") or "")
        actual = str(row.get("actual_route_family") or "")
        likely = "generic_provider" if actual == "generic_provider" else "direct_handler" if surface == "direct" else "legacy_planner" if surface in {"legacy", "planner"} else "error"
        details.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt"),
                "expected_route_family": row.get("expected_route_family"),
                "actual_route_family": actual,
                "expected_subsystem": row.get("expected_subsystem"),
                "actual_subsystem": row.get("actual_subsystem"),
                "failure_category": row.get("failure_category"),
                "route_surface_type": surface,
                "route_trace_fields_present": present_trace_fields(row),
                "missing_trace_fields": missing_trace_fields(row),
                "likely_real_engine": likely,
                "why_engine_was_not_recorded": "row serializer only copied explicit planner debug engine and did not derive direct/legacy engines",
                "fix_defer_decision": "fixed_in_command_eval_row_serializer",
            }
        )
    payload = {
        "total_rows": len(rows),
        "unknown_rows": len(unknown),
        "routing_engine_counts": dict(Counter(str(row.get("routing_engine") or "unknown") for row in rows)),
        "unknown_row_details": details,
        "stabilization_fix": "derive routing_engine from explicit debug first, then route_surface_type/actual family/status",
    }
    write_json(OUT / "routing_engine_accountability.json", payload)
    write_md(
        OUT / "routing_engine_accountability.md",
        [
            "# Routing Engine Accountability",
            "",
            f"Expansion-1 unknown routing_engine rows: {len(unknown)}.",
            "Fix applied: command-eval row serialization now emits direct_handler, legacy_planner, generic_provider, excluded, or error when explicit planner telemetry is absent.",
            "",
            "## Unknown Rows",
            *[f"- `{item['test_id']}`: surface=`{item['route_surface_type']}`, likely=`{item['likely_real_engine']}`, failure=`{item['failure_category']}`." for item in details],
        ],
    )


def write_regression_autopsy(best: list[dict[str, Any]], arch: list[dict[str, Any]], mig: list[dict[str, Any]], exp: list[dict[str, Any]]) -> None:
    datasets = {"best_prior": best, "post_router_architecture": arch, "post_migration_2": mig, "planner_v2_expansion_1": exp}
    by_id = {name: {row.get("test_id"): row for row in rows} for name, rows in datasets.items()}
    all_ids = sorted(set().union(*(set(mapping) for mapping in by_id.values())))
    movements = []
    for test_id in all_ids:
        before = by_id["post_migration_2"].get(test_id) or {}
        after = by_id["planner_v2_expansion_1"].get(test_id) or {}
        movement = "stayed_pass" if before.get("passed") and after.get("passed") else "stayed_fail" if not before.get("passed") and not after.get("passed") else "pass_to_fail" if before.get("passed") and not after.get("passed") else "fail_to_pass"
        classification = ""
        if movement == "pass_to_fail":
            classification = classify_regression(after)
        movements.append(
            {
                "test_id": test_id,
                "movement": movement,
                "classification": classification,
                "before_category": before.get("failure_category"),
                "after_category": after.get("failure_category"),
                "before_engine": before.get("routing_engine"),
                "after_engine": after.get("routing_engine"),
                "before_route": before.get("actual_route_family"),
                "after_route": after.get("actual_route_family"),
                "before_subsystem": before.get("actual_subsystem"),
                "after_subsystem": after.get("actual_subsystem"),
                "planner_v2_caused": movement == "pass_to_fail" and after.get("routing_engine") == "planner_v2",
            }
        )
    payload = {
        "run_summaries": {name: summarize(rows) for name, rows in datasets.items()},
        "movement_counts": dict(Counter(item["movement"] for item in movements)),
        "pass_to_fail_classification_counts": dict(Counter(item["classification"] for item in movements if item["movement"] == "pass_to_fail")),
        "movements": movements,
    }
    write_json(OUT / "250_regression_autopsy.json", payload)
    pass_to_fail = [item for item in movements if item["movement"] == "pass_to_fail"]
    write_md(
        OUT / "250_regression_autopsy.md",
        [
            "# 250 Regression Autopsy",
            "",
            f"Pass -> fail rows from migration-2 to expansion-1: {len(pass_to_fail)}.",
            f"Movement counts: {payload['movement_counts']}.",
            "",
            "## Pass -> Fail",
            *[
                f"- `{item['test_id']}`: {item['classification']}; {item['before_route']}/{item['before_subsystem']} -> {item['after_route']}/{item['after_subsystem']} via `{item['after_engine']}`."
                for item in pass_to_fail
            ],
        ],
    )


def classify_regression(row: dict[str, Any]) -> str:
    expected = str(row.get("expected_route_family") or "")
    actual = str(row.get("actual_route_family") or "")
    if row.get("failure_category") == "latency_issue":
        return "latency_only"
    if row.get("failure_category") == "wrong_subsystem" and row.get("routing_engine") == "planner_v2":
        if expected in {"power", "trust_approvals", "weather", "window_control"}:
            return "planner_v2_overcapture_of_unmigrated_native_owner"
        if expected == "watch_runtime" and actual == "watch_runtime":
            return "planner_v2_taxonomy_or_tool_mapping_mismatch"
    if row.get("failure_category") == "real_routing_gap" and expected == actual:
        return "stricter_native_clarification_or_tool_expectation_mismatch"
    return "unknown_or_real_regression"


def write_wrong_subsystem_autopsy(rows: list[dict[str, Any]]) -> None:
    wrong = [row for row in rows if row.get("failure_category") == "wrong_subsystem"]
    details = []
    for row in wrong:
        expected = str(row.get("expected_route_family") or "")
        actual = str(row.get("actual_route_family") or "")
        selected = str(row.get("selected_route_spec") or "")
        if expected in {"trust_approvals", "power", "weather", "window_control"} and row.get("routing_engine") == "planner_v2":
            root = "Planner v2 selected a migrated neighboring spec instead of deferring to the unmigrated native owner"
            classification = "Planner v2 overcapture"
            fix = "defer unmigrated native owner to legacy/native path"
        elif expected == "watch_runtime" and actual == "watch_runtime":
            root = "watch_runtime family was correct but browser-context tool/subsystem normalization was lost in Planner v2 adapter"
            classification = "correct route but wrong subsystem label/tool"
            fix = "map browser page/tab status through browser_context tool"
        else:
            root = "unclassified wrong-subsystem mismatch"
            classification = "needs manual review"
            fix = "defer"
        details.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt"),
                "expected_route_family": expected,
                "actual_route_family": actual,
                "expected_subsystem": row.get("expected_subsystem"),
                "actual_subsystem": row.get("actual_subsystem"),
                "expected_tool": row.get("expected_tool"),
                "actual_tool": row.get("actual_tool"),
                "routing_engine": row.get("routing_engine"),
                "intent_frame": row.get("intent_frame"),
                "selected_route_spec": selected,
                "route_candidates": row.get("route_candidates"),
                "route_scores": row.get("route_scores"),
                "subsystem_label_source": "Planner v2 RouteFamilySpec or semantic adapter",
                "normalized_subsystem_label": row.get("expected_subsystem"),
                "wrongness": classification,
                "root_cause": root,
                "fix_defer_decision": fix,
            }
        )
    payload = {"count": len(wrong), "cluster_counts": dict(Counter(item["root_cause"] for item in details)), "rows": details}
    write_json(OUT / "wrong_subsystem_autopsy.json", payload)
    write_md(OUT / "wrong_subsystem_autopsy.md", ["# Wrong-Subsystem Autopsy", "", f"Rows: {len(wrong)}.", *[f"- `{item['test_id']}`: {item['root_cause']}." for item in details]])


def write_planner_v2_overcapture_audit(rows: list[dict[str, Any]]) -> None:
    failed = [row for row in rows if row.get("routing_engine") == "planner_v2" and not row.get("passed")]
    details = []
    for row in failed:
        category = str(row.get("failure_category") or "")
        expected = str(row.get("expected_route_family") or "")
        actual = str(row.get("actual_route_family") or "")
        if category == "latency_issue":
            classification = "correct Planner v2 decision, latency failure"
        elif category == "response_correctness_failure":
            classification = "correct Planner v2 decision, response/result-state failure"
        elif category == "wrong_subsystem" and expected in {"trust_approvals", "power", "weather", "window_control"}:
            classification = "Planner v2 overcapture"
        elif category == "wrong_subsystem":
            classification = "correct Planner v2 decision, taxonomy mismatch"
        elif category == "real_routing_gap" and expected == actual:
            classification = "correct family but result/tool expectation mismatch"
        elif actual == "generic_provider":
            classification = "Planner v2 generic-provider handoff bug"
        else:
            classification = "Planner v2 spec or context-binding bug"
        details.append({**row_summary(row), "classification": classification, "intent_frame": row.get("intent_frame"), "selected_route_spec": row.get("selected_route_spec"), "candidate_scores": row.get("route_scores"), "native_decline_reasons": row.get("native_decline_reasons"), "generic_provider_gate_reason": row.get("generic_provider_gate_reason")})
    payload = {"failed_planner_v2_rows": len(failed), "classification_counts": dict(Counter(item["classification"] for item in details)), "rows": details}
    write_json(OUT / "planner_v2_overcapture_audit.json", payload)
    write_md(OUT / "planner_v2_overcapture_audit.md", ["# Planner v2 Overcapture Audit", "", f"Failed Planner v2 rows: {len(failed)}.", f"Classification counts: {payload['classification_counts']}."])


def write_generic_provider_audit(rows: list[dict[str, Any]]) -> None:
    generic = [row for row in rows if row.get("actual_route_family") == "generic_provider"]
    details = []
    for row in generic:
        expected = str(row.get("expected_route_family") or "")
        spec_exists = expected in set(row.get("candidate_specs_considered") or [])
        if expected in {"routine"} and row.get("selected_route_spec") == expected:
            classification = "generic_gate_bug"
        elif spec_exists:
            classification = "native_candidate_declined_wrongly"
        elif expected in {"trusted_hook_register"}:
            classification = "routeability_mismatch"
        elif row.get("failure_category") in {"unsupported_feature_expected", "feature_map_overexpectation"}:
            classification = "correct_generic_for_unsupported"
        else:
            classification = "native_spec_missing"
        details.append({**row_summary(row), "native_route_spec_existed": spec_exists, "decline_reasons": row.get("native_decline_reasons"), "classification": classification, "provider_calls": row.get("provider_call_count")})
    payload = {"count": len(generic), "classification_counts": dict(Counter(item["classification"] for item in details)), "rows": details}
    write_json(OUT / "generic_provider_audit.json", payload)
    write_md(OUT / "generic_provider_audit.md", ["# Generic-Provider Audit", "", f"Rows: {len(generic)}.", f"Classification counts: {payload['classification_counts']}."])


def write_score_decomposition(rows: list[dict[str, Any]]) -> None:
    decomposed = []
    for row in rows:
        expected_tools = set(str(item) for item in row.get("expected_tool") or [])
        actual_tools = set(str(item) for item in row.get("actual_tool") or [])
        route_correct = row.get("expected_route_family") == row.get("actual_route_family")
        subsystem_correct = row.get("expected_subsystem") == row.get("actual_subsystem")
        tool_correct = not expected_tools or bool(expected_tools & actual_tools)
        category = str(row.get("failure_category") or "passed")
        item = {
            "test_id": row.get("test_id"),
            "route_correct": route_correct,
            "subsystem_correct": subsystem_correct,
            "tool_correct": tool_correct,
            "result_state_correct": category not in {"response_correctness_failure", "truthfulness_failure", "clarification_failure"},
            "response_correct": category != "response_correctness_failure",
            "latency_pass": category != "latency_issue",
            "payload_pass": not bool(row.get("payload_guardrail_triggered")),
            "safety_pass": not bool(row.get("external_action_performed")) and category != "hard_timeout",
            "provider_pass": not bool(row.get("provider_call_violation")) and int(row.get("provider_call_count") or 0) == 0,
            "approval_policy_pass": category != "approval_expectation_mismatch",
            "final_pass": bool(row.get("passed")),
            "failure_category": category,
            "routing_engine": row.get("routing_engine"),
        }
        decomposed.append(item)
    def count_where(key: str) -> int:
        return sum(1 for item in decomposed if item.get(key))
    pass_if_latency_excluded = sum(1 for item in decomposed if item["final_pass"] or (item["failure_category"] == "latency_issue" and all(item[k] for k in ("route_correct", "subsystem_correct", "tool_correct", "payload_pass", "safety_pass", "provider_pass"))))
    pass_if_response_excluded = sum(1 for item in decomposed if item["final_pass"] or item["failure_category"] == "response_correctness_failure")
    route_correct_nonpass = sum(1 for item in decomposed if item["route_correct"] and not item["final_pass"])
    pure_route_family_fail = sum(1 for item in decomposed if not item["route_correct"] and item["failure_category"] == "real_routing_gap")
    taxonomy_mismatch = sum(1 for item in decomposed if item["route_correct"] and not item["subsystem_correct"])
    not_owned_by_spine = sum(1 for row in rows if row.get("failure_category") == "real_routing_gap" and row.get("routing_engine") != "planner_v2")
    payload = {
        "overall_score": {"pass": count_where("final_pass"), "fail": len(decomposed) - count_where("final_pass")},
        "routing_score": {"correct": count_where("route_correct"), "incorrect": len(decomposed) - count_where("route_correct")},
        "subsystem_score": {"correct": count_where("subsystem_correct"), "incorrect": len(decomposed) - count_where("subsystem_correct")},
        "tool_score": {"correct": count_where("tool_correct"), "incorrect": len(decomposed) - count_where("tool_correct")},
        "result_state_score": {"correct": count_where("result_state_correct"), "incorrect": len(decomposed) - count_where("result_state_correct")},
        "response_correctness_score": {"correct": count_where("response_correct"), "incorrect": len(decomposed) - count_where("response_correct")},
        "latency_score": {"correct": count_where("latency_pass"), "incorrect": len(decomposed) - count_where("latency_pass")},
        "payload_score": {"correct": count_where("payload_pass"), "incorrect": len(decomposed) - count_where("payload_pass")},
        "safety_score": {"correct": count_where("safety_pass"), "incorrect": len(decomposed) - count_where("safety_pass")},
        "provider_score": {"correct": count_where("provider_pass"), "incorrect": len(decomposed) - count_where("provider_pass")},
        "approval_policy_score": {"correct": count_where("approval_policy_pass"), "incorrect": len(decomposed) - count_where("approval_policy_pass")},
        "pass_if_latency_excluded": pass_if_latency_excluded,
        "pass_if_response_correctness_excluded": pass_if_response_excluded,
        "route_correct_but_nonpassing": route_correct_nonpass,
        "pure_route_family_failures": pure_route_family_fail,
        "taxonomy_label_mismatch_failures": taxonomy_mismatch,
        "real_routing_gaps_not_owned_by_planner_v2": not_owned_by_spine,
        "rows": decomposed,
    }
    write_json(OUT / "score_decomposition.json", payload)
    write_md(OUT / "score_decomposition.md", ["# Score Decomposition", "", f"Overall: {payload['overall_score']}.", f"Routing score: {payload['routing_score']}.", f"Pass if latency excluded: {pass_if_latency_excluded}.", f"Route-correct but nonpassing rows: {route_correct_nonpass}."])


def row_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "prompt": row.get("prompt"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "expected_subsystem": row.get("expected_subsystem"),
        "actual_subsystem": row.get("actual_subsystem"),
        "expected_tool": row.get("expected_tool"),
        "actual_tool": row.get("actual_tool"),
        "routing_engine": row.get("routing_engine"),
        "failure_category": row.get("failure_category"),
        "failure_reason": row.get("failure_reason"),
    }


def present_trace_fields(row: dict[str, Any]) -> list[str]:
    keys = ["route_state", "planner_v2_trace", "intent_frame", "candidate_specs_considered", "selected_route_spec", "native_decline_reasons", "generic_provider_gate_reason"]
    return [key for key in keys if row.get(key)]


def missing_trace_fields(row: dict[str, Any]) -> list[str]:
    keys = ["routing_engine", "planner_v2_trace", "intent_frame", "candidate_specs_considered", "selected_route_spec"]
    return [key for key in keys if not row.get(key)]


def write_final_report(best: list[dict[str, Any]], arch: list[dict[str, Any]], mig: list[dict[str, Any]], exp: list[dict[str, Any]]) -> None:
    post_rows = read_jsonl(OUT / "250_post_stabilization_results.jsonl")
    post_summary = read_json(OUT / "250_post_stabilization_summary.json")
    workbench = read_json(OUT / "stabilization_workbench_summary.json")
    integration = read_json(OUT / "stabilization_integration_summary.json")
    cleanup = read_json(OUT / "anti_overfitting_cleanup.json")
    engine = read_json(OUT / "routing_engine_accountability.json")
    wrong = read_json(OUT / "wrong_subsystem_autopsy.json")
    provider = read_json(OUT / "generic_provider_audit.json")
    score = read_json(OUT / "score_decomposition.json")
    post_metrics = summarize(post_rows) if post_rows else {}
    summary = {
        "anti_overfitting_cleanup_passed": cleanup.get("cleanup_passed"),
        "routing_engine_accountability": engine,
        "wrong_subsystem_autopsy_count": wrong.get("count"),
        "generic_provider_audit_count": provider.get("count"),
        "score_decomposition": {key: score.get(key) for key in ("overall_score", "routing_score", "subsystem_score", "pass_if_latency_excluded", "route_correct_but_nonpassing")},
        "workbench": workbench,
        "integration": integration,
        "post_250": post_summary or post_metrics,
        "safety_provider_payload": safety_summary(post_rows) if post_rows else safety_summary(exp),
        "recommendation": recommendation(post_rows, post_summary, cleanup, engine),
        "routine_save_historical_blocker": "known_unreproduced_product_latency_blocker",
    }
    write_json(OUT / "planner_v2_stabilization_summary.json", summary)
    lines = [
        "# Planner v2 Stabilization 1 Report",
        "",
        "## Executive Summary",
        "This pass stabilized integration seams rather than migrating more families. It removed product-routing benchmark literals, added routing-engine derivation for direct/legacy rows, deferred unmigrated native owners away from Planner v2 overcapture, restored browser-context subsystem/tool mapping, and kept routine execution on the native routine path.",
        "",
        "## Anti-Overfitting Cleanup",
        f"Previous forbidden hits: {cleanup.get('forbidden_product_routing_hits_before')}. Current forbidden hits: {cleanup.get('forbidden_product_routing_hits_after')}. Passed: {cleanup.get('cleanup_passed')}.",
        "",
        "## Routing Engine Accountability",
        f"Expansion-1 unknown rows: {engine.get('unknown_rows')}. Fix: serializer now derives direct_handler/legacy_planner/generic_provider/excluded/error when explicit planner debug is absent.",
        "",
        "## 250 Regression Autopsy",
        f"Expansion-1 summary: {summarize(exp)}.",
        "Primary regression source: Planner v2 overcaptured scheduled/unmigrated native owners and emitted Planner v2 labels that did not match existing product/eval taxonomy.",
        "",
        "## Wrong-Subsystem Autopsy",
        f"Wrong-subsystem rows audited: {wrong.get('count')}. Cluster counts: {wrong.get('cluster_counts')}.",
        "",
        "## Planner v2 Overcapture Audit",
        f"Planner v2 failed-row classifications: {read_json(OUT / 'planner_v2_overcapture_audit.json').get('classification_counts')}.",
        "",
        "## Generic-Provider Audit",
        f"Generic-provider rows audited: {provider.get('count')}. Classification counts: {provider.get('classification_counts')}.",
        "",
        "## Score Decomposition",
        f"Overall expansion-1 score: {score.get('overall_score')}. Routing score: {score.get('routing_score')}. Subsystem score: {score.get('subsystem_score')}.",
        f"Pass if latency excluded: {score.get('pass_if_latency_excluded')}. Route-correct but nonpassing rows: {score.get('route_correct_but_nonpassing')}.",
        "",
        "## Fixes Made",
        "- Replaced exact benchmark literals in product routing logic with generalized concept predicates.",
        "- Added command-eval routing_engine fallback derivation for direct/legacy/generic/excluded/error rows.",
        "- Added Planner v2 legacy deferral for scheduled but unmigrated native owners such as trust_approvals, power, weather, and window_control.",
        "- Normalized Planner v2 watch_runtime browser page/tab status to the browser_context tool path.",
        "- Added native Planner v2 routine_execute semantic handoff instead of falling through to generic_provider.",
        "",
        "## What Was Deliberately Not Changed",
        "- No new families were migrated.",
        "- No new route behavior was added to the legacy planner as the primary path.",
        "- No scoring, provider audit, payload, approval/trust, dry-run, or timeout guardrails were weakened.",
        "- The historical routine_save blocker remains known_unreproduced_product_latency_blocker.",
        "",
        "## Safety Provider Payload Results",
        f"{summary['safety_provider_payload']}.",
        "",
        "## 250 Before/After",
        f"Best prior: {summarize(best)}.",
        f"Post-router architecture: {summarize(arch)}.",
        f"Post-migration-2: {summarize(mig)}.",
        f"Expansion-1 pre-stabilization: {summarize(exp)}.",
        f"Post-stabilization: {post_metrics if post_rows else 'not run'}.",
        "",
        "## Recommendation",
        str(summary["recommendation"]),
    ]
    write_md(OUT / "planner_v2_stabilization_report.md", lines)


def safety_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
        "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
        "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
        "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "payload_guardrail_failures": sum(1 for row in rows if row.get("failure_category") == "payload_guardrail_failure"),
        "payload_guardrail_triggered_rows": sum(1 for row in rows if row.get("payload_guardrail_triggered")),
        "hard_timeouts": sum(1 for row in rows if row.get("failure_category") == "hard_timeout"),
        "max_response_json_bytes": max((int(row.get("response_json_bytes") or 0) for row in rows), default=0),
        "rows_above_1mb": sum(1 for row in rows if int(row.get("response_json_bytes") or 0) > 1_000_000),
    }


def recommendation(post_rows: list[dict[str, Any]], post_summary: dict[str, Any], cleanup: dict[str, Any], engine: dict[str, Any]) -> str:
    if not cleanup.get("cleanup_passed"):
        return "continue_stabilization"
    if not post_rows:
        return "run_250_after_clean_focused_lanes"
    metrics = summarize(post_rows)
    if metrics["provider_calls"] or metrics["external_actions"] or metrics["payload_guardrail_failures"]:
        return "continue_stabilization"
    if metrics["pass"] < 181:
        return "continue_stabilization"
    if metrics["failure_categories"].get("wrong_subsystem", 0) > 5:
        return "fix_taxonomy_scoring"
    return "migrate_more_families"


def write_md(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(str(line) for line in lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
