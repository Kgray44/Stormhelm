from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / ".artifacts" / "command-usability-eval"
OUT_DIR = ARTIFACT_ROOT / "route-spine-translation-audit"

BEST_DIR = ARTIFACT_ROOT / "readiness-pass-3"
ARCH_DIR = ARTIFACT_ROOT / "router-architecture-reset"
MIG2_DIR = ARTIFACT_ROOT / "route-spine-migration-2"

BEST_250 = BEST_DIR / "250_post_readiness_3_results.jsonl"
BEST_250_SUMMARY = BEST_DIR / "250_post_readiness_3_summary.json"
ARCH_250 = ARCH_DIR / "250_post_router_architecture_results.jsonl"
ARCH_250_SUMMARY = ARCH_DIR / "250_post_router_architecture_summary.json"
MIG2_250 = MIG2_DIR / "250_post_migration_2_results.jsonl"
MIG2_250_SUMMARY = MIG2_DIR / "250_post_migration_2_summary.json"
MIG2_TARGETED = MIG2_DIR / "targeted_migration_integration_results.jsonl"
MIG2_TARGETED_SUMMARY = MIG2_DIR / "targeted_migration_integration_summary.json"
SPEC_DESIGN = ARCH_DIR / "route_family_spec_design.json"


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value == "":
        return []
    return [value]


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def metric(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def percentile(values: list[float], pct: float) -> float:
    clean = sorted(v for v in values if v is not None and not math.isnan(v))
    if not clean:
        return 0.0
    if len(clean) == 1:
        return clean[0]
    pos = (len(clean) - 1) * pct
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return clean[lo]
    return clean[lo] + (clean[hi] - clean[lo]) * (pos - lo)


def summary_stats(values: list[float]) -> dict[str, float]:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if not clean:
        return {"avg": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "avg": round(mean(clean), 3),
        "p50": round(percentile(clean, 0.50), 3),
        "p90": round(percentile(clean, 0.90), 3),
        "p95": round(percentile(clean, 0.95), 3),
        "max": round(max(clean), 3),
    }


def assertion(row: dict[str, Any], name: str) -> dict[str, Any] | None:
    assertions = row.get("assertions") or {}
    item = assertions.get(name)
    return item if isinstance(item, dict) else None


def assertion_passed(row: dict[str, Any], name: str, fallback: bool) -> bool:
    item = assertion(row, name)
    if item is None:
        return fallback
    return boolish(item.get("passed"))


def expected_actual_equal(row: dict[str, Any], expected_key: str, actual_key: str) -> bool:
    expected = row.get(expected_key)
    actual = row.get(actual_key)
    if isinstance(expected, list) or isinstance(actual, list):
        return as_list(expected) == as_list(actual)
    if expected in (None, "", "any"):
        return True
    return expected == actual


def result_state_matches(row: dict[str, Any]) -> bool:
    expected = row.get("expected_result_state")
    actual = row.get("actual_result_state") or row.get("result_state")
    if expected in (None, "", "any"):
        return True
    if expected == "dry_run_or_completed":
        return actual in {"dry_run", "completed", "planned", "would_execute"}
    if expected == "needs_clarification_or_blocked":
        return actual in {"needs_clarification", "blocked_missing_context", "blocked"}
    if isinstance(expected, list):
        return actual in expected
    return expected == actual


def normalize_engine(row: dict[str, Any]) -> str:
    engine = (row.get("routing_engine") or "").strip()
    if engine in {"route_spine", "legacy_planner", "direct_handler", "generic_provider", "mixed"}:
        return engine
    surface = (row.get("route_surface_type") or "").strip()
    if surface in {"direct", "direct_handler"}:
        return "direct_handler"
    if row.get("actual_route_family") == "generic_provider":
        return "generic_provider"
    return "unknown"


def top_level_candidates(row: dict[str, Any]) -> list[str]:
    candidates = row.get("candidate_specs_considered")
    if isinstance(candidates, list):
        return [str(x) for x in candidates]
    actual = ((row.get("assertions") or {}).get("target_slots") or {}).get("actual")
    if isinstance(actual, dict):
        candidates = actual.get("candidate_specs_considered")
        if isinstance(candidates, list):
            return [str(x) for x in candidates]
    return []


def native_declines(row: dict[str, Any]) -> dict[str, Any]:
    declines = row.get("native_decline_reasons")
    if isinstance(declines, dict):
        return declines
    actual = ((row.get("assertions") or {}).get("target_slots") or {}).get("actual")
    if isinstance(actual, dict) and isinstance(actual.get("native_decline_reasons"), dict):
        return actual["native_decline_reasons"]
    return {}


def selected_spec(row: dict[str, Any]) -> str:
    value = row.get("selected_route_spec")
    if value:
        return str(value)
    actual = ((row.get("assertions") or {}).get("target_slots") or {}).get("actual")
    if isinstance(actual, dict) and actual.get("selected_route_spec"):
        return str(actual["selected_route_spec"])
    return ""


def route_spec_exists(row: dict[str, Any], known_specs: set[str]) -> bool:
    expected = row.get("expected_route_family")
    return bool(expected and (expected in known_specs or expected in top_level_candidates(row)))


def row_axes(row: dict[str, Any]) -> dict[str, bool]:
    failure_category = row.get("failure_category") or ""
    route_correct = assertion_passed(
        row,
        "route_family",
        expected_actual_equal(row, "expected_route_family", "actual_route_family"),
    )
    subsystem_correct = assertion_passed(
        row,
        "subsystem",
        expected_actual_equal(row, "expected_subsystem", "actual_subsystem"),
    )
    tool_correct = assertion_passed(
        row,
        "tool_chain",
        expected_actual_equal(row, "expected_tool", "actual_tool"),
    )
    result_state_correct = result_state_matches(row)
    latency_pass = assertion_passed(row, "latency", failure_category != "latency_issue")
    payload_assert = assertion_passed(row, "payload_guardrail", failure_category != "payload_guardrail_failure")
    payload_triggered = boolish(row.get("payload_guardrail_triggered"))
    payload_reason = row.get("payload_guardrail_reason") or ""
    payload_pass = payload_assert and failure_category != "payload_guardrail_failure" and not (
        payload_triggered and payload_reason != "workspace_items_truncated"
    )
    provider_pass = assertion_passed(row, "provider_usage", not boolish(row.get("provider_call_violation")))
    provider_pass = provider_pass and not any(
        metric(row, key) > 0
        for key in (
            "provider_call_count",
            "openai_call_count",
            "llm_call_count",
            "embedding_call_count",
        )
    )
    safety_pass = not boolish(row.get("external_action_performed")) and not boolish(
        row.get("process_killed")
    ) and row.get("status") != "hard_timeout"
    approval_policy_pass = assertion_passed(row, "approval", True)
    response_asserts = [
        assertion_passed(row, "response_meaning", True),
        assertion_passed(row, "no_overclaim", True),
        assertion_passed(row, "clarification", True),
        assertion_passed(row, "target_slots", True),
    ]
    response_correct = all(response_asserts) and failure_category != "response_correctness_failure"
    return {
        "route_correct": route_correct,
        "subsystem_correct": subsystem_correct,
        "tool_correct": tool_correct,
        "result_state_correct": result_state_correct,
        "response_correct": response_correct,
        "latency_pass": latency_pass,
        "payload_pass": payload_pass,
        "safety_pass": safety_pass,
        "provider_pass": provider_pass,
        "approval_policy_pass": approval_policy_pass,
        "final_pass": boolish(row.get("passed")),
    }


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "prompt": row.get("prompt") or row.get("input"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "expected_subsystem": row.get("expected_subsystem"),
        "actual_subsystem": row.get("actual_subsystem"),
        "expected_tool": row.get("expected_tool"),
        "actual_tool": row.get("actual_tool"),
        "expected_result_state": row.get("expected_result_state"),
        "actual_result_state": row.get("actual_result_state"),
        "failure_category": row.get("failure_category"),
        "failure_reason": row.get("failure_reason"),
        "routing_engine": normalize_engine(row),
        "route_surface_type": row.get("route_surface_type"),
        "selected_route_spec": selected_spec(row),
        "latency_ms": row.get("latency_ms") or row.get("total_latency_ms"),
        "response_json_bytes": row.get("response_json_bytes"),
    }


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(Counter(str(row.get(key) or "") for row in rows))


def axes_for_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, bool]]:
    return {str(row.get("test_id")): row_axes(row) for row in rows}


