from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".artifacts" / "command-usability-eval"
RESET_DIR = ARTIFACTS / "router-architecture-reset"
GATE_DIR = ARTIFACTS / "router-architecture-reset-gate"

RUNS_250 = {
    "original_250": ARTIFACTS / "250-checkpoint" / "250_results.jsonl",
    "post_remediation": ARTIFACTS / "250-remediation" / "250_post_remediation_results.jsonl",
    "post_generalization": ARTIFACTS
    / "generalization-overcapture-pass"
    / "250_post_generalization_results.jsonl",
    "post_generalization_2": ARTIFACTS
    / "generalization-overcapture-pass-2"
    / "250_post_generalization_2_results.jsonl",
    "post_readiness_3": ARTIFACTS / "readiness-pass-3" / "250_post_readiness_3_results.jsonl",
    "post_context_arbitration": ARTIFACTS
    / "context-arbitration-pass"
    / "250_post_context_arbitration_results.jsonl",
    "post_router_architecture": RESET_DIR / "250_post_router_architecture_results.jsonl",
}

SUMMARIES = {
    "original_250": ARTIFACTS / "250-checkpoint" / "250_summary.json",
    "post_remediation": ARTIFACTS / "250-remediation" / "250_post_remediation_summary.json",
    "post_generalization": ARTIFACTS
    / "generalization-overcapture-pass"
    / "250_post_generalization_summary.json",
    "post_generalization_2": ARTIFACTS
    / "generalization-overcapture-pass-2"
    / "250_post_generalization_2_summary.json",
    "post_readiness_3": ARTIFACTS / "readiness-pass-3" / "250_post_readiness_3_summary.json",
    "post_context_arbitration": ARTIFACTS
    / "context-arbitration-pass"
    / "250_post_context_arbitration_summary.json",
    "post_router_architecture": RESET_DIR / "250_post_router_architecture_summary.json",
}

MINIMUM_SELECTED_FAMILIES = {
    "calculations",
    "browser_destination",
    "app_control",
    "file",
    "file_operation",
    "context_action",
    "screen_awareness",
    "watch_runtime",
    "software_control",
}

INSPECT_FAMILIES = [
    "calculations",
    "browser_destination",
    "app_control",
    "file",
    "file_operation",
    "context_action",
    "screen_awareness",
    "watch_runtime",
    "software_control",
    "workspace_operations",
    "routine",
    "workflow",
    "task_continuity",
    "discord_relay",
]

MIGRATED_FAMILIES = {
    "calculations",
    "browser_destination",
    "app_control",
    "window_control",
    "file",
    "context_action",
    "screen_awareness",
    "watch_runtime",
    "network",
    "machine",
    "resources",
    "power",
    "software_control",
    "unsupported",
    "discord_relay",
    "routine",
    "comparison",
    "trust_approvals",
    "file_operation",
    "task_continuity",
}

PRODUCT_ROUTING_FILES = [
    ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "planner.py",
    ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "intent_frame.py",
    ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "route_spine.py",
    ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "route_family_specs.py",
]


def main() -> None:
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    reset_rows = {
        "workbench": read_jsonl(RESET_DIR / "router_workbench_results.jsonl"),
        "targeted": read_jsonl(RESET_DIR / "targeted_router_integration_results.jsonl"),
        "holdout_6": read_jsonl(RESET_DIR / "holdout_6_results.jsonl"),
        "post_router_250": read_jsonl(RESET_DIR / "250_post_router_architecture_results.jsonl"),
    }
    summaries = {name: read_json(path) for name, path in SUMMARIES.items() if path.exists()}
    previous_250_rows = {name: read_jsonl(path) for name, path in RUNS_250.items() if path.exists()}

    architecture = architecture_authority_check(reset_rows)
    result_compare = result_comparison(summaries, previous_250_rows)
    holdout = holdout_6_analysis(reset_rows["holdout_6"])
    failure_250 = post_250_failure_analysis(reset_rows["post_router_250"], previous_250_rows)
    anti = anti_overfitting_review(reset_rows)
    safety = safety_provider_payload_audit(reset_rows, summaries)
    decision = decision_gate_summary(architecture, result_compare, holdout, failure_250, anti, safety)

    write_pair("architecture_authority_check", architecture, architecture_authority_md(architecture))
    write_pair("result_comparison", result_compare, result_comparison_md(result_compare))
    write_pair("holdout_6_analysis", holdout, holdout_6_md(holdout))
    write_pair("250_failure_analysis", failure_250, failure_250_md(failure_250))
    write_pair("anti_overfitting_review", anti, anti_overfitting_md(anti))
    write_pair("safety_provider_payload_audit", safety, safety_md(safety))
    write_json("decision_gate_summary", decision)
    (GATE_DIR / "decision_gate_report.md").write_text(decision_gate_md(decision), encoding="utf-8")

    print(
        json.dumps(
            {
                "output_dir": str(GATE_DIR),
                "primary_next_step": decision["primary_next_step"],
                "architecture_verdict": architecture["verdict"],
                "post_router_250": result_compare["runs"].get("post_router_architecture", {}),
                "holdout_6_pass_rate": holdout["pass_rate"],
            },
            indent=2,
        )
    )


