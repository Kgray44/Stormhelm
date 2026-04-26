from __future__ import annotations

import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "context-arbitration-pass"

RUNS = {
    "original_250": Path(".artifacts/command-usability-eval/250-checkpoint/250_results.jsonl"),
    "post_remediation": Path(".artifacts/command-usability-eval/250-remediation/250_post_remediation_results.jsonl"),
    "post_generalization": Path(".artifacts/command-usability-eval/generalization-overcapture-pass/250_post_generalization_results.jsonl"),
    "post_generalization_2": Path(
        ".artifacts/command-usability-eval/generalization-overcapture-pass-2/250_post_generalization_2_results.jsonl"
    ),
    "post_readiness_3": Path(".artifacts/command-usability-eval/readiness-pass-3/250_post_readiness_3_results.jsonl"),
}
HOLDOUT_4 = Path(".artifacts/command-usability-eval/readiness-pass-3/holdout_4_results.jsonl")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_rows = {name: _read_jsonl(path) for name, path in RUNS.items()}
    holdout_rows = _read_jsonl(HOLDOUT_4)
    progress = _progress_stagnation_audit(run_rows)
    holdout = _holdout_4_diagnosis(holdout_rows)
    gaps = _remaining_routing_gap_census(run_rows["post_readiness_3"])
    latency = _latency_lane_reclassification(run_rows["post_readiness_3"])
    design = _route_context_arbitration_design(holdout, gaps)
    static = _static_anti_overfitting_check()

    _write_pair("progress_stagnation_audit", progress, _progress_md(progress))
    _write_pair("holdout_4_failure_diagnosis", holdout, _holdout_md(holdout))
    _write_pair("remaining_routing_gap_census", gaps, _gaps_md(gaps))
    _write_pair("route_context_arbitration_design", design, _design_md(design))
    _write_pair("latency_lane_reclassification", latency, _latency_md(latency))
    (OUTPUT_DIR / "static_anti_overfitting_check.md").write_text(_static_md(static), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_dir": str(OUTPUT_DIR),
                "progress_rows": len(progress["rows"]),
                "holdout_4_failures": len(holdout["failures"]),
                "remaining_routing_gaps": len(gaps["items"]),
                "latency_rows": len(latency["items"]),
                "static_check": static["status"],
            },
            indent=2,
        )
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_pair(stem: str, payload: dict[str, Any], markdown: str) -> None:
    (OUTPUT_DIR / f"{stem}.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (OUTPUT_DIR / f"{stem}.md").write_text(markdown, encoding="utf-8")


def _progress_stagnation_audit(run_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    by_run = {name: {str(row.get("test_id")): row for row in rows} for name, rows in run_rows.items()}
    ordered_names = list(RUNS)
    all_ids = sorted({test_id for rows in by_run.values() for test_id in rows})
    rows = []
    counts: Counter[str] = Counter()
    generic_failures = []
    missing_context = []
    ambiguity = []
    unsupported = []
    remove_from_scoring = []
    for test_id in all_ids:
        states = []
        categories = []
        routes = []
        for name in ordered_names:
            row = by_run.get(name, {}).get(test_id)
            if row is None:
                states.append("missing")
                categories.append("missing")
                routes.append("missing")
                continue
            states.append("pass" if row.get("passed") else "fail")
            categories.append(str(row.get("failure_category") or "passed"))
            routes.append(str(row.get("actual_route_family") or ""))
        classification = _progress_classification(states, categories)
        counts[classification] += 1
        latest = by_run["post_readiness_3"].get(test_id, {})
        item = {
            "test_id": test_id,
            "prompt": latest.get("prompt") or _first_value(by_run, test_id, "prompt"),
            "expected_route_family": latest.get("expected_route_family") or _first_value(by_run, test_id, "expected_route_family"),
            "latest_actual_route_family": latest.get("actual_route_family"),
            "states_by_run": dict(zip(ordered_names, states, strict=False)),
            "categories_by_run": dict(zip(ordered_names, categories, strict=False)),
            "routes_by_run": dict(zip(ordered_names, routes, strict=False)),
            "classification": classification,
            "failure_reason": latest.get("failure_reason"),
            "known_lane_labels": latest.get("known_lane_labels"),
        }
        rows.append(item)
        if latest.get("actual_route_family") == "generic_provider" and not latest.get("passed"):
            generic_failures.append(item)
        if _missing_context_like(latest):
            missing_context.append(item)
        if _cross_family_like(latest):
            ambiguity.append(item)
        if _unsupported_like(latest):
            unsupported.append(item)
        if _remove_from_normal_routing_scoring(latest):
            remove_from_scoring.append(item)
    return {
        "sources": {name: str(path) for name, path in RUNS.items()},
        "counts": dict(counts),
        "rows": rows,
        "persistent_failures": [row for row in rows if row["classification"] == "failed_every_run"],
        "newly_fixed_rows": [row for row in rows if row["classification"] == "fixed_and_stayed_fixed"],
        "regressions": [row for row in rows if row["classification"] == "fixed_then_regressed"],
        "generic_provider_failures": generic_failures,
        "missing_context_binding_failures": missing_context,
        "cross_family_ambiguity_failures": ambiguity,
        "unsupported_or_corpus_expectation_failures": unsupported,
        "remove_from_normal_routing_scoring_candidates": remove_from_scoring,
    }


def _progress_classification(states: list[str], categories: list[str]) -> str:
    scored = [state for state in states if state != "missing"]
    failed = [state == "fail" for state in scored]
    if all(failed):
        if all(category == "latency_issue" for category in categories if category != "missing"):
            return "latency_only"
        return "failed_every_run"
    if scored and scored[-1] == "pass":
        first_pass = next((index for index, state in enumerate(scored) if state == "pass"), None)
        if first_pass is not None and all(state == "pass" for state in scored[first_pass:]):
            return "fixed_and_stayed_fixed"
    if "pass" in scored and scored[-1] == "fail":
        return "fixed_then_regressed"
    if len(set(category for category in categories if category != "missing")) > 1:
        return "changed_failure_category"
    return "newly_failed_after_stricter_routing" if scored and scored[0] == "pass" else "corpus_or_policy_issue"


def _first_value(by_run: dict[str, dict[str, dict[str, Any]]], test_id: str, key: str) -> Any:
    for rows in by_run.values():
        value = rows.get(test_id, {}).get(key)
        if value not in (None, ""):
            return value
    return ""


def _holdout_4_diagnosis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = []
    for row in rows:
        if row.get("passed"):
            continue
        item = _failure_item(row)
        item.update(
            {
                "provider_called": row.get("provider_called"),
                "openai_called": row.get("openai_called"),
                "llm_called": row.get("llm_called"),
                "embedding_called": row.get("embedding_called"),
                "provider_call_count": row.get("provider_call_count"),
                "openai_call_count": row.get("openai_call_count"),
                "llm_call_count": row.get("llm_call_count"),
                "embedding_call_count": row.get("embedding_call_count"),
                "problem_classification": _holdout_problem(row),
                "root_cause": _root_cause(row),
            }
        )
        failures.append(item)
    return {
        "source": str(HOLDOUT_4),
        "failure_count": len(failures),
        "counts": {
            "by_failure_category": dict(Counter(item["failure_category"] for item in failures)),
            "by_problem_classification": dict(Counter(item["problem_classification"] for item in failures)),
            "by_expected_route_family": dict(Counter(item["expected_route_family"] for item in failures)),
            "by_actual_route_family": dict(Counter(item["actual_route_family"] for item in failures)),
        },
        "failures": failures,
    }


def _remaining_routing_gap_census(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for row in rows:
        if row.get("failure_category") != "real_routing_gap":
            continue
        item = _failure_item(row)
        item["root_cause_group"] = _routing_gap_group(row)
        item["normal_scoring_recommendation"] = (
            "audit_or_exclude_if_feature_map_overexpectation"
            if _remove_from_normal_routing_scoring(row)
            else "score_as_routing_gap"
        )
        items.append(item)
    return {
        "source": str(RUNS["post_readiness_3"]),
        "count": len(items),
        "counts": {
            "by_root_cause_group": dict(Counter(item["root_cause_group"] for item in items)),
            "by_expected_route_family": dict(Counter(item["expected_route_family"] for item in items)),
            "by_actual_route_family": dict(Counter(item["actual_route_family"] for item in items)),
        },
        "items": items,
    }


def _latency_lane_reclassification(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for row in rows:
        if row.get("failure_category") != "latency_issue":
            continue
        classification = _latency_classification(row)
        items.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt"),
                "route_family": row.get("actual_route_family"),
                "total_latency_ms": row.get("total_latency_ms") or row.get("latency_ms"),
                "route_handler_ms": row.get("route_handler_ms"),
                "memory_context_ms": row.get("memory_context_ms"),
                "response_serialization_ms": row.get("response_serialization_ms"),
                "unattributed_latency_ms": row.get("unattributed_latency_ms"),
                "response_json_bytes": row.get("response_json_bytes"),
                "workspace_item_count": row.get("workspace_item_count"),
                "known_lane_labels": row.get("known_lane_labels"),
                "hard_timeout_status": row.get("status") == "hard_timeout",
                "classification": classification,
            }
        )
    by_class = defaultdict(list)
    for item in items:
        by_class[item["classification"]].append(float(item.get("total_latency_ms") or 0.0))
    summaries = {
        key: {
            "count": len(values),
            "min": min(values) if values else 0,
            "median": median(values) if values else 0,
            "max": max(values) if values else 0,
        }
        for key, values in sorted(by_class.items())
    }
    return {
        "source": str(RUNS["post_readiness_3"]),
        "count": len(items),
        "classification_counts": dict(Counter(item["classification"] for item in items)),
        "classification_latency_summary": summaries,
        "items": items,
    }


def _route_context_arbitration_design(holdout: dict[str, Any], gaps: dict[str, Any]) -> dict[str, Any]:
    clusters = [
        {
            "cluster_id": "RCA-001",
            "name": "calculation follow-up and noisy direct math",
            "evidence": ["holdout4 calculation positives/follow-ups", "post-readiness-3 calculations ambiguous row"],
            "intended_owner": "calculations",
            "missing_context_behavior": "route to calculations with needs_clarification/blocked_missing_context",
            "overcapture_risk": "conceptual math or app Calculator prompts must not become calculations",
        },
        {
            "cluster_id": "RCA-002",
            "name": "deictic open/read selected/browser/file targets",
            "evidence": ["browser/app/open deictic failures", "file/context selected target failures"],
            "intended_owner": "browser_destination, file, or context_action based on compatible context source",
            "missing_context_behavior": "native clarification naming the missing URL/file/selection",
            "overcapture_risk": "open app commands and conceptual web/design requests must remain outside browser/file routes",
        },
        {
            "cluster_id": "RCA-003",
            "name": "visible UI/screen action grounding",
            "evidence": ["click that one", "press submit holdout pressure"],
            "intended_owner": "screen_awareness",
            "missing_context_behavior": "native clarification/blocked grounding, no blind click execution",
            "overcapture_risk": "conceptual button/design wording must stay generic",
        },
        {
            "cluster_id": "RCA-004",
            "name": "approval/trust and software lifecycle boundary",
            "evidence": ["approve it", "approve trusted hook", "remove Slack from this machine"],
            "intended_owner": "trust_approvals or software_control",
            "missing_context_behavior": "trust clarifies missing active approval; software lifecycle prepares dry-run/approval plan",
            "overcapture_risk": "delete/remove files must remain guardrailed",
        },
        {
            "cluster_id": "RCA-005",
            "name": "system/watch/status versus app open",
            "evidence": ["open or diagnose wifi status", "what did I miss while I was away"],
            "intended_owner": "network or watch_runtime",
            "missing_context_behavior": "status routes should return bounded status/summary, not app launch",
            "overcapture_risk": "conceptual network or activity-writing prompts must remain generic",
        },
    ]
    return {
        "inputs": {
            "holdout_4_failure_count": holdout.get("failure_count"),
            "remaining_250_routing_gap_count": gaps.get("count"),
        },
        "typed_result": {
            "context_available": "bool",
            "context_type": "selection | clipboard | recent_entity | active_request | recent_result | visible_screen | none",
            "context_source": "active_context | active_request_state | recent_tool_results | screen_state | none",
            "freshness": "current | recent | cooling | stale | ambiguous | missing",
            "ambiguity": "none | multiple_candidates | stale_candidate | incompatible_context",
            "candidate_bindings": "list[RouteBinding]",
            "selected_binding": "RouteBinding | null",
            "missing_preconditions": "list[str]",
            "route_family_owners": "list[str]",
            "clarification_recommended": "bool",
            "clarification_text": "str",
            "generic_provider_allowed": "bool",
            "reason": "str",
        },
        "laws": [
            "If a native route owns the intent but context is missing, route native and clarify.",
            "If context is stale or ambiguous, route native and ask for clarification.",
            "If a phrase is conceptual and no native action target exists, do not overcapture.",
            "If multiple route families could own a phrase, use context-source compatibility to arbitrate.",
            "generic_provider may win only when no native route meaningfully owns the request.",
            "Provider/OpenAI/LLM calls remain disabled in command-eval mode.",
        ],
        "clusters": clusters,
        "implementation_shape": [
            "Add a small RouteContextArbitrator model that derives context candidates and ownership posture.",
            "Use it from DeterministicPlanner before generic fallback and before broad app/open matching.",
            "Convert owned missing-context cases into typed SemanticParseProposal clarifications.",
            "Expose arbitration payload in route_state via semantic slots and route candidate metadata.",
        ],
    }


def _static_anti_overfitting_check() -> dict[str, Any]:
    product_paths = [
        "src/stormhelm/core/orchestrator",
        "src/stormhelm/core/calculations",
        "src/stormhelm/core/screen_awareness",
        "src/stormhelm/core/software_control",
    ]
    suspicious = [
        "holdout4_",
        "holdout5_",
        "context_arbitration_exact_",
        "context_arbitration_holdout_",
    ]
    hits = []
    for root in product_paths:
        path = Path(root)
        if not path.exists():
            continue
        for file_path in path.rglob("*.py"):
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            for needle in suspicious:
                if needle in text:
                    hits.append({"path": str(file_path), "needle": needle})
    status = "passed" if not hits else "failed"
    return {"status": status, "hits": hits, "searched_paths": product_paths, "forbidden_needles": suspicious}


def _failure_item(row: dict[str, Any]) -> dict[str, Any]:
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
        "route_candidates": row.get("route_candidates"),
        "route_scores": row.get("route_scores"),
        "fallback_reason": row.get("fallback_reason"),
        "generic_provider_eligible": row.get("generic_provider_eligible"),
        "generic_provider_selected_reason": row.get("generic_provider_selected_reason"),
        "deictic_binding_summary": row.get("deictic_binding_summary"),
        "provider_called": row.get("provider_called"),
        "openai_called": row.get("openai_called"),
        "llm_called": row.get("llm_called"),
        "embedding_called": row.get("embedding_called"),
    }


def _holdout_problem(row: dict[str, Any]) -> str:
    prompt = str(row.get("prompt") or "").lower()
    expected = str(row.get("expected_route_family") or "")
    actual = str(row.get("actual_route_family") or "")
    reason = str(row.get("failure_reason") or "").lower()
    if actual == "generic_provider" and "clarification: expected" in reason:
        return "missing-context clarification failure"
    if actual == "generic_provider":
        return "wrong generic fallback"
    if "response_meaning" in reason or "approval:" in reason:
        return "response/corpus policy mismatch"
    if actual != expected:
        return "cross-family arbitration failure"
    if "that" in prompt or "it" in prompt or "this" in prompt:
        return "deictic/follow-up binding failure"
    return "undercapture"


def _root_cause(row: dict[str, Any]) -> str:
    prompt = str(row.get("prompt") or "").lower()
    expected = str(row.get("expected_route_family") or "")
    actual = str(row.get("actual_route_family") or "")
    if expected == "calculations":
        if any(token in prompt for token in ("that", "same", "redo", "answer")):
            return "calculation follow-up binding missing or underpowered"
        return "calculation direct-expression extraction gap"
    if actual == "generic_provider" and any(token in prompt for token in ("this", "that", "it", "highlighted", "selected")):
        return "native route owns deictic intent but no native clarification proposal was emitted"
    if expected in {"discord_relay", "trust_approvals"}:
        return "approval/relay missing-context route should clarify natively"
    if expected in {"file", "context_action", "browser_destination"}:
        return "context-source compatibility missing for selected/recent target"
    if expected in {"network", "watch_runtime"}:
        return "status/watch route lost to app/generic route"
    return "route-family ownership gap"


def _routing_gap_group(row: dict[str, Any]) -> str:
    expected = str(row.get("expected_route_family") or "")
    prompt = str(row.get("prompt") or "").lower()
    tags = set(str(tag) for tag in (row.get("case") or {}).get("tags") or [])
    if expected == "calculations":
        return "calculation/follow-up/deictic"
    if expected in {"browser_destination", "file"}:
        return "browser/app/open deictic"
    if expected in {"context_action", "desktop_search"}:
        return "file/context selected target"
    if expected == "screen_awareness":
        return "screen-awareness missing grounding"
    if expected in {"workflow", "routine", "task_continuity"}:
        return "workflow/routine/task continuity follow-ups"
    if expected in {"network", "watch_runtime", "machine", "power", "resources", "storage", "time", "weather", "location"}:
        return "system/watch/status"
    if expected == "discord_relay":
        return "Discord/relay/context send"
    if expected in {"software_control", "app_control", "window_control"}:
        return "software/app lifecycle boundary"
    if "unsupported" in tags or expected == "unsupported":
        return "unsupported expected route"
    if "feature_map_overexpectation" == row.get("failure_category"):
        return "routeability/feature-map mismatch"
    if any(token in prompt for token in {"this", "that", "it"}):
        return "other deictic"
    return "other"


def _latency_classification(row: dict[str, Any]) -> str:
    labels = set(row.get("known_lane_labels") or [])
    route = str(row.get("actual_route_family") or "")
    if "known_workspace_latency_lane" in labels or route == "workspace_operations":
        return "known_workspace_latency_lane"
    if route in {"file_operation", "maintenance", "routine", "software_recovery", "workflow"}:
        return "known_bounded_latency_lane"
    if float(row.get("unattributed_latency_ms") or 0) > 2000:
        return "unknown_latency_issue"
    return "product_latency_bug"


def _missing_context_like(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            row.get("prompt"),
            row.get("failure_reason"),
            row.get("fallback_reason"),
            row.get("generic_provider_selected_reason"),
        )
    ).lower()
    return any(token in text for token in ("this", "that", "it", "before", "selected", "highlighted", "context"))