def load_known_specs(rows: list[dict[str, Any]]) -> set[str]:
    specs: set[str] = set()
    data = load_json(SPEC_DESIGN, {})
    for spec in data.get("route_family_specs", []) if isinstance(data, dict) else []:
        if isinstance(spec, dict) and spec.get("route_family"):
            specs.add(str(spec["route_family"]))
    for row in rows:
        specs.update(top_level_candidates(row))
    return specs


def markdown_table(headers: list[str], rows: list[list[Any]], limit: int | None = None) -> str:
    if limit is not None:
        rows = rows[:limit]
    def cell(value: Any) -> str:
        text = "" if value is None else str(value)
        text = text.replace("\n", " ").replace("|", "\\|")
        if len(text) > 140:
            text = text[:137] + "..."
        return text
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(cell(v) for v in row) + " |")
    return "\n".join(out)


def score_decomposition(rows: list[dict[str, Any]]) -> dict[str, Any]:
    row_details = []
    counters = Counter()
    failures = [row for row in rows if not boolish(row.get("passed"))]
    for row in rows:
        axes = row_axes(row)
        detail = compact_row(row) | axes
        row_details.append(detail)
        for name, passed in axes.items():
            if passed:
                counters[f"{name}_true"] += 1
            else:
                counters[f"{name}_false"] += 1
    def all_except(axes: dict[str, bool], excluded: set[str]) -> bool:
        return all(v for k, v in axes.items() if k not in excluded and k != "final_pass")
    if_latency_excluded = sum(1 for row in rows if row_axes(row)["final_pass"] or all_except(row_axes(row), {"latency_pass"}))
    if_response_excluded = sum(1 for row in rows if row_axes(row)["final_pass"] or all_except(row_axes(row), {"response_correct"}))
    route_correct_nonrouting_fail = [
        compact_row(row) | row_axes(row)
        for row in failures
        if row_axes(row)["route_correct"]
    ]
    pure_route_fail = [
        compact_row(row) | row_axes(row)
        for row in failures
        if not row_axes(row)["route_correct"]
        and row_axes(row)["latency_pass"]
        and row_axes(row)["payload_pass"]
        and row_axes(row)["provider_pass"]
        and row_axes(row)["safety_pass"]
        and row_axes(row)["approval_policy_pass"]
        and row_axes(row)["response_correct"]
    ]
    taxonomy_like = [
        compact_row(row) | row_axes(row)
        for row in failures
        if row_axes(row)["route_correct"]
        and (
            not row_axes(row)["subsystem_correct"]
            or not row_axes(row)["tool_correct"]
            or not row_axes(row)["result_state_correct"]
        )
        and row.get("failure_category") not in {"latency_issue", "response_correctness_failure"}
    ]
    not_spine_owned = [
        compact_row(row) | row_axes(row)
        for row in failures
        if normalize_engine(row) != "route_spine"
    ]
    answer = {
        "total_rows": len(rows),
        "final_pass": sum(1 for row in rows if boolish(row.get("passed"))),
        "final_fail": len(failures),
        "axis_counts": dict(counters),
        "would_pass_if_latency_excluded": if_latency_excluded,
        "would_pass_if_response_correctness_excluded": if_response_excluded,
        "route_correct_but_nonrouting_fail_count": len(route_correct_nonrouting_fail),
        "pure_route_family_failure_count": len(pure_route_fail),
        "taxonomy_label_mismatch_like_count": len(taxonomy_like),
        "fail_because_route_spine_did_not_own_count": len(not_spine_owned),
        "route_correct_but_nonrouting_fail_examples": route_correct_nonrouting_fail[:30],
        "pure_route_family_failure_examples": pure_route_fail[:30],
        "taxonomy_label_mismatch_like_examples": taxonomy_like[:30],
        "not_route_spine_owned_failure_examples": not_spine_owned[:30],
        "rows": row_details,
    }
    return answer