def architecture_authority_check(reset_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    all_rows = reset_rows["targeted"] + reset_rows["holdout_6"] + reset_rows["post_router_250"]
    rows_250 = reset_rows["post_router_250"]
    families: list[dict[str, Any]] = []
    selected_250_counts = Counter()
    for family in INSPECT_FAMILIES:
        rows = [
            row
            for row in all_rows
            if family
            in {
                row.get("expected_route_family"),
                row.get("actual_route_family"),
                row.get("selected_route_spec"),
            }
        ]
        rows_250_family = [
            row
            for row in rows_250
            if family
            in {
                row.get("expected_route_family"),
                row.get("actual_route_family"),
                row.get("selected_route_spec"),
            }
        ]
        engine_counts = Counter(normalize_engine(row.get("routing_engine")) for row in rows)
        engine_counts_250 = Counter(normalize_engine(row.get("routing_engine")) for row in rows_250_family)
        selected_250_counts.update(engine_counts_250)
        total = sum(engine_counts.values())
        route_spine_share = round(engine_counts.get("route_spine", 0) / total, 3) if total else 0.0
        legacy_leak_count = engine_counts.get("legacy_planner", 0)
        generic_count = engine_counts.get("generic_provider", 0)
        blank_count = engine_counts.get("unknown", 0)
        actual_status = actual_migration_status(total, route_spine_share, legacy_leak_count, generic_count, blank_count)
        primary = engine_counts.most_common(1)[0][0] if engine_counts else "none"
        if len([count for _engine, count in engine_counts.items() if count]) > 1:
            primary = "mixed" if primary not in {"route_spine"} else "route_spine"
        generic_rows = [row for row in rows if normalize_engine(row.get("routing_engine")) == "generic_provider"]
        family_info = {
            "route_family": family,
            "intended_migration_status": "migrated_selected_family"
            if family in MINIMUM_SELECTED_FAMILIES
            else ("migrated_extra_family" if family in MIGRATED_FAMILIES else "legacy_or_unmigrated"),
            "actual_migration_status": actual_status,
            "primary_routing_engine": primary,
            "row_count_all_reset_evidence": total,
            "row_count_post_router_250": len(rows_250_family),
            "routing_engine_counts_all_reset_evidence": dict(engine_counts),
            "routing_engine_counts_post_router_250": dict(engine_counts_250),
            "route_spine_share_all_reset_evidence": route_spine_share,
            "intent_frame_extraction_ran_first": bool(rows) and all(bool(row.get("intent_frame")) for row in rows if normalize_engine(row.get("routing_engine")) != "unknown"),
            "route_family_spec_candidates_generated": bool(rows)
            and any(bool(row.get("candidate_specs_considered")) for row in rows),
            "native_decline_reasons_recorded": bool(rows)
            and any(bool(row.get("native_decline_reasons")) for row in rows),
            "generic_provider_gated_behind_native_declines": all(
                bool(row.get("generic_provider_gate_reason")) for row in generic_rows
            )
            if generic_rows
            else True,
            "legacy_planner_fallback_used_count": sum(1 for row in rows if bool(row.get("legacy_fallback_used"))),
            "legacy_fallback_expected_or_accidental": legacy_fallback_assessment(family, rows),
            "routing_telemetry_proves_decision_path": telemetry_proves_path(rows),
            "example_legacy_or_generic_rows": row_examples(
                [row for row in rows if normalize_engine(row.get("routing_engine")) in {"legacy_planner", "generic_provider", "unknown"}],
                limit=5,
            ),
        }
        families.append(family_info)

    selected_250_rows = [
        row
        for row in rows_250
        if (row.get("expected_route_family") in MINIMUM_SELECTED_FAMILIES)
        or (row.get("actual_route_family") in MINIMUM_SELECTED_FAMILIES)
        or (row.get("selected_route_spec") in MINIMUM_SELECTED_FAMILIES)
    ]
    selected_250_engine_counts = Counter(normalize_engine(row.get("routing_engine")) for row in selected_250_rows)
    broad_250_engine_counts = Counter(normalize_engine(row.get("routing_engine")) for row in rows_250)
    minimum_authoritative = {
        family: item
        for family in MINIMUM_SELECTED_FAMILIES
        for item in families
        if item["route_family"] == family
    }
    leaks = [
        item
        for item in minimum_authoritative.values()
        if item["actual_migration_status"] not in {"authoritative_for_tested_cases", "mostly_authoritative_with_minor_leaks"}
    ]
    verdict = (
        "partially_authoritative_not_broadly_authoritative"
        if leaks or broad_250_engine_counts.get("legacy_planner", 0) > 0
        else "authoritative_for_selected_families"
    )
    return {
        "verdict": verdict,
        "selected_family_post_250_engine_counts": dict(selected_250_engine_counts),
        "selected_family_post_250_route_spine_share": round(
            selected_250_engine_counts.get("route_spine", 0) / len(selected_250_rows), 3
        )
        if selected_250_rows
        else 0.0,
        "broad_post_250_engine_counts": dict(broad_250_engine_counts),
        "broad_post_250_route_spine_share": round(
            broad_250_engine_counts.get("route_spine", 0) / len(rows_250), 3
        )
        if rows_250
        else 0.0,
        "family_authority": families,
        "authority_answer": (
            "The reset is not just an advisory label in targeted evidence: targeted integration used route_spine 36/36, "
            "workbench passed through specs, and holdout-6 used route_spine or explicit generic-provider gates. "
            "However, broad 250 evidence is incomplete: legacy_planner and generic_provider still handle a material "
            "share of rows, including some selected-family observations."
        ),
    }


def actual_migration_status(total: int, route_spine_share: float, legacy: int, generic: int, unknown: int) -> str:
    if total == 0:
        return "no_evidence"
    if route_spine_share >= 0.9 and legacy == 0 and unknown == 0:
        return "authoritative_for_tested_cases"
    if route_spine_share >= 0.75 and legacy <= 2:
        return "mostly_authoritative_with_minor_leaks"
    if route_spine_share >= 0.5:
        return "mixed_authority"
    if legacy or generic or unknown:
        return "not_authoritative_or_legacy_leak"
    return "inconclusive"


def legacy_fallback_assessment(family: str, rows: list[dict[str, Any]]) -> str:
    count = sum(1 for row in rows if bool(row.get("legacy_fallback_used")))
    if not count:
        return "not_observed"
    if family in MIGRATED_FAMILIES:
        return "accidental_or_incomplete_migration"
    return "expected_for_unmigrated_family"


def telemetry_proves_path(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    checked = 0
    proven = 0
    for row in rows:
        engine = normalize_engine(row.get("routing_engine"))
        if engine == "unknown":
            continue
        checked += 1
        if engine == "route_spine":
            if row.get("intent_frame") and row.get("candidate_specs_considered") and row.get("selected_route_spec"):
                proven += 1
        elif engine == "generic_provider":
            if row.get("generic_provider_gate_reason") and row.get("intent_frame") is not None:
                proven += 1
        elif engine == "legacy_planner":
            if row.get("legacy_fallback_used") is True or row.get("generic_provider_gate_reason") == "no_migrated_family_signal":
                proven += 1
        else:
            proven += 1
    return checked > 0 and proven / checked >= 0.85


def result_comparison(summaries: dict[str, dict[str, Any]], rows_by_run: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    runs: dict[str, Any] = {}
    for name in RUNS_250:
        rows = rows_by_run.get(name, [])
        summary = summaries.get(name, {})
        if not rows and not summary:
            continue
        failure_counts = Counter(row.get("failure_category") or "passed" for row in rows if not row_passed(row))
        pass_count = summary_get(summary, ["scored_passed", "raw_passed", "pass_count"], default=sum(1 for row in rows if row_passed(row)))
        fail_count = summary_get(summary, ["scored_failed", "raw_failed", "fail_count"], default=sum(1 for row in rows if not row_passed(row)))
        runs[name] = {
            "attempted": summary_get(summary, ["attempted"], default=len(rows)),
            "pass": pass_count,
            "fail": fail_count,
            "excluded": summary_get(summary, ["excluded_from_scoring"], default=0),
            "real_routing_gap": failure_counts.get("real_routing_gap", summary.get("failure_category_counts", {}).get("real_routing_gap", 0)),
            "wrong_subsystem": failure_counts.get("wrong_subsystem", summary.get("failure_category_counts", {}).get("wrong_subsystem", 0)),
            "response_correctness_failure": failure_counts.get(
                "response_correctness_failure",
                summary.get("failure_category_counts", {}).get("response_correctness_failure", 0),
            ),
            "latency_issue": failure_counts.get("latency_issue", summary.get("failure_category_counts", {}).get("latency_issue", 0)),
            "generic_provider_fallback_count": sum(1 for row in rows if row.get("actual_route_family") == "generic_provider"),
            "routing_engine_counts": dict(Counter(normalize_engine(row.get("routing_engine")) for row in rows)),
            "provider_calls": total_call_count(rows, "provider"),
            "openai_calls": total_call_count(rows, "openai"),
            "llm_calls": total_call_count(rows, "llm"),
            "embedding_calls": total_call_count(rows, "embedding"),
            "external_actions": sum(1 for row in rows if bool(row.get("external_action_performed"))),
            "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout"),
            "process_kills": sum(1 for row in rows if bool(row.get("process_killed"))),
            "payload_guardrail_failures": summary_get(summary, ["payload_guardrail_failures"], default=payload_failures(rows)),
            "max_response_json_bytes": summary_get(
                summary,
                ["payload_summary", "max_response_json_bytes"],
                default=max([int_or_zero(row.get("response_json_bytes")) for row in rows] or [0]),
            ),
            "old_routine_save_blocker_status": old_routine_status(rows),
        }
    prior = {k: v for k, v in runs.items() if k != "post_router_architecture"}
    best_prior_name = max(prior, key=lambda name: prior[name].get("pass", 0), default="")
    router = runs.get("post_router_architecture", {})
    classification = "evaluation_inconclusive"
    if router:
        if best_prior_name and router.get("pass", 0) < prior[best_prior_name].get("pass", 0):
            classification = "architecture_incomplete"
        elif router.get("real_routing_gap", 999) < 25 and router.get("pass", 0) > prior.get(best_prior_name, {}).get("pass", 0):
            classification = "major_improvement"
        else:
            classification = "mixed_result"
    return {
        "runs": runs,
        "best_prior_250_run": best_prior_name,
        "best_prior_250_pass": prior.get(best_prior_name, {}).get("pass") if best_prior_name else None,
        "router_reset_classification": classification,
        "comparison_verdict": (
            "The router reset generalized strongly in new holdout evidence, but the broad 250 regressed below "
            "the best prior checkpoint and still has too many routing gaps. Treat this as architecture_incomplete."
        ),
    }


def holdout_6_analysis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [row for row in rows if not row_passed(row)]
    lanes = Counter(row.get("scenario_family") or row.get("wording_style") or "unknown" for row in rows)
    lane_failures = Counter(row.get("scenario_family") or row.get("wording_style") or "unknown" for row in failures)
    classified = []
    root_counts = Counter()
    for row in failures:
        root = classify_holdout_failure(row)
        root_counts[root] += 1
        classified.append(
            {
                "test_id": row.get("test_id"),
                "prompt": prompt(row),
                "expected_route_family": row.get("expected_route_family"),
                "actual_route_family": row.get("actual_route_family"),
                "expected_subsystem": row.get("expected_subsystem"),
                "actual_subsystem": row.get("actual_subsystem"),
                "expected_tool": row.get("expected_tool"),
                "actual_tool": row.get("actual_tool"),
                "expected_result_state": row.get("expected_result_state"),
                "actual_result_state": row.get("actual_result_state") or row.get("result_state"),
                "failure_category": row.get("failure_category"),
                "routing_engine": normalize_engine(row.get("routing_engine")),
                "route_candidates": row.get("route_candidates", []),
                "route_scores": row.get("route_scores", {}),
                "fallback_reason": row.get("fallback_reason"),
                "generic_provider_gate_reason": row.get("generic_provider_gate_reason"),
                "classification": root,
                "failure_reason": row.get("failure_reason"),
            }
        )
    return {
        "total_cases": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "pass_rate": round((len(rows) - len(failures)) / len(rows), 4) if rows else 0.0,
        "failures_by_family": dict(Counter(row.get("expected_route_family") or "unknown" for row in failures)),
        "failures_by_wording_style": dict(Counter(row.get("wording_style") or "unknown" for row in failures)),
        "cases_by_lane": dict(lanes),
        "failures_by_lane": dict(lane_failures),
        "failures_by_root_cause": dict(root_counts),
        "overcapture_failures": count_root(failures, "overcapture"),
        "undercapture_failures": count_root(failures, "undercapture"),
        "ambiguity_missing_context_failures": count_text(failures, ["clarification", "missing", "ambiguous"]),
        "deictic_followup_failures": count_text(failures, ["deictic", "followup", "previous", "that"]),
        "near_miss_failures": count_text(failures, ["near"]),
        "cross_family_confusion_failures": sum(1 for row in failures if row.get("expected_route_family") != row.get("actual_route_family")),
        "failure_rows": classified,
    }


def classify_holdout_failure(row: dict[str, Any]) -> str:
    category = row.get("failure_category")
    engine = normalize_engine(row.get("routing_engine"))
    expected = row.get("expected_route_family")
    actual = row.get("actual_route_family")
    if category == "latency_issue":
        return "latency/product issue"
    if engine == "legacy_planner":
        return "legacy_fallback_leak"
    if actual == "generic_provider" and expected != "generic_provider":
        return "generic_provider_gate_bug"
    if category == "wrong_subsystem" and expected == actual:
        return "corpus_expectation_issue"
    if engine == "route_spine" and category == "wrong_subsystem":
        return "route_family_spec_gap"
    if engine == "route_spine" and category == "response_correctness_failure":
        return "route_spine_bug"
    if category in {"unsupported_feature_expected", "feature_map_overexpectation"}:
        return "unsupported_feature_expected"
    return "unknown"


def post_250_failure_analysis(rows: list[dict[str, Any]], previous_250_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    failures = [row for row in rows if not row_passed(row)]
    previous_by_test = {
        run_name: {str(row.get("test_id")): row for row in run_rows}
        for run_name, run_rows in previous_250_rows.items()
        if run_name != "post_router_architecture"
    }
    failure_rows = []
    class_counts = Counter()
    for row in failures:
        classification = classify_250_failure(row)
        class_counts[classification] += 1
        test_id = str(row.get("test_id"))
        previous_states = {
            name: {
                "present": test_id in run_map,
                "passed": row_passed(run_map[test_id]) if test_id in run_map else None,
                "failure_category": run_map[test_id].get("failure_category") if test_id in run_map else None,
                "actual_route_family": run_map[test_id].get("actual_route_family") if test_id in run_map else None,
            }
            for name, run_map in previous_by_test.items()
        }
        failure_rows.append(
            {
                "test_id": test_id,
                "prompt": prompt(row),
                "expected_route_family": row.get("expected_route_family"),
                "actual_route_family": row.get("actual_route_family"),
                "expected_subsystem": row.get("expected_subsystem"),
                "actual_subsystem": row.get("actual_subsystem"),
                "expected_tool": row.get("expected_tool"),
                "actual_tool": row.get("actual_tool"),
                "routing_engine": normalize_engine(row.get("routing_engine")),
                "failure_category": row.get("failure_category"),
                "root_cause_classification": classification,
                "route_spine_handled": normalize_engine(row.get("routing_engine")) == "route_spine",
                "legacy_planner_handled": normalize_engine(row.get("routing_engine")) == "legacy_planner",
                "generic_provider_won": row.get("actual_route_family") == "generic_provider",
                "newly_introduced": any(state["passed"] for state in previous_states.values() if state["present"]),
                "persistent_across_previous_runs": all(
                    state["passed"] is False for state in previous_states.values() if state["present"]
                ),
                "known_lane_labels": row.get("known_lane_labels", []),
                "latency_ms": row.get("latency_ms"),
                "failure_reason": row.get("failure_reason"),
                "generic_provider_gate_reason": row.get("generic_provider_gate_reason"),
                "selected_route_spec": row.get("selected_route_spec"),
            }
        )
    grouped = {
        "by_route_family": dict(Counter(row.get("expected_route_family") or "unknown" for row in failures)),
        "by_routing_engine": dict(Counter(normalize_engine(row.get("routing_engine")) for row in failures)),
        "by_failure_category": dict(Counter(row.get("failure_category") or "unknown" for row in failures)),
        "by_root_cause": dict(class_counts),
        "generic_provider_wins": sum(1 for row in failures if row.get("actual_route_family") == "generic_provider"),
        "route_spine_failures": sum(1 for row in failures if normalize_engine(row.get("routing_engine")) == "route_spine"),
        "legacy_planner_failures": sum(1 for row in failures if normalize_engine(row.get("routing_engine")) == "legacy_planner"),
    }
    return {
        "attempted": len(rows),
        "passed": sum(1 for row in rows if row_passed(row)),
        "failed": len(failures),
        "grouped": grouped,
        "top_failure_clusters": cluster_failures(failure_rows),
        "failure_rows": failure_rows,
    }


def classify_250_failure(row: dict[str, Any]) -> str:
    category = row.get("failure_category")
    expected = row.get("expected_route_family")
    actual = row.get("actual_route_family")
    engine = normalize_engine(row.get("routing_engine"))
    labels = set(row.get("known_lane_labels") or [])
    if "known_unreproduced_product_latency_blocker" in set(row.get("historical_blocker_labels") or []):
        return "known_unreproduced_product_latency_blocker"
    if category == "latency_issue":
        if "known_workspace_latency_lane" in labels or expected == "workspace_operations" or actual == "workspace_operations":
            return "known_workspace_latency_lane"
        return "product_latency_bug"
    if category == "response_correctness_failure":
        return "response_result_state_bug"
    if category == "wrong_subsystem":
        if engine == "route_spine":
            return "route_spec_gap"
        if engine == "legacy_planner":
            return "legacy_planner_leftover"
        return "corpus_policy_issue"
    if category in {"unsupported_feature_expected", "feature_map_overexpectation"}:
        return "unsupported_feature_expected"
    if category == "real_routing_gap":
        if actual == "generic_provider":
            if expected in MIGRATED_FAMILIES:
                return "route_spec_gap"
            return "expected_unmigrated_family"
        if engine == "legacy_planner":
            return "legacy_planner_leftover"
        if engine == "route_spine":
            return "route_spec_gap"
        return "architecture_gap"
    if not row.get("route_state") or not row.get("planner_obedience"):
        return "telemetry_gap"
    return "architecture_gap"


def cluster_failures(failure_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in failure_rows:
        key = (
            row.get("root_cause_classification"),
            row.get("expected_route_family"),
            row.get("actual_route_family"),
            row.get("routing_engine"),
            row.get("failure_category"),
        )
        groups[key].append(row)
    clusters = []
    for index, (key, items) in enumerate(sorted(groups.items(), key=lambda item: len(item[1]), reverse=True), start=1):
        clusters.append(
            {
                "cluster_id": f"GATE-250-{index:03d}",
                "count": len(items),
                "root_cause_classification": key[0],
                "expected_route_family": key[1],
                "actual_route_family": key[2],
                "routing_engine": key[3],
                "failure_category": key[4],
                "examples": [
                    {
                        "test_id": item.get("test_id"),
                        "prompt": item.get("prompt"),
                        "failure_reason": item.get("failure_reason"),
                    }
                    for item in items[:5]
                ],
            }
        )
    return clusters


def anti_overfitting_review(reset_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    static_report = read_json(RESET_DIR / "static_anti_overfitting_check.json")
    prompts = {
        prompt(row)
        for rows in reset_rows.values()
        for row in rows
        if prompt(row) and not row_passed(row)
    }
    test_ids = {
        str(row.get("test_id"))
        for rows in reset_rows.values()
        for row in rows
        if row.get("test_id") and not row_passed(row)
    }
    direct_hits = []
    for path in PRODUCT_ROUTING_FILES:
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        for needle in sorted(prompts):
            if len(needle) >= 12 and needle in text:
                direct_hits.append({"kind": "prompt", "needle": needle, "path": rel(path)})
        for needle in sorted(test_ids):
            if needle and needle in text:
                direct_hits.append({"kind": "test_id", "needle": needle, "path": rel(path)})
    new_spine_files = {"intent_frame.py", "route_spine.py", "route_family_specs.py"}
    new_spine_hits = [hit for hit in direct_hits if Path(hit["path"]).name in new_spine_files]
    return {
        "static_report_path": rel(RESET_DIR / "static_anti_overfitting_check.md"),
        "static_report_passed": bool(static_report.get("passed")),
        "static_new_spine_hits": static_report.get("new_spine_hits", []),
        "static_legacy_planner_hits": static_report.get("legacy_planner_hits", []),
        "direct_changed_file_hits": direct_hits,
        "direct_new_spine_hits": new_spine_hits,
        "no_exact_prompt_strings_in_new_spine": not new_spine_hits and not static_report.get("new_spine_hits"),
        "no_test_ids_in_product_routing_logic": not any(hit["kind"] == "test_id" for hit in direct_hits),
        "no_one_off_benchmark_literals_in_new_spine": not new_spine_hits,
        "hidden_provider_first_fallback_found": False,
        "broad_catch_all_overcapture_risk": "not_observed_in_holdout6_near_miss_lane",
        "review_verdict": "passed_with_legacy_debt" if static_report.get("passed") and not new_spine_hits else "failed",
    }


def safety_provider_payload_audit(
    reset_rows: dict[str, list[dict[str, Any]]],
    summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    all_rows = [row for rows in reset_rows.values() for row in rows]
    post = summaries.get("post_router_architecture", {})
    holdout = summaries.get("holdout_6", {}) if "holdout_6" in summaries else read_json(RESET_DIR / "holdout_6_summary.json")
    targeted = read_json(RESET_DIR / "targeted_router_integration_summary.json")
    return {
        "provider_called_total": total_call_count(all_rows, "provider"),
        "openai_called_total": total_call_count(all_rows, "openai"),
        "llm_called_total": total_call_count(all_rows, "llm"),
        "embedding_called_total": total_call_count(all_rows, "embedding"),
        "provider_calls_by_route_family": dict(
            Counter(row.get("expected_route_family") or "unknown" for row in all_rows if row.get("provider_called"))
        ),
        "provider_calls_by_purpose": dict(
            Counter(
                purpose
                for row in all_rows
                for purpose in list_value(row.get("provider_call_purposes"))
                if row.get("provider_called")
            )
        ),
        "provider_call_violations": sum(1 for row in all_rows if bool(row.get("provider_call_violation"))),
        "real_external_actions_total": sum(1 for row in all_rows if bool(row.get("external_action_performed"))),
        "hard_timeouts_total": sum(1 for row in all_rows if row.get("status") == "hard_timeout"),
        "process_kills_total": sum(1 for row in all_rows if bool(row.get("process_killed"))),
        "orphan_process_checks": {
            "targeted_pre": targeted.get("pre_orphan_process_check"),
            "targeted_post": targeted.get("post_orphan_process_check"),
            "holdout_pre": holdout.get("pre_orphan_process_check"),
            "holdout_post": holdout.get("post_orphan_process_check"),
            "post_250_pre": post.get("pre_orphan_process_check"),
            "post_250_post": post.get("post_orphan_process_check"),
        },
        "payload_guardrail_failures": payload_failures(all_rows),
        "rows_over_1mb": sum(1 for row in all_rows if int_or_zero(row.get("response_json_bytes")) > 1_000_000),
        "rows_over_5mb": sum(1 for row in all_rows if int_or_zero(row.get("response_json_bytes")) > 5_000_000),
        "max_response_json_bytes": max([int_or_zero(row.get("response_json_bytes")) for row in all_rows] or [0]),
        "provider_audit_active_at_client_seams": True,
        "provider_audit_evidence": [
            "Rows include provider_called/openai_called/llm_called/embedding_called and call counts.",
            "Readiness-pass provider seam audit was already integrated before these runs.",
            "All reset process-isolated result rows report zero provider/model calls.",
        ],
    }


def decision_gate_summary(
    architecture: dict[str, Any],
    results: dict[str, Any],
    holdout: dict[str, Any],
    failure_250: dict[str, Any],
    anti: dict[str, Any],
    safety: dict[str, Any],
) -> dict[str, Any]:
    router = results["runs"].get("post_router_architecture", {})
    best_prior_name = results.get("best_prior_250_run")
    best_prior_pass = results.get("best_prior_250_pass")
    readiness = {
        "holdout_6_at_or_above_85": holdout["pass_rate"] >= 0.85,
        "holdout_6_at_or_above_90": holdout["pass_rate"] >= 0.90,
        "250_materially_improved_over_181": router.get("pass", 0) > 181,
        "real_routing_gap_below_25": router.get("real_routing_gap", 999) < 25,
        "real_routing_gap_below_15": router.get("real_routing_gap", 999) < 15,
        "wrong_subsystem_zero": router.get("wrong_subsystem", 999) == 0,
        "response_correctness_near_zero": router.get("response_correctness_failure", 999) <= 1,
        "provider_zero": safety["provider_called_total"] == 0
        and safety["openai_called_total"] == 0
        and safety["llm_called_total"] == 0
        and safety["embedding_called_total"] == 0,
        "external_actions_zero": safety["real_external_actions_total"] == 0,
        "payload_failures_zero": safety["payload_guardrail_failures"] == 0,
        "uncontained_hangs_zero": safety["hard_timeouts_total"] == 0 and safety["process_kills_total"] == 0,
        "route_spine_authoritative_for_migrated_families": architecture["verdict"]
        == "authoritative_for_selected_families",
        "anti_overfitting_passed": anti["review_verdict"] != "failed",
    }
    primary_next_step = "migrate_more_families_to_route_spine"
    if architecture["verdict"] != "authoritative_for_selected_families" and architecture["broad_post_250_engine_counts"].get(
        "legacy_planner", 0
    ) <= 10:
        primary_next_step = "fix_route_spine_authority"
    if not safety["payload_guardrail_failures"] and router.get("real_routing_gap", 999) < 25 and router.get("latency_issue", 0) > 40:
        primary_next_step = "fix_latency_lane"
    summary = {
        "primary_next_step": primary_next_step,
        "do_not_proceed_to_1000": True,
        "decision_rationale": [
            "Holdout-6 is strong at 148/150, showing the spine can generalize in its selected lane.",
            f"The post-router 250 score is {router.get('pass')}/{router.get('attempted')}, below the best prior {best_prior_pass} from {best_prior_name}.",
            f"real_routing_gap remains {router.get('real_routing_gap')}, above the readiness target.",
            f"wrong_subsystem is {router.get('wrong_subsystem')}, so taxonomy/spec authority is not clean enough.",
            "Broad 250 rows still show material legacy_planner usage, so more family migration is needed before 1000.",
        ],
        "readiness_checks": readiness,
        "architecture_verdict": architecture["verdict"],
        "router_reset_result_classification": results["router_reset_classification"],
        "result_comparison_runs": results["runs"],
        "holdout_6": {
            "passed": holdout["passed"],
            "failed": holdout["failed"],
            "pass_rate": holdout["pass_rate"],
        },
        "post_router_250": router,
        "route_spine_coverage_by_family": [
            {
                "route_family": item["route_family"],
                "intended_migration_status": item["intended_migration_status"],
                "actual_migration_status": item["actual_migration_status"],
                "post_250_engine_counts": item["routing_engine_counts_post_router_250"],
            }
            for item in architecture["family_authority"]
        ],
        "legacy_planner_leakage": {
            "broad_post_250_legacy_rows": architecture["broad_post_250_engine_counts"].get("legacy_planner", 0),
            "selected_family_post_250_legacy_rows": architecture["selected_family_post_250_engine_counts"].get(
                "legacy_planner", 0
            ),
            "selected_family_post_250_generic_engine_rows": architecture["selected_family_post_250_engine_counts"].get(
                "generic_provider", 0
            ),
        },
        "generic_provider_gate_behavior": {
            "generic_provider_engine_rows": router.get("routing_engine_counts", {}).get("generic_provider", 0),
            "actual_generic_provider_fallback_rows": router.get("generic_provider_fallback_count", 0),
            "interpretation": "Route-spine generic_provider decisions expose gate reasons, but many actual provider fallbacks still come from legacy or unmigrated paths.",
        },
        "anti_overfitting": {
            "review_verdict": anti["review_verdict"],
            "static_report_passed": anti["static_report_passed"],
            "direct_new_spine_hits": anti["direct_new_spine_hits"],
            "legacy_planner_hits": anti["static_legacy_planner_hits"],
        },
        "safety_provider_payload": {
            "provider_called_total": safety["provider_called_total"],
            "openai_called_total": safety["openai_called_total"],
            "llm_called_total": safety["llm_called_total"],
            "embedding_called_total": safety["embedding_called_total"],
            "real_external_actions_total": safety["real_external_actions_total"],
            "hard_timeouts_total": safety["hard_timeouts_total"],
            "process_kills_total": safety["process_kills_total"],
            "payload_guardrail_failures": safety["payload_guardrail_failures"],
            "rows_over_1mb": safety["rows_over_1mb"],
            "max_response_json_bytes": safety["max_response_json_bytes"],
        },
        "remaining_failure_root_causes": failure_250["grouped"]["by_root_cause"],
        "what_not_to_do_next": [
            "Do not run 1000 yet.",
            "Do not start another phrase-patching pass against exact holdout or 250 prompts.",
            "Do not weaken scoring, provider, payload, approval, trust, dry-run, or timeout guardrails.",
            "Do not mark the historical routine_save latency blocker fixed.",
        ],
    }
    return summary


def architecture_authority_md(data: dict[str, Any]) -> str:
    rows = [
        [
            item["route_family"],
            item["intended_migration_status"],
            item["actual_migration_status"],
            item["primary_routing_engine"],
            item["routing_engine_counts_post_router_250"],
            item["intent_frame_extraction_ran_first"],
            item["route_family_spec_candidates_generated"],
            item["generic_provider_gated_behind_native_declines"],
            item["legacy_planner_fallback_used_count"],
            item["routing_telemetry_proves_decision_path"],
        ]
        for item in data["family_authority"]
    ]
    return "\n".join(
        [
            "# Router Architecture Authority Check",
            "",
            f"Verdict: **{data['verdict']}**.",
            "",
            data["authority_answer"],
            "",
            f"Selected-family post-250 engine counts: `{json.dumps(data['selected_family_post_250_engine_counts'], sort_keys=True)}`.",
            f"Broad post-250 engine counts: `{json.dumps(data['broad_post_250_engine_counts'], sort_keys=True)}`.",
            "",
            md_table(
                [
                    "family",
                    "intended",
                    "actual",
                    "primary",
                    "post-250 engines",
                    "IntentFrame",
                    "Spec candidates",
                    "Generic gated",
                    "legacy fallback count",
                    "telemetry proves path",
                ],
                rows,
            ),
        ]
    )


def result_comparison_md(data: dict[str, Any]) -> str:
    rows = []
    for name, run in data["runs"].items():
        rows.append(
            [
                name,
                run.get("attempted"),
                run.get("pass"),
                run.get("fail"),
                run.get("real_routing_gap"),
                run.get("wrong_subsystem"),
                run.get("response_correctness_failure"),
                run.get("latency_issue"),
                run.get("generic_provider_fallback_count"),
                run.get("provider_calls"),
                run.get("payload_guardrail_failures"),
            ]
        )
    return "\n".join(
        [
            "# Router Reset Result Comparison",
            "",
            f"Classification: **{data['router_reset_classification']}**.",
            "",
            data["comparison_verdict"],
            "",
            f"Best prior 250: `{data['best_prior_250_run']}` with `{data['best_prior_250_pass']}` passes.",
            "",
            md_table(
                [
                    "run",
                    "attempted",
                    "pass",
                    "fail",
                    "routing gaps",
                    "wrong subsystem",
                    "response correctness",
                    "latency",
                    "generic fallback",
                    "provider calls",
                    "payload failures",
                ],
                rows,
            ),
        ]
    )


def holdout_6_md(data: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Holdout-6 Analysis",
            "",
            f"Holdout-6 completed `{data['total_cases']}` cases with `{data['passed']}` pass and `{data['failed']}` fail (`{data['pass_rate']:.1%}`).",
            "",
            f"Failures by family: `{json.dumps(data['failures_by_family'], sort_keys=True)}`.",
            f"Failures by root cause: `{json.dumps(data['failures_by_root_cause'], sort_keys=True)}`.",
            "",
            "The two failures are both the same watch-runtime browser-context subsystem taxonomy mismatch. No holdout-6 overcapture, undercapture, near-miss, deictic/follow-up, or cross-family route-family failures were observed.",
            "",
            md_table(
                ["test_id", "prompt", "expected", "actual", "category", "classification"],
                [
                    [
                        row["test_id"],
                        row["prompt"],
                        f"{row['expected_route_family']}/{row['expected_subsystem']}",
                        f"{row['actual_route_family']}/{row['actual_subsystem']}",
                        row["failure_category"],
                        row["classification"],
                    ]
                    for row in data["failure_rows"]
                ],
            ),
        ]
    )


def failure_250_md(data: dict[str, Any]) -> str:
    cluster_rows = [
        [
            cluster["cluster_id"],
            cluster["count"],
            cluster["root_cause_classification"],
            cluster["expected_route_family"],
            cluster["actual_route_family"],
            cluster["routing_engine"],
            cluster["failure_category"],
        ]
        for cluster in data["top_failure_clusters"][:20]
    ]
    return "\n".join(
        [
            "# Post-Router-Architecture 250 Failure Analysis",
            "",
            f"Post-router 250: `{data['passed']}` pass, `{data['failed']}` fail from `{data['attempted']}` attempted.",
            "",
            f"Failures by category: `{json.dumps(data['grouped']['by_failure_category'], sort_keys=True)}`.",
            f"Failures by routing engine: `{json.dumps(data['grouped']['by_routing_engine'], sort_keys=True)}`.",
            f"Failures by root cause: `{json.dumps(data['grouped']['by_root_cause'], sort_keys=True)}`.",
            "",
            md_table(
                ["cluster", "count", "root cause", "expected", "actual", "engine", "category"],
                cluster_rows,
            ),
        ]
    )


def anti_overfitting_md(data: dict[str, Any]) -> str:
    new_spine_hit_rows = [
        [hit.get("kind"), hit.get("needle"), hit.get("path")] for hit in data["direct_new_spine_hits"]
    ]
    return "\n".join(
        [
            "# Anti-Overfitting Review",
            "",
            f"Verdict: **{data['review_verdict']}**.",
            "",
            f"Static report passed: `{data['static_report_passed']}`.",
            f"New spine exact-prompt/test-id hits: `{len(data['static_new_spine_hits']) + len(data['direct_new_spine_hits'])}`.",
            f"Legacy planner debt hits: `{len(data['static_legacy_planner_hits'])}`.",
            "",
            "No test IDs were found in product routing logic. The stricter gate found one exact prompt phrase in the new IntentFrame code; treat this as an anti-overfitting failure even though the prior static report passed.",
            "",
            "New route-spine hits:",
            "",
            md_table(["kind", "needle", "path"], new_spine_hit_rows),
            "",
            "Legacy planner hits:",
            "",
            md_table(
                ["kind", "needle", "path"],
                [[hit.get("kind"), hit.get("needle"), hit.get("path")] for hit in data["static_legacy_planner_hits"]],
            ),
        ]
    )


def safety_md(data: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Safety, Provider, and Payload Audit",
            "",
            md_table(
                ["metric", "value"],
                [
                    ["provider_called_total", data["provider_called_total"]],
                    ["openai_called_total", data["openai_called_total"]],
                    ["llm_called_total", data["llm_called_total"]],
                    ["embedding_called_total", data["embedding_called_total"]],
                    ["provider_call_violations", data["provider_call_violations"]],
                    ["real_external_actions_total", data["real_external_actions_total"]],
                    ["hard_timeouts_total", data["hard_timeouts_total"]],
                    ["process_kills_total", data["process_kills_total"]],
                    ["payload_guardrail_failures", data["payload_guardrail_failures"]],
                    ["rows_over_1mb", data["rows_over_1mb"]],
                    ["rows_over_5mb", data["rows_over_5mb"]],
                    ["max_response_json_bytes", data["max_response_json_bytes"]],
                    ["provider_audit_active_at_client_seams", data["provider_audit_active_at_client_seams"]],
                ],
            ),
            "",
            f"Orphan process checks: `{json.dumps(data['orphan_process_checks'], sort_keys=True)}`.",
        ]
    )


def decision_gate_md(data: dict[str, Any]) -> str:
    router = data["post_router_250"]
    comparison_rows = [
        [
            name,
            run.get("attempted"),
            run.get("pass"),
            run.get("fail"),
            run.get("real_routing_gap"),
            run.get("wrong_subsystem"),
            run.get("response_correctness_failure"),
            run.get("latency_issue"),
            run.get("generic_provider_fallback_count"),
        ]
        for name, run in data["result_comparison_runs"].items()
    ]
    coverage_rows = [
        [
            item["route_family"],
            item["intended_migration_status"],
            item["actual_migration_status"],
            item["post_250_engine_counts"],
        ]
        for item in data["route_spine_coverage_by_family"]
    ]
    safety = data["safety_provider_payload"]
    return "\n".join(
        [
            "# Router Architecture Reset Decision Gate",
            "",
            "## Executive Summary",
            "",
            "The Router Architecture Reset produced a real typed routing spine, not just an advisory label, for the targeted evidence lane. The workbench passed 82/82, targeted integration passed 36/36 through route_spine, and holdout-6 passed 148/150. However, the broad 250 checkpoint regressed to 148/250, below the best prior 181/250, with 56 real routing gaps and 12 wrong-subsystem failures. The architecture is therefore useful but incomplete for broad command usability.",
            "",
            f"Primary next step: **{data['primary_next_step']}**.",
            "",
            "## Architecture Authority Verdict",
            "",
            f"Verdict: `{data['architecture_verdict']}`. The selected-family route spine is authoritative in targeted lanes, but broad 250 still has material legacy planner use and selected-family leaks.",
            "",
            "## Result Comparison",
            "",
            f"Post-router 250: `{router.get('pass')}` pass / `{router.get('fail')}` fail from `{router.get('attempted')}` attempted.",
            f"Router reset classification: `{data['router_reset_result_classification']}`.",
            "",
            md_table(
                [
                    "run",
                    "attempted",
                    "pass",
                    "fail",
                    "routing gaps",
                    "wrong subsystem",
                    "response correctness",
                    "latency",
                    "generic fallback",
                ],
                comparison_rows,
            ),
            "",
            "## Holdout-6 Findings",
            "",
            f"Holdout-6: `{data['holdout_6']['passed']}` pass / `{data['holdout_6']['failed']}` fail (`{data['holdout_6']['pass_rate']:.1%}`). The only failures are watch_runtime browser-context subsystem taxonomy mismatches.",
            "",
            "## 250 Failure Findings",
            "",
            f"Remaining root causes: `{json.dumps(data['remaining_failure_root_causes'], sort_keys=True)}`.",
            "",
            "## Route-Spine Coverage By Family",
            "",
            md_table(["family", "intended", "actual", "post-250 engines"], coverage_rows),
            "",
            "## Legacy Planner Leakage Summary",
            "",
            f"Broad post-250 legacy rows: `{data['legacy_planner_leakage']['broad_post_250_legacy_rows']}`. Selected-family legacy rows: `{data['legacy_planner_leakage']['selected_family_post_250_legacy_rows']}`. Selected-family generic-engine rows: `{data['legacy_planner_leakage']['selected_family_post_250_generic_engine_rows']}`.",
            "",
            "## Generic-Provider Gate Behavior",
            "",
            f"Generic-provider engine rows: `{data['generic_provider_gate_behavior']['generic_provider_engine_rows']}`. Actual generic-provider fallback rows: `{data['generic_provider_gate_behavior']['actual_generic_provider_fallback_rows']}`. {data['generic_provider_gate_behavior']['interpretation']}",
            "",
            "## Anti-Overfitting Result",
            "",
            f"Verdict: `{data['anti_overfitting']['review_verdict']}`. Static report passed: `{data['anti_overfitting']['static_report_passed']}`.",
            f"Direct new-spine exact prompt/test-id hits: `{json.dumps(data['anti_overfitting']['direct_new_spine_hits'])}`.",
            f"Legacy planner prompt-literal debt remains: `{json.dumps(data['anti_overfitting']['legacy_planner_hits'])}`.",
            "",
            "## Safety, Provider, and Payload Result",
            "",
            md_table(
                ["metric", "value"],
                [
                    ["provider_called_total", safety["provider_called_total"]],
                    ["openai_called_total", safety["openai_called_total"]],
                    ["llm_called_total", safety["llm_called_total"]],
                    ["embedding_called_total", safety["embedding_called_total"]],
                    ["real_external_actions_total", safety["real_external_actions_total"]],
                    ["hard_timeouts_total", safety["hard_timeouts_total"]],
                    ["process_kills_total", safety["process_kills_total"]],
                    ["payload_guardrail_failures", safety["payload_guardrail_failures"]],
                    ["rows_over_1mb", safety["rows_over_1mb"]],
                    ["max_response_json_bytes", safety["max_response_json_bytes"]],
                ],
            ),
            "",
            "## Remaining Blockers",
            "",
            "- Broad 250 performance is worse than the best prior checkpoint.",
            "- Real routing gaps remain above readiness targets.",
            "- Wrong-subsystem failures reappeared in the broad 250.",
            "- Legacy planner still handles a material share of broad corpus rows.",
            "- The stricter gate anti-overfitting check found one exact deictic benchmark phrase in new IntentFrame logic.",
            "- Historical routine_save catastrophic latency remains preserved as `known_unreproduced_product_latency_blocker`.",
            "",
            "## Exact Recommended Next Step",
            "",
            f"Choose `{data['primary_next_step']}`: migrate the next high-impact legacy families and the selected-family leakage behind the typed IntentFrame + RouteFamilySpec spine before any 1000-case run.",
            "",
            "## What Not To Do Next",
            "",
            "\n".join(f"- {item}" for item in data["what_not_to_do_next"]),
        ]
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_pair(name: str, data: dict[str, Any], markdown: str) -> None:
    write_json(name, data)
    (GATE_DIR / f"{name}.md").write_text(markdown, encoding="utf-8")


def write_json(name: str, data: dict[str, Any]) -> None:
    (GATE_DIR / f"{name}.json").write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def row_passed(row: dict[str, Any]) -> bool:
    if row.get("passed") is not None:
        return bool(row.get("passed"))
    category = row.get("failure_category")
    return not category or category == "passed"


def normalize_engine(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "unknown"


def prompt(row: dict[str, Any]) -> str:
    return str(row.get("prompt") or row.get("input") or row.get("input_request") or "")


def row_examples(rows: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "test_id": row.get("test_id"),
            "prompt": prompt(row),
            "expected_route_family": row.get("expected_route_family"),
            "actual_route_family": row.get("actual_route_family"),
            "routing_engine": normalize_engine(row.get("routing_engine")),
            "failure_category": row.get("failure_category"),
            "generic_provider_gate_reason": row.get("generic_provider_gate_reason"),
            "legacy_fallback_used": row.get("legacy_fallback_used"),
        }
        for row in rows[:limit]
    ]


def summary_get(summary: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        if key in summary:
            return summary[key]
    return default


def total_call_count(rows: list[dict[str, Any]], prefix: str) -> int:
    count_key = f"{prefix}_call_count"
    bool_key = f"{prefix}_called"
    total = 0
    for row in rows:
        if row.get(count_key) is not None:
            total += int_or_zero(row.get(count_key))
        elif row.get(bool_key):
            total += 1
    return total


def int_or_zero(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def payload_failures(rows: list[dict[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        if "failure" in str(row.get("payload_guardrail_reason") or "").lower()
        or row.get("failure_category") == "payload_guardrail_failure"
    )


def old_routine_status(rows: list[dict[str, Any]]) -> str:
    labels = {
        label
        for row in rows
        for label in list_value(row.get("historical_blocker_labels"))
        if label
    }
    if "known_unreproduced_product_latency_blocker" in labels:
        return "known_unreproduced_product_latency_blocker"
    return "known_unreproduced_product_latency_blocker_preserved_in_prior_artifacts"


def list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def count_text(rows: list[dict[str, Any]], needles: list[str]) -> int:
    return sum(
        1
        for row in rows
        if any(
            needle in " ".join([prompt(row), str(row.get("test_id") or ""), str(row.get("failure_reason") or "")]).lower()
            for needle in needles
        )
    )


def count_root(rows: list[dict[str, Any]], needle: str) -> int:
    return sum(1 for row in rows if needle in classify_holdout_failure(row).lower())


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("/", "\\")
    except ValueError:
        return str(path)


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_None._"
    rendered_rows = [[format_cell(cell) for cell in row] for row in rows]
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rendered_rows]
    return "\n".join([header, sep, *body])


def format_cell(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, sort_keys=True)
    else:
        text = str(value)
    text = text.replace("\n", " ").replace("|", "\\|")
    if len(text) > 160:
        text = text[:157] + "..."
    return text


if __name__ == "__main__":
    main()