def _cross_family_like(row: dict[str, Any]) -> bool:
    return bool(
        not row.get("passed")
        and row.get("actual_route_family")
        and row.get("expected_route_family")
        and row.get("actual_route_family") not in {row.get("expected_route_family"), "generic_provider"}
    )


def _unsupported_like(row: dict[str, Any]) -> bool:
    tags = {str(tag) for tag in (row.get("case") or {}).get("tags") or []}
    return "unsupported" in tags or row.get("expected_route_family") == "unsupported" or row.get("failure_category") in {
        "feature_map_overexpectation",
        "unsupported_feature_expected",
        "corpus_expectation_bug",
    }


def _remove_from_normal_routing_scoring(row: dict[str, Any]) -> bool:
    return _unsupported_like(row) or str(row.get("expected_route_family") or "") in {"development", "terminal"}


def _progress_md(payload: dict[str, Any]) -> str:
    lines = ["# Progress And Stagnation Audit", "", f"Rows audited: {len(payload['rows'])}", "", "## Counts"]
    for key, value in sorted(payload["counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Persistent Failures",
            *_table(payload["persistent_failures"][:40], ["test_id", "expected_route_family", "latest_actual_route_family", "classification"]),
            "",
            "## Regressions",
            *_table(payload["regressions"][:40], ["test_id", "expected_route_family", "latest_actual_route_family", "classification"]),
            "",
            "## Remove From Normal Routing Scoring Candidates",
            *_table(
                payload["remove_from_normal_routing_scoring_candidates"][:40],
                ["test_id", "expected_route_family", "latest_actual_route_family", "classification"],
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _holdout_md(payload: dict[str, Any]) -> str:
    lines = ["# Holdout-4 Failure Diagnosis", "", f"Failures: {payload['failure_count']}", "", "## Counts"]
    for group, counts in payload["counts"].items():
        lines.append(f"### {group}")
        for key, value in sorted(counts.items()):
            lines.append(f"- {key}: {value}")
    lines.extend(["", "## Failures", *_table(payload["failures"], ["test_id", "expected_route_family", "actual_route_family", "problem_classification", "root_cause"])])
    return "\n".join(lines) + "\n"


def _gaps_md(payload: dict[str, Any]) -> str:
    lines = ["# Remaining Routing Gap Census", "", f"Remaining real routing gaps: {payload['count']}", "", "## By Root Cause Group"]
    for key, value in sorted(payload["counts"]["by_root_cause_group"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Items", *_table(payload["items"], ["test_id", "expected_route_family", "actual_route_family", "root_cause_group", "normal_scoring_recommendation"])])
    return "\n".join(lines) + "\n"


def _design_md(payload: dict[str, Any]) -> str:
    lines = ["# Route Context Arbitration Design", "", "## Typed Result"]
    for key, value in payload["typed_result"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Laws"])
    lines.extend(f"- {law}" for law in payload["laws"])
    lines.extend(["", "## Clusters"])
    for cluster in payload["clusters"]:
        lines.append(f"- {cluster['cluster_id']}: {cluster['name']} -> {cluster['intended_owner']}")
    lines.extend(["", "## Implementation Shape"])
    lines.extend(f"- {item}" for item in payload["implementation_shape"])
    return "\n".join(lines) + "\n"


def _latency_md(payload: dict[str, Any]) -> str:
    lines = ["# Latency Lane Reclassification", "", f"Latency rows: {payload['count']}", "", "## Classification Counts"]
    for key, value in sorted(payload["classification_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Items", *_table(payload["items"], ["test_id", "route_family", "total_latency_ms", "classification"])])
    return "\n".join(lines) + "\n"


def _static_md(payload: dict[str, Any]) -> str:
    lines = ["# Static Anti-Overfitting Check", "", f"Status: {payload['status']}", "", "## Forbidden Needles"]
    lines.extend(f"- {needle}" for needle in payload["forbidden_needles"])
    if payload["hits"]:
        lines.extend(["", "## Hits", *_table(payload["hits"], ["path", "needle"])])
    else:
        lines.append("\nNo exact holdout/test-id routing logic hits were found.")
    return "\n".join(lines) + "\n"


def _table(rows: list[dict[str, Any]], fields: list[str]) -> list[str]:
    if not rows:
        return ["No rows."]
    output = ["|" + "|".join(fields) + "|", "|" + "|".join("---" for _ in fields) + "|"]
    for row in rows:
        output.append("|" + "|".join(_cell(row.get(field)) for field in fields) + "|")
    return output


def _cell(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    return text.replace("|", "\\|").replace("\n", " ")[:220]


if __name__ == "__main__":
    main()