def write_score_decomposition(data: dict[str, Any]) -> None:
    lines = [
        "# Score Decomposition",
        "",
        f"- Total rows: {data['total_rows']}",
        f"- Final pass/fail: {data['final_pass']} pass / {data['final_fail']} fail",
        f"- Would pass if latency were excluded: {data['would_pass_if_latency_excluded']}",
        f"- Would pass if response correctness were excluded: {data['would_pass_if_response_correctness_excluded']}",
        f"- Route-correct but failed for non-routing reasons: {data['route_correct_but_nonrouting_fail_count']}",
        f"- Pure route-family failures: {data['pure_route_family_failure_count']}",
        f"- Taxonomy/label mismatch-like failures: {data['taxonomy_label_mismatch_like_count']}",
        f"- Failures where route spine did not own decision: {data['fail_because_route_spine_did_not_own_count']}",
        "",
        "## Axis Counts",
        "",
        markdown_table(["axis", "count"], [[k, v] for k, v in sorted(data["axis_counts"].items())]),
        "",
        "## Route-Correct Non-Routing Failures",
        "",
        markdown_table(
            ["test_id", "category", "engine", "route", "tool", "latency", "response", "prompt"],
            [
                [
                    row["test_id"],
                    row["failure_category"],
                    row["routing_engine"],
                    f"{row['expected_route_family']}->{row['actual_route_family']}",
                    f"{row['expected_tool']}->{row['actual_tool']}",
                    row["latency_pass"],
                    row["response_correct"],
                    row["prompt"],
                ]
                for row in data["route_correct_but_nonrouting_fail_examples"]
            ],
            limit=30,
        ),
        "",
        "## Pure Route-Family Failures",
        "",
        markdown_table(
            ["test_id", "category", "engine", "expected", "actual", "prompt"],
            [
                [
                    row["test_id"],
                    row["failure_category"],
                    row["routing_engine"],
                    row["expected_route_family"],
                    row["actual_route_family"],
                    row["prompt"],
                ]
                for row in data["pure_route_family_failure_examples"]
            ],
            limit=30,
        ),
    ]
    write_text(OUT_DIR / "score_decomposition.md", "\n".join(lines) + "\n")


def routing_engine_impact(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[normalize_engine(row)].append(row)
    result: dict[str, Any] = {}
    for engine, engine_rows in sorted(groups.items()):
        failures = [row for row in engine_rows if not boolish(row.get("passed"))]
        latencies = [metric(row, "latency_ms", metric(row, "total_latency_ms")) for row in engine_rows]
        result[engine] = {
            "attempted": len(engine_rows),
            "pass": len(engine_rows) - len(failures),
            "fail": len(failures),
            "pass_rate": round((len(engine_rows) - len(failures)) / len(engine_rows), 4) if engine_rows else 0.0,
            "failure_categories": count_by(failures, "failure_category"),
            "route_correct_count": sum(1 for row in engine_rows if row_axes(row)["route_correct"]),
            "subsystem_correct_count": sum(1 for row in engine_rows if row_axes(row)["subsystem_correct"]),
            "latency_issue_count": sum(1 for row in failures if row.get("failure_category") == "latency_issue"),
            "response_correctness_failure_count": sum(
                1 for row in failures if row.get("failure_category") == "response_correctness_failure"
            ),
            "latency_ms": summary_stats(latencies),
            "generic_fallback_count": sum(1 for row in engine_rows if row.get("actual_route_family") == "generic_provider"),
            "provider_call_count": sum(int(metric(row, "provider_call_count")) for row in engine_rows),
            "openai_call_count": sum(int(metric(row, "openai_call_count")) for row in engine_rows),
            "llm_call_count": sum(int(metric(row, "llm_call_count")) for row in engine_rows),
            "embedding_call_count": sum(int(metric(row, "embedding_call_count")) for row in engine_rows),
            "top_failures": [compact_row(row) for row in failures[:30]],
        }
    route_spine = result.get("route_spine", {})
    legacy = result.get("legacy_planner", {})
    result["_answers"] = {
        "route_spine_pass_rate_higher_than_legacy": (
            route_spine.get("pass_rate", 0.0) > legacy.get("pass_rate", 0.0)
            if route_spine and legacy
            else None
        ),
        "route_spine_primary_failures": result.get("route_spine", {}).get("failure_categories", {}),
        "legacy_primary_failures": result.get("legacy_planner", {}).get("failure_categories", {}),
        "legacy_still_main_source_of_real_routing_gap": (
            result.get("legacy_planner", {}).get("failure_categories", {}).get("real_routing_gap", 0)
            >= result.get("route_spine", {}).get("failure_categories", {}).get("real_routing_gap", 0)
        ),
    }
    return result


def write_routing_engine_impact(data: dict[str, Any]) -> None:
    engines = [k for k in data.keys() if not k.startswith("_")]
    lines = [
        "# Routing Engine Impact",
        "",
        markdown_table(
            [
                "engine",
                "attempted",
                "pass",
                "fail",
                "pass_rate",
                "failure_categories",
                "p95_ms",
                "generic_fallbacks",
                "provider_calls",
            ],
            [
                [
                    engine,
                    data[engine]["attempted"],
                    data[engine]["pass"],
                    data[engine]["fail"],
                    data[engine]["pass_rate"],
                    data[engine]["failure_categories"],
                    data[engine]["latency_ms"]["p95"],
                    data[engine]["generic_fallback_count"],
                    data[engine]["provider_call_count"],
                ]
                for engine in engines
            ],
        ),
        "",
        "## Answers",
        "",
        f"- Route-spine pass rate higher than legacy: {data['_answers']['route_spine_pass_rate_higher_than_legacy']}",
        f"- Route-spine primary failures: `{data['_answers']['route_spine_primary_failures']}`",
        f"- Legacy primary failures: `{data['_answers']['legacy_primary_failures']}`",
        f"- Legacy still main source of real routing gap: {data['_answers']['legacy_still_main_source_of_real_routing_gap']}",
    ]
    write_text(OUT_DIR / "routing_engine_impact.md", "\n".join(lines) + "\n")


def movement_report(best_rows: list[dict[str, Any]], arch_rows: list[dict[str, Any]], mig_rows: list[dict[str, Any]]) -> dict[str, Any]:
    best = {row.get("test_id"): row for row in best_rows}
    arch = {row.get("test_id"): row for row in arch_rows}
    mig = {row.get("test_id"): row for row in mig_rows}
    test_ids = sorted(set(best) | set(arch) | set(mig))
    rows = []
    counts = Counter()
    pass_to_fail = []
    fail_to_pass = []
    for test_id in test_ids:
        b = best.get(test_id, {})
        a = arch.get(test_id, {})
        m = mig.get(test_id, {})
        best_pass = boolish(b.get("passed"))
        arch_pass = boolish(a.get("passed"))
        mig_pass = boolish(m.get("passed"))
        movement = "stayed_pass" if best_pass and mig_pass else "stayed_fail" if not best_pass and not mig_pass else "pass_to_fail" if best_pass and not mig_pass else "fail_to_pass"
        row = {
            "test_id": test_id,
            "movement_best_to_migration2": movement,
            "best_pass": best_pass,
            "router_arch_pass": arch_pass,
            "migration2_pass": mig_pass,
            "best_category": b.get("failure_category"),
            "router_arch_category": a.get("failure_category"),
            "migration2_category": m.get("failure_category"),
            "failure_category_changed": b.get("failure_category") != m.get("failure_category"),
            "routing_engine_changed": normalize_engine(b) != normalize_engine(m),
            "route_family_changed": b.get("actual_route_family") != m.get("actual_route_family"),
            "subsystem_changed": b.get("actual_subsystem") != m.get("actual_subsystem"),
            "latency_status_changed": (b.get("failure_category") == "latency_issue") != (m.get("failure_category") == "latency_issue"),
            "taxonomy_status_changed": (
                b.get("actual_subsystem") != b.get("expected_subsystem")
            ) != (m.get("actual_subsystem") != m.get("expected_subsystem")),
            "prompt": m.get("prompt") or b.get("prompt"),
            "best_engine": normalize_engine(b),
            "migration2_engine": normalize_engine(m),
            "best_route": f"{b.get('expected_route_family')}->{b.get('actual_route_family')}",
            "migration2_route": f"{m.get('expected_route_family')}->{m.get('actual_route_family')}",
        }
        if movement == "pass_to_fail":
            row["regression_classification"] = classify_pass_to_fail(m)
            pass_to_fail.append(row)
        elif movement == "fail_to_pass":
            row["fix_source"] = classify_fail_to_pass(b, m)
            fail_to_pass.append(row)
        rows.append(row)
        counts[movement] += 1
        if row["failure_category_changed"]:
            counts["failure_category_changed"] += 1
        if row["routing_engine_changed"]:
            counts["routing_engine_changed"] += 1
        if row["route_family_changed"]:
            counts["route_family_changed"] += 1
    return {
        "counts": dict(counts),
        "pass_to_fail": pass_to_fail,
        "fail_to_pass": fail_to_pass,
        "rows": rows,
    }


def classify_pass_to_fail(row: dict[str, Any]) -> str:
    category = row.get("failure_category")
    axes = row_axes(row)
    if category == "latency_issue":
        return "latency_reclassification_or_slower_path"
    if category == "response_correctness_failure":
        return "response_or_target_slot_translation"
    if category == "missing_telemetry":
        return "telemetry_reclassification"
    if axes["route_correct"] and not axes["subsystem_correct"]:
        return "taxonomy_or_subsystem_label"
    if normalize_engine(row) == "route_spine":
        return "route_spine_related_real_regression"
    return "unknown_or_legacy_regression"


def classify_fail_to_pass(old: dict[str, Any], new: dict[str, Any]) -> str:
    if normalize_engine(new) == "route_spine":
        return "route_spine_migration_or_spine_translation"
    if normalize_engine(old) != normalize_engine(new):
        return "routing_engine_change"
    return "non_spine_or_existing_behavior"


def write_movement_report(data: dict[str, Any]) -> None:
    lines = [
        "# Failure Movement Report",
        "",
        "## Movement Counts",
        "",
        markdown_table(["movement", "count"], [[k, v] for k, v in sorted(data["counts"].items())]),
        "",
        "## Pass To Fail",
        "",
        markdown_table(
            ["test_id", "category", "classification", "engine", "route", "prompt"],
            [
                [
                    row["test_id"],
                    row["migration2_category"],
                    row.get("regression_classification"),
                    row["migration2_engine"],
                    row["migration2_route"],
                    row["prompt"],
                ]
                for row in data["pass_to_fail"]
            ],
            limit=40,
        ),
        "",
        "## Fail To Pass",
        "",
        markdown_table(
            ["test_id", "old_category", "new_engine", "fix_source", "route", "prompt"],
            [
                [
                    row["test_id"],
                    row["best_category"],
                    row["migration2_engine"],
                    row.get("fix_source"),
                    row["migration2_route"],
                    row["prompt"],
                ]
                for row in data["fail_to_pass"]
            ],
            limit=40,
        ),
    ]
    write_text(OUT_DIR / "failure_movement_report.md", "\n".join(lines) + "\n")


def real_routing_gap_autopsy(rows: list[dict[str, Any]], known_specs: set[str]) -> dict[str, Any]:
    gaps = [row for row in rows if row.get("failure_category") == "real_routing_gap"]
    details = []
    counts = Counter()
    for row in gaps:
        expected = row.get("expected_route_family")
        candidates = top_level_candidates(row)
        declines = native_declines(row)
        candidate_present = expected in candidates
        spec_exists = route_spec_exists(row, known_specs)
        declined = expected in declines
        decline_reason = declines.get(expected, [])
        classification = classify_routing_gap(row, known_specs, candidate_present, spec_exists, declined)
        counts[classification] += 1
        details.append(
            compact_row(row)
            | {
                "route_spine_candidate_present": candidate_present,
                "route_spec_exists": spec_exists,
                "route_spec_declined": declined,
                "decline_reason": decline_reason,
                "generic_provider_eligible": row.get("generic_provider_eligible"),
                "legacy_planner_used": normalize_engine(row) == "legacy_planner",
                "missing_context": bool(as_list(row.get("missing_preconditions"))),
                "unsupported_expected_feature": row.get("implemented_routeable_status") in {"scaffold_only", "docs_only"},
                "taxonomy_mismatch": row_axes(row)["route_correct"] and not row_axes(row)["subsystem_correct"],
                "likely_fix_type": classification,
                "candidate_specs_considered": candidates[:40],
                "selected_route_spec": selected_spec(row),
                "generic_provider_gate_reason": row.get("generic_provider_gate_reason"),
                "fallback_reason": row.get("fallback_reason"),
            }
        )
    grouped = defaultdict(Counter)
    for item in details:
        grouped[str(item["expected_route_family"])][item["likely_fix_type"]] += 1
    return {
        "total_real_routing_gaps": len(gaps),
        "classification_counts": dict(counts),
        "by_expected_family": {k: dict(v) for k, v in sorted(grouped.items())},
        "rows": details,
    }


def classify_routing_gap(
    row: dict[str, Any],
    known_specs: set[str],
    candidate_present: bool,
    spec_exists: bool,
    declined: bool,
) -> str:
    engine = normalize_engine(row)
    actual = row.get("actual_route_family")
    expected = row.get("expected_route_family")
    if row.get("implemented_routeable_status") in {"scaffold_only", "docs_only"}:
        return "unsupported_feature_expected"
    if engine == "legacy_planner" and not spec_exists:
        return "unmigrated_family"
    if engine == "legacy_planner":
        return "legacy_planner_interference"
    if actual == "generic_provider" and candidate_present and not boolish(row.get("generic_provider_eligible")):
        return "generic_provider_gate_bug"
    if actual == "generic_provider" and candidate_present:
        return "generic_provider_gate_bug"
    if spec_exists and not candidate_present:
        return "intent_frame_extraction_gap"
    if spec_exists and declined:
        reasons = " ".join(map(str, as_list(native_declines(row).get(expected))))
        if "context" in reasons or as_list(row.get("missing_preconditions")):
            return "missing_context_should_clarify"
        return "migrated_family_spec_gap"
    if spec_exists and candidate_present and selected_spec(row) == expected and actual != expected:
        return "generic_provider_gate_bug"
    if spec_exists:
        return "target_extraction_gap"
    return "unmigrated_family"


def write_real_routing_gap_autopsy(data: dict[str, Any]) -> None:
    lines = [
        "# Real Routing Gap Autopsy",
        "",
        f"- Total real routing gaps: {data['total_real_routing_gaps']}",
        "",
        "## Classification Counts",
        "",
        markdown_table(["classification", "count"], [[k, v] for k, v in sorted(data["classification_counts"].items())]),
        "",
        "## By Expected Family",
        "",
        markdown_table(
            ["expected_family", "classifications"],
            [[family, counts] for family, counts in sorted(data["by_expected_family"].items())],
        ),
        "",
        "## Gap Rows",
        "",
        markdown_table(
            ["test_id", "expected", "actual", "engine", "spec", "candidate", "selected", "fix_type", "prompt"],
            [
                [
                    row["test_id"],
                    row["expected_route_family"],
                    row["actual_route_family"],
                    row["routing_engine"],
                    row["route_spec_exists"],
                    row["route_spine_candidate_present"],
                    row["selected_route_spec"],
                    row["likely_fix_type"],
                    row["prompt"],
                ]
                for row in data["rows"]
            ],
            limit=80,
        ),
    ]
    write_text(OUT_DIR / "real_routing_gap_autopsy.md", "\n".join(lines) + "\n")


def taxonomy_scoring_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    entries = []
    counts = Counter()
    for row in rows:
        if boolish(row.get("passed")):
            continue
        axes = row_axes(row)
        classification = None
        reason = ""
        if axes["route_correct"] and not axes["subsystem_correct"]:
            classification = "compatibility_mapping_missing"
            reason = "route family correct but subsystem label differs"
        elif axes["route_correct"] and not axes["tool_correct"] and row.get("failure_category") != "latency_issue":
            classification = "route_spec_naming_issue"
            reason = "route family/subsystem are correct but tool chain or target slots differ"
        elif axes["route_correct"] and not axes["result_state_correct"]:
            classification = "product_taxonomy_bug"
            reason = "result_state differs from expected semantics"
        elif row.get("failure_category") == "missing_telemetry":
            classification = "compatibility_mapping_missing"
            reason = "route telemetry/surface mapping missing"
        elif row.get("failure_category") == "response_correctness_failure" and axes["route_correct"]:
            classification = "compatibility_mapping_missing"
            reason = "route is semantically correct, but target-slot/approval/clarification scoring fails"
        elif row.get("failure_category") == "real_routing_gap":
            classification = "true_product_routing_failure"
            reason = "route family mismatch"
        elif row.get("failure_category") == "latency_issue":
            classification = "true_product_routing_failure"
            reason = "not a taxonomy issue; latency-only scoring failure"
        if classification:
            counts[classification] += 1
            entries.append(compact_row(row) | row_axes(row) | {"taxonomy_classification": classification, "reason": reason})
    return {"classification_counts": dict(counts), "rows": entries}


def write_taxonomy_scoring_audit(data: dict[str, Any]) -> None:
    lines = [
        "# Taxonomy And Scoring Audit",
        "",
        markdown_table(["classification", "count"], [[k, v] for k, v in sorted(data["classification_counts"].items())]),
        "",
        "## Rows",
        "",
        markdown_table(
            ["test_id", "category", "classification", "route", "tool_correct", "result_state_correct", "reason"],
            [
                [
                    row["test_id"],
                    row["failure_category"],
                    row["taxonomy_classification"],
                    f"{row['expected_route_family']}->{row['actual_route_family']}",
                    row["tool_correct"],
                    row["result_state_correct"],
                    row["reason"],
                ]
                for row in data["rows"]
            ],
            limit=100,
        ),
    ]
    write_text(OUT_DIR / "taxonomy_scoring_audit.md", "\n".join(lines) + "\n")


def latency_influence_audit(rows: list[dict[str, Any]], targeted_rows: list[dict[str, Any]]) -> dict[str, Any]:
    latency_250 = [row for row in rows if row.get("failure_category") == "latency_issue"]
    latency_targeted = [row for row in targeted_rows if row.get("failure_category") == "latency_issue" or not row_axes(row)["latency_pass"]]
    combined = [("250", row) for row in latency_250] + [("targeted", row) for row in latency_targeted]
    entries = []
    for source, row in combined:
        axes = row_axes(row)
        only_latency = (
            not axes["latency_pass"]
            and axes["route_correct"]
            and axes["subsystem_correct"]
            and axes["tool_correct"]
            and axes["response_correct"]
            and axes["payload_pass"]
            and axes["provider_pass"]
            and axes["safety_pass"]
            and axes["approval_policy_pass"]
        )
        entries.append(
            compact_row(row)
            | {
                "source": source,
                "route_correct": axes["route_correct"],
                "subsystem_correct": axes["subsystem_correct"],
                "tool_correct": axes["tool_correct"],
                "latency_is_only_failure_axis": only_latency,
                "route_handler_ms": row.get("route_handler_ms"),
                "memory_context_ms": row.get("memory_context_ms"),
                "response_serialization_ms": row.get("response_serialization_ms"),
                "unattributed_latency_ms": row.get("unattributed_latency_ms"),
                "workspace_item_count": row.get("workspace_item_count"),
                "known_lane_labels": row.get("known_lane_labels") or [],
            }
        )
    latency_only_250 = sum(1 for row in latency_250 if next(e for e in entries if e["test_id"] == row.get("test_id") and e["source"] == "250")["latency_is_only_failure_axis"])
    by_engine = defaultdict(int)
    by_family = defaultdict(int)
    for entry in entries:
        by_engine[entry["routing_engine"]] += 1
        by_family[str(entry["expected_route_family"])] += 1
    return {
        "250_latency_issue_count": len(latency_250),
        "targeted_latency_issue_count": len(latency_targeted),
        "latency_alone_depresses_250_by": latency_only_250,
        "latency_failures_by_routing_engine": dict(sorted(by_engine.items())),
        "latency_failures_by_expected_family": dict(sorted(by_family.items())),
        "route_spine_latency_failures_250": sum(1 for row in latency_250 if normalize_engine(row) == "route_spine"),
        "answers": {
            "routing_readiness_should_be_reported_separately_from_latency": latency_only_250 > 0,
            "route_spine_disproportionately_failing_latency": sum(1 for row in latency_250 if normalize_engine(row) == "route_spine") > len(latency_250) / 2 if latency_250 else False,
            "latency_concentrated_in_workspace_or_direct_routes": any(
                family in by_family for family in ("workspace_operations", "routine", "terminal")
            ),
        },
        "rows": entries,
    }


def write_latency_influence_audit(data: dict[str, Any]) -> None:
    lines = [
        "# Latency Influence Audit",
        "",
        f"- 250 latency issue rows: {data['250_latency_issue_count']}",
        f"- Targeted lane latency issue rows: {data['targeted_latency_issue_count']}",
        f"- 250 rows where latency is the only failing axis: {data['latency_alone_depresses_250_by']}",
        f"- Route-spine latency failures in 250: {data['route_spine_latency_failures_250']}",
        "",
        "## By Routing Engine",
        "",
        markdown_table(["engine", "count"], [[k, v] for k, v in data["latency_failures_by_routing_engine"].items()]),
        "",
        "## By Expected Family",
        "",
        markdown_table(["family", "count"], [[k, v] for k, v in data["latency_failures_by_expected_family"].items()]),
        "",
        "## Latency Rows",
        "",
        markdown_table(
            ["source", "test_id", "family", "engine", "latency_ms", "only_latency", "unattributed_ms", "payload"],
            [
                [
                    row["source"],
                    row["test_id"],
                    row["expected_route_family"],
                    row["routing_engine"],
                    row["latency_ms"],
                    row["latency_is_only_failure_axis"],
                    row["unattributed_latency_ms"],
                    row["response_json_bytes"],
                ]
                for row in data["rows"]
            ],
            limit=80,
        ),
    ]
    write_text(OUT_DIR / "latency_influence_audit.md", "\n".join(lines) + "\n")


def route_spine_coverage_audit(rows: list[dict[str, Any]], known_specs: set[str]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("expected_route_family") or "")].append(row)
    families = {}
    for family, family_rows in sorted(groups.items()):
        by_engine = Counter(normalize_engine(row) for row in family_rows)
        pass_fail_by_engine: dict[str, dict[str, int]] = {}
        for engine in by_engine:
            engine_rows = [row for row in family_rows if normalize_engine(row) == engine]
            pass_fail_by_engine[engine] = {
                "pass": sum(1 for row in engine_rows if boolish(row.get("passed"))),
                "fail": sum(1 for row in engine_rows if not boolish(row.get("passed"))),
            }
        failures = [row for row in family_rows if not boolish(row.get("passed"))]
        real_gaps = sum(1 for row in failures if row.get("failure_category") == "real_routing_gap")
        legacy_fails = sum(1 for row in failures if normalize_engine(row) == "legacy_planner")
        generic_fails = sum(1 for row in failures if normalize_engine(row) == "generic_provider" or row.get("actual_route_family") == "generic_provider")
        if real_gaps + legacy_fails + generic_fails >= 3:
            expected_benefit = "high"
        elif real_gaps + legacy_fails + generic_fails >= 1:
            expected_benefit = "medium"
        else:
            expected_benefit = "low"
        families[family] = {
            "total_cases": len(family_rows),
            "route_spine_cases": by_engine.get("route_spine", 0),
            "legacy_planner_cases": by_engine.get("legacy_planner", 0),
            "direct_handler_cases": by_engine.get("direct_handler", 0),
            "generic_provider_cases": by_engine.get("generic_provider", 0),
            "unknown_cases": by_engine.get("unknown", 0),
            "pass_fail_by_routing_engine": pass_fail_by_engine,
            "route_spec_exists": family in known_specs,
            "should_migrate_next": (legacy_fails + generic_fails + real_gaps) >= 2,
            "expected_benefit_if_migrated": expected_benefit,
            "migration_risk": "high" if family in {"discord_relay", "trust_approvals", "terminal", "power"} else "medium" if real_gaps else "low",
            "failure_categories": count_by(failures, "failure_category"),
        }
    return {
        "families": families,
        "totals": {
            "route_spine_cases": sum(f["route_spine_cases"] for f in families.values()),
            "legacy_planner_cases": sum(f["legacy_planner_cases"] for f in families.values()),
            "generic_provider_cases": sum(f["generic_provider_cases"] for f in families.values()),
            "recommended_next_migration_candidates": [
                family
                for family, data in families.items()
                if data["should_migrate_next"] and data["expected_benefit_if_migrated"] in {"high", "medium"}
            ],
        },
    }


def write_route_spine_coverage(data: dict[str, Any]) -> None:
    lines = [
        "# Route Spine Coverage Audit",
        "",
        f"- Route-spine cases: {data['totals']['route_spine_cases']}",
        f"- Legacy-planner cases: {data['totals']['legacy_planner_cases']}",
        f"- Generic-provider cases: {data['totals']['generic_provider_cases']}",
        "",
        "## Family Coverage",
        "",
        markdown_table(
            [
                "family",
                "total",
                "spine",
                "legacy",
                "generic",
                "spec",
                "migrate_next",
                "benefit",
                "failures",
            ],
            [
                [
                    family,
                    item["total_cases"],
                    item["route_spine_cases"],
                    item["legacy_planner_cases"],
                    item["generic_provider_cases"],
                    item["route_spec_exists"],
                    item["should_migrate_next"],
                    item["expected_benefit_if_migrated"],
                    item["failure_categories"],
                ]
                for family, item in data["families"].items()
            ],
        ),
    ]
    write_text(OUT_DIR / "route_spine_coverage_audit.md", "\n".join(lines) + "\n")


def build_decision(
    score: dict[str, Any],
    engine: dict[str, Any],
    gaps: dict[str, Any],
    taxonomy: dict[str, Any],
    latency: dict[str, Any],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    route_spine = engine.get("route_spine", {})
    legacy = engine.get("legacy_planner", {})
    route_spine_healthier = (
        route_spine.get("pass_rate", 0.0) > legacy.get("pass_rate", 0.0)
        and route_spine.get("attempted", 0) > 0
    )
    unmigrated_or_legacy = sum(
        gaps.get("classification_counts", {}).get(key, 0)
        for key in ("unmigrated_family", "legacy_planner_interference")
    )
    taxonomy_like = score.get("taxonomy_label_mismatch_like_count", 0) + taxonomy.get("classification_counts", {}).get("compatibility_mapping_missing", 0)
    latency_only = latency.get("latency_alone_depresses_250_by", 0)
    if route_spine_healthier and unmigrated_or_legacy >= 10:
        action = "migrate_more_families"
        rationale = "Route-spine rows are healthier than legacy rows, and a large share of real routing gaps still involve legacy/unmigrated ownership."
    elif taxonomy_like >= 15:
        action = "fix_taxonomy_scoring"
        rationale = "Many rows look semantically correct but fail due to label, tool, or result-state translation."
    elif latency_only >= 15:
        action = "fix_latency_scoring_or_latency_lane"
        rationale = "Latency alone is depressing the broad score enough to obscure routing readiness."
    elif gaps.get("classification_counts", {}).get("migrated_family_spec_gap", 0) >= 10:
        action = "fix_route_spine_specs"
        rationale = "Migrated families are still failing because their specs decline or select incorrectly."
    elif gaps.get("classification_counts", {}).get("intent_frame_extraction_gap", 0) >= 10:
        action = "fix_intent_frame_extraction"
        rationale = "Common failures are missing route-spine candidates despite existing specs."
    elif gaps.get("classification_counts", {}).get("missing_context_should_clarify", 0) >= 10:
        action = "fix_context_binding"
        rationale = "Context and missing-context clarification dominate the remaining routing gaps."
    else:
        action = "stop_and_manual_review"
        rationale = "The remaining failures are mixed enough that another automatic pass risks returning to whack-a-mole."
    return {
        "primary_next_action": action,
        "rationale": rationale,
        "decision_inputs": {
            "route_spine_pass_rate": route_spine.get("pass_rate"),
            "legacy_pass_rate": legacy.get("pass_rate"),
            "unmigrated_or_legacy_gap_count": unmigrated_or_legacy,
            "taxonomy_like_count": taxonomy_like,
            "latency_only_count": latency_only,
            "recommended_next_migration_candidates": coverage["totals"]["recommended_next_migration_candidates"],
        },
        "what_not_to_do_next": [
            "do not run 1000",
            "do not rerun 250 before acting on the audit decision",
            "do not patch exact prompts",
            "do not weaken provider, payload, approval, trust, dry-run, timeout, or scoring guardrails",
        ],
    }


def write_decision(data: dict[str, Any]) -> None:
    lines = [
        "# Translation Audit Decision",
        "",
        f"Primary next action: `{data['primary_next_action']}`",
        "",
        data["rationale"],
        "",
        "## Inputs",
        "",
        markdown_table(["input", "value"], [[k, v] for k, v in data["decision_inputs"].items()]),
        "",
        "## What Not To Do Next",
        "",
        "\n".join(f"- {item}" for item in data["what_not_to_do_next"]),
    ]
    write_text(OUT_DIR / "translation_audit_decision.md", "\n".join(lines) + "\n")


def write_translation_report(
    score: dict[str, Any],
    engine: dict[str, Any],
    movement: dict[str, Any],
    gaps: dict[str, Any],
    taxonomy: dict[str, Any],
    latency: dict[str, Any],
    coverage: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    route_spine = engine.get("route_spine", {})
    legacy = engine.get("legacy_planner", {})
    generic = engine.get("generic_provider", {})
    unknown = engine.get("unknown", {})
    lines = [
        "# Route-Spine Translation Audit Report",
        "",
        "## Executive Summary",
        "",
        "Route-spine authority is real, but the broad 250 score is being held down by translation and execution handoff issues, legacy/unmigrated ownership, latency, and response/target-slot scoring. The migration reduced legacy planner usage and eliminated wrong-subsystem failures, but many broad rows either never reached the spine or reached the spine and then failed at the command-result/evaluation boundary.",
        "",
        f"- Post-migration-2 250: {score['final_pass']} pass / {score['final_fail']} fail.",
        f"- Route-spine rows: {route_spine.get('attempted', 0)} with pass rate {route_spine.get('pass_rate', 0)}.",
        f"- Legacy rows: {legacy.get('attempted', 0)} with pass rate {legacy.get('pass_rate', 0)}.",
        f"- Generic-provider rows: {generic.get('attempted', 0)}.",
        f"- Unknown/direct rows: {unknown.get('attempted', 0)}.",
        f"- Real routing gaps: {gaps['total_real_routing_gaps']}; latency-only depression: {latency['latency_alone_depresses_250_by']} rows.",
        f"- Recommended next action: `{decision['primary_next_action']}`.",
        "",
        "## Why Route-Spine Wins Did Not Move 250 Much",
        "",
        "- The selected targeted lanes are route-spine-heavy; the broad 250 still contains substantial legacy/unknown coverage.",
        "- Wrong-subsystem failures disappeared, but route-family gaps did not: this means taxonomy normalization helped one axis while ownership gaps remained.",
        "- Some route-spine rows select the expected native spec but the final command result still becomes generic_provider or fails tool/target-slot expectations. That is a translation/adapter boundary, not a phrase-recognition failure.",
        "- Latency remains a separate scoring drag and should be reported independently from routing readiness.",
        "",
        "## Score Decomposition",
        "",
        f"- Would pass if latency were excluded: {score['would_pass_if_latency_excluded']}.",
        f"- Would pass if response correctness were excluded: {score['would_pass_if_response_correctness_excluded']}.",
        f"- Route-correct but non-routing failures: {score['route_correct_but_nonrouting_fail_count']}.",
        f"- Pure route-family failures: {score['pure_route_family_failure_count']}.",
        f"- Taxonomy/label mismatch-like failures: {score['taxonomy_label_mismatch_like_count']}.",
        f"- Failed rows not owned by route_spine: {score['fail_because_route_spine_did_not_own_count']}.",
        "",
        "## Routing-Engine Impact",
        "",
        markdown_table(
            ["engine", "attempted", "pass", "fail", "pass_rate", "failures", "p95_ms"],
            [
                [
                    engine_name,
                    engine_data["attempted"],
                    engine_data["pass"],
                    engine_data["fail"],
                    engine_data["pass_rate"],
                    engine_data["failure_categories"],
                    engine_data["latency_ms"]["p95"],
                ]
                for engine_name, engine_data in engine.items()
                if not engine_name.startswith("_")
            ],
        ),
        "",
        "## Failure Movement From Prior Runs",
        "",
        markdown_table(["movement", "count"], [[k, v] for k, v in sorted(movement["counts"].items())]),
        "",
        "## Real Routing Gap Autopsy",
        "",
        markdown_table(["classification", "count"], [[k, v] for k, v in sorted(gaps["classification_counts"].items())]),
        "",
        "## Taxonomy/Scoring Audit",
        "",
        markdown_table(["classification", "count"], [[k, v] for k, v in sorted(taxonomy["classification_counts"].items())]),
        "",
        "## Latency Influence Audit",
        "",
        f"- 250 latency issue rows: {latency['250_latency_issue_count']}.",
        f"- Targeted lane latency issue rows: {latency['targeted_latency_issue_count']}.",
        f"- Route-spine latency failures in 250: {latency['route_spine_latency_failures_250']}.",
        f"- Routing readiness should be reported separately from latency: {latency['answers']['routing_readiness_should_be_reported_separately_from_latency']}.",
        "",
        "## Route Spine Coverage Audit",
        "",
        f"- Total route-spine cases: {coverage['totals']['route_spine_cases']}.",
        f"- Total legacy-planner cases: {coverage['totals']['legacy_planner_cases']}.",
        f"- Total generic-provider cases: {coverage['totals']['generic_provider_cases']}.",
        f"- Recommended next migration candidates: `{coverage['totals']['recommended_next_migration_candidates']}`.",
        "",
        "## Recommended Next Action",
        "",
        f"`{decision['primary_next_action']}`",
        "",
        decision["rationale"],
        "",
        "## What Not To Do Next",
        "",
        "\n".join(f"- {item}" for item in decision["what_not_to_do_next"]),
    ]
    write_text(OUT_DIR / "translation_audit_report.md", "\n".join(lines) + "\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    best_rows = load_jsonl(BEST_250)
    arch_rows = load_jsonl(ARCH_250)
    mig_rows = load_jsonl(MIG2_250)
    targeted_rows = load_jsonl(MIG2_TARGETED)
    if not mig_rows:
        raise SystemExit(f"No rows loaded from {MIG2_250}")
    known_specs = load_known_specs(mig_rows)

    score = score_decomposition(mig_rows)
    write_json(OUT_DIR / "score_decomposition.json", score)
    write_score_decomposition(score)

    engine = routing_engine_impact(mig_rows)
    write_json(OUT_DIR / "routing_engine_impact.json", engine)
    write_routing_engine_impact(engine)

    movement = movement_report(best_rows, arch_rows, mig_rows)
    write_json(OUT_DIR / "failure_movement_report.json", movement)
    write_movement_report(movement)

    gaps = real_routing_gap_autopsy(mig_rows, known_specs)
    write_json(OUT_DIR / "real_routing_gap_autopsy.json", gaps)
    write_real_routing_gap_autopsy(gaps)

    taxonomy = taxonomy_scoring_audit(mig_rows)
    write_json(OUT_DIR / "taxonomy_scoring_audit.json", taxonomy)
    write_taxonomy_scoring_audit(taxonomy)

    latency = latency_influence_audit(mig_rows, targeted_rows)
    write_json(OUT_DIR / "latency_influence_audit.json", latency)
    write_latency_influence_audit(latency)

    coverage = route_spine_coverage_audit(mig_rows, known_specs)
    write_json(OUT_DIR / "route_spine_coverage_audit.json", coverage)
    write_route_spine_coverage(coverage)

    decision = build_decision(score, engine, gaps, taxonomy, latency, coverage)
    write_json(OUT_DIR / "translation_audit_decision.json", decision)
    write_decision(decision)

    write_translation_report(score, engine, movement, gaps, taxonomy, latency, coverage, decision)
    print(json.dumps({
        "out_dir": str(OUT_DIR),
        "decision": decision["primary_next_action"],
        "final_pass": score["final_pass"],
        "final_fail": score["final_fail"],
    }, indent=2))


if __name__ == "__main__":
    main()
