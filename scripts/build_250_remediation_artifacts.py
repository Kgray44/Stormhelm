from __future__ import annotations

import json
import subprocess
from collections import Counter
from collections import defaultdict
from pathlib import Path
from typing import Any


ORIGINAL_DIR = Path(".artifacts") / "command-usability-eval" / "250-checkpoint"
OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "250-remediation"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _read_jsonl(ORIGINAL_DIR / "250_results.jsonl")
    feature_audit = _read_json(ORIGINAL_DIR / "feature_map_audit.json")
    cluster_payload = _failure_clusters(rows)
    routeability_payload = _routeability_audit(rows, feature_audit)
    wrong_payload = _wrong_subsystem_audit(rows)
    latency_payload = _latency_lane_audit(rows)
    plan_payload = _remediation_plan(cluster_payload["clusters"])
    anti_overfit_payload = _anti_overfitting_protocol()
    static_payload = _static_hardcoding_check(rows)

    _write_json(OUTPUT_DIR / "250_failure_cluster_census.json", cluster_payload)
    (OUTPUT_DIR / "250_failure_cluster_census.md").write_text(_cluster_markdown(cluster_payload), encoding="utf-8")
    _write_json(OUTPUT_DIR / "250_remediation_plan.json", plan_payload)
    (OUTPUT_DIR / "250_remediation_plan.md").write_text(_plan_markdown(plan_payload), encoding="utf-8")
    _write_json(OUTPUT_DIR / "250_routeability_audit.json", routeability_payload)
    (OUTPUT_DIR / "250_routeability_audit.md").write_text(_routeability_markdown(routeability_payload), encoding="utf-8")
    _write_json(OUTPUT_DIR / "250_wrong_subsystem_audit.json", wrong_payload)
    (OUTPUT_DIR / "250_wrong_subsystem_audit.md").write_text(_wrong_markdown(wrong_payload), encoding="utf-8")
    _write_json(OUTPUT_DIR / "250_latency_lane_audit.json", latency_payload)
    (OUTPUT_DIR / "250_latency_lane_audit.md").write_text(_latency_markdown(latency_payload), encoding="utf-8")
    _write_json(OUTPUT_DIR / "250_anti_overfitting_protocol.json", anti_overfit_payload)
    (OUTPUT_DIR / "250_anti_overfitting_protocol.md").write_text(_anti_overfit_markdown(anti_overfit_payload), encoding="utf-8")
    _write_json(OUTPUT_DIR / "250_static_anti_hardcoding_check.json", static_payload)
    (OUTPUT_DIR / "250_static_anti_hardcoding_check.md").write_text(_static_markdown(static_payload), encoding="utf-8")

    print(json.dumps({"output_dir": str(OUTPUT_DIR), "clusters": len(cluster_payload["clusters"])}, indent=2))


def _failure_clusters(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [row for row in rows if not row.get("passed") and row.get("score_in_pass_fail", True)]
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in failed:
        classification = _cluster_classification(row)
        fallback = str(row.get("fallback_reason") or row.get("generic_provider_selected_reason") or "")
        fallback_group = "generic_provider_fallback" if "generic_provider" in fallback or "no_native_route_family" in fallback else fallback
        key = (
            row.get("expected_route_family"),
            row.get("actual_route_family"),
            row.get("expected_subsystem"),
            row.get("actual_subsystem"),
            tuple(row.get("expected_tool") or []),
            tuple(row.get("actual_tool") or []),
            row.get("failure_category"),
            classification,
            fallback_group,
        )
        grouped[key].append(row)
    clusters: list[dict[str, Any]] = []
    for index, (key, items) in enumerate(sorted(grouped.items(), key=lambda pair: (-len(pair[1]), str(pair[0]))), 1):
        sample = items[0]
        classification = _cluster_classification(sample)
        clusters.append(
            {
                "cluster_id": f"C{index:03d}",
                "failure_count": len(items),
                "expected_route_family": key[0],
                "actual_route_family": key[1],
                "expected_subsystem": key[2],
                "actual_subsystem": key[3],
                "expected_tool": list(key[4]),
                "actual_tool": list(key[5]),
                "wording_style_counts": dict(Counter(str(row.get("wording_style") or "") for row in items)),
                "failure_category": key[6],
                "cluster_classification": key[7],
                "fallback_reason": key[8],
                "route_candidates": sample.get("route_candidates"),
                "route_scores": sample.get("route_scores"),
                "likely_fix_area": _likely_fix_area(sample, classification),
                "representative_test_ids": [str(row.get("test_id")) for row in items[:8]],
                "representative_prompts": [str(row.get("prompt") or row.get("input")) for row in items[:5]],
                "rows": [_row_brief(row) for row in items],
            }
        )
    return {
        "source": str(ORIGINAL_DIR / "250_results.jsonl"),
        "total_scored_failures": len(failed),
        "failure_category_counts": dict(Counter(row.get("failure_category") for row in failed)),
        "by_expected_family": dict(Counter(row.get("expected_route_family") for row in failed)),
        "clusters": clusters,
    }


def _routeability_audit(rows: list[dict[str, Any]], feature_audit: dict[str, Any]) -> dict[str, Any]:
    route_families = feature_audit.get("route_families") if isinstance(feature_audit.get("route_families"), dict) else {}
    involved = sorted(
        {
            str(row.get("expected_route_family") or "")
            for row in rows
            if not row.get("passed") and row.get("failure_category") in {"real_routing_gap", "wrong_subsystem"}
        }
        - {""}
    )
    items: list[dict[str, Any]] = []
    for family in involved:
        evidence = dict(route_families.get(family) or {})
        classification = evidence.get("classification") or _fallback_classification(family)
        items.append(
            {
                "family": family,
                "classification": classification,
                "evidence_file_path": evidence.get("evidence_path") or "not_found_in_feature_audit",
                "route_entrypoint": evidence.get("route_entrypoint") or "",
                "reachable_through_chat_send": bool(evidence.get("reachable_through_chat_send", classification != "docs_only")),
                "dry_run_execution_can_validate": bool(evidence.get("dry_run_validates", classification in {"implemented_routeable", "implemented_direct_only"})),
                "should_be_scored_in_250": bool(evidence.get("include_in_scoring", classification in {"implemented_routeable", "implemented_direct_only"})),
                "generic_provider_fallback_acceptable_for_native_prompt": classification not in {"implemented_routeable", "implemented_direct_only"},
                "scoring_note": evidence.get("scoring_note") or "",
            }
        )
    return {
        "families": items,
        "classification_counts": dict(Counter(item["classification"] for item in items)),
    }


def _wrong_subsystem_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wrong = [row for row in rows if row.get("failure_category") == "wrong_subsystem"]
    items: list[dict[str, Any]] = []
    for row in wrong:
        expected = str(row.get("expected_route_family") or "")
        actual = str(row.get("actual_route_family") or "")
        if expected == "resources" and actual == "resource":
            root_cause = "resource route family was not canonicalized to resources and subsystem label was blank"
            classification = "subsystem-label normalization bug"
            decision = "fixed by canonicalizing resource -> resources"
        elif expected == "window_control" and actual == "screen_awareness":
            root_cause = "screen awareness over-owned open-window status prompts before window_status candidate generation won"
            classification = "true route bug"
            decision = "fixed by adding native window_status ownership and narrowing screen-awareness capture"
        elif actual == "screen_awareness":
            root_cause = "screen-awareness candidate overcaptured a cross-family/wrapped prompt"
            classification = "route taxonomy mismatch"
            decision = "partially fixed through wrapper normalization and screen-awareness near-miss guard; validate in rerun"
        else:
            root_cause = "requires post-remediation rerun validation"
            classification = "unknown wrong-subsystem row"
            decision = "defer unless reproduced"
        items.append(
            {
                **_row_brief(row),
                "route_candidates": row.get("route_candidates"),
                "route_scores": row.get("route_scores"),
                "selected_handler": row.get("selected_handler") or "",
                "subsystem_label_source": "planner/tool observation",
                "normalized_subsystem_label": row.get("expected_subsystem") if classification == "subsystem-label normalization bug" else row.get("actual_subsystem"),
                "root_cause": root_cause,
                "classification": classification,
                "fix_or_defer_decision": decision,
            }
        )
    return {"count": len(items), "items": items}


def _latency_lane_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latency = [row for row in rows if row.get("failure_category") == "latency_issue"]
    items: list[dict[str, Any]] = []
    for row in latency:
        labels = row.get("known_lane_labels") or []
        family = str(row.get("actual_route_family") or row.get("expected_route_family") or "")
        if "known_workspace_latency_lane" in labels or family in {"workspace_operations", "task_continuity"}:
            classification = "known_workspace_latency_lane"
            decision = "quarantine as bounded workspace latency lane if post-rerun stays payload-safe and under hard timeout"
        elif float(row.get("unattributed_latency_ms") or 0) > 3000:
            classification = "unknown_latency_issue"
            decision = "needs lifecycle attribution; no broad latency fix in this routing pass"
        else:
            classification = "product_latency_bug"
            decision = "inspect route handler and runtime overhead after routing pass"
        items.append(
            {
                **_row_brief(row),
                "route_family": family,
                "total_latency_ms": row.get("total_latency_ms"),
                "latency_ms": row.get("latency_ms"),
                "route_handler_ms": row.get("route_handler_ms"),
                "memory_context_ms": row.get("memory_context_ms"),
                "response_serialization_ms": row.get("response_serialization_ms"),
                "unattributed_latency_ms": row.get("unattributed_latency_ms"),
                "response_json_bytes": row.get("response_json_bytes"),
                "workspace_item_count": row.get("workspace_item_count"),
                "hard_timeout_status": row.get("status") == "hard_timeout",
                "known_lane_labels": labels,
                "classification": classification,
                "decision": decision,
            }
        )
    return {
        "count": len(items),
        "classification_counts": dict(Counter(item["classification"] for item in items)),
        "items": items,
    }


def _remediation_plan(clusters: list[dict[str, Any]]) -> dict[str, Any]:
    plan: list[dict[str, Any]] = []
    for cluster in clusters:
        classification = cluster["cluster_classification"]
        should_fix = classification in {
            "route_ownership_gap",
            "generic_provider_gate_too_eager",
            "native_candidate_missing",
            "native_candidate_declined_wrongly",
            "wrong_subsystem_label",
            "wrong_subsystem_route",
            "missing_context_should_clarify",
        } and cluster["failure_count"] >= 2
        if classification in {"deictic_binding_failure", "followup_binding_failure", "known_workspace_latency_lane", "unknown_latency_issue"}:
            should_fix = False
        plan.append(
            {
                "cluster_id": cluster["cluster_id"],
                "failure_count": cluster["failure_count"],
                "classification": classification,
                "representative_test_ids": cluster["representative_test_ids"],
                "representative_prompts": cluster["representative_prompts"],
                "expected_route_subsystem_tool": {
                    "route_family": cluster["expected_route_family"],
                    "subsystem": cluster["expected_subsystem"],
                    "tool": cluster["expected_tool"],
                },
                "actual_route_subsystem_tool": {
                    "route_family": cluster["actual_route_family"],
                    "subsystem": cluster["actual_subsystem"],
                    "tool": cluster["actual_tool"],
                },
                "likely_fix": _fix_text(cluster),
                "risk_of_overcapture": _overcapture_risk(cluster),
                "near_miss_tests_required": _near_miss_tests(cluster),
                "fix_now_or_defer": "fix_now" if should_fix else "defer_or_quarantine",
            }
        )
    return {"plan": plan}


def _anti_overfitting_protocol() -> dict[str, Any]:
    return {
        "rules": [
            "Original 250 failed prompts are repro examples, not proof of a generalized fix.",
            "Each repaired cluster must define a bug pattern before code is changed.",
            "Each repaired cluster must have exact repro, unseen positive, near-miss negative, and ambiguous/missing-context coverage.",
            "Exact prompt strings may appear in tests/artifacts only, not product routing logic.",
            "A static source-diff check searches added product lines for exact test ids and original prompt strings.",
            "A holdout process-isolated suite runs after fixes, and holdout failures are not patched in this pass.",
        ],
        "repaired_cluster_patterns": [
            "operator_wrapper_normalization",
            "status_route_ownership",
            "system_control_enablement",
            "unsupported_external_commitment_decline",
            "wrong_subsystem_label_normalization",
            "screen_awareness_overcapture_guard",
        ],
        "required_rate_sections": [
            "exact_250_repro_pass_rate",
            "unseen_variant_pass_rate",
            "near_miss_preservation_rate",
            "ambiguity_or_missing_context_correctness",
            "full_250_rerun_pass_rate",
            "holdout_pass_rate",
        ],
    }


def _static_hardcoding_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = {str(row.get("prompt") or row.get("input") or "").strip().lower() for row in rows if row.get("prompt") or row.get("input")}
    test_ids = {str(row.get("test_id") or "").strip().lower() for row in rows if row.get("test_id")}
    try:
        diff = subprocess.run(
            ["git", "diff", "--unified=0", "--", "src/stormhelm"],
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
            check=False,
        ).stdout
    except Exception as exc:  # pragma: no cover - diagnostic only
        return {"status": "error", "error": str(exc), "exact_prompt_hits": [], "test_id_hits": []}
    added_lines = [
        line[1:].strip()
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    prompt_hits = []
    test_id_hits = []
    for line in added_lines:
        lowered = line.lower()
        for prompt in prompts:
            if prompt and len(prompt) >= 18 and prompt in lowered:
                prompt_hits.append({"prompt": prompt, "line": line})
        for test_id in test_ids:
            if test_id and test_id in lowered:
                test_id_hits.append({"test_id": test_id, "line": line})
    return {
        "status": "passed" if not prompt_hits and not test_id_hits else "needs_review",
        "scope": "added product source lines from git diff -- src/stormhelm",
        "added_line_count": len(added_lines),
        "exact_prompt_hits": prompt_hits,
        "test_id_hits": test_id_hits,
    }


def _cluster_classification(row: dict[str, Any]) -> str:
    category = row.get("failure_category")
    expected = str(row.get("expected_route_family") or "")
    actual = str(row.get("actual_route_family") or "")
    style = str(row.get("wording_style") or "")
    fallback = str(row.get("fallback_reason") or row.get("generic_provider_selected_reason") or "")
    if category == "latency_issue":
        if "known_workspace_latency_lane" in (row.get("known_lane_labels") or []) or expected in {"workspace_operations", "task_continuity"} or actual in {"workspace_operations", "task_continuity"}:
            return "known_workspace_latency_lane"
        return "unknown_latency_issue"
    if category == "wrong_subsystem":
        if expected == "resources" and actual == "resource":
            return "wrong_subsystem_label"
        return "wrong_subsystem_route"
    if style == "deictic":
        return "deictic_binding_failure"
    if style == "follow_up":
        return "followup_binding_failure"
    if actual == "generic_provider":
        if "no_native_route_family" in fallback:
            return "generic_provider_gate_too_eager"
        return "native_candidate_missing"
    if expected == actual:
        return "native_candidate_declined_wrongly"
    return "route_ownership_gap"


def _likely_fix_area(row: dict[str, Any], classification: str) -> str:
    if classification in {"generic_provider_gate_too_eager", "native_candidate_missing", "route_ownership_gap"}:
        return "planner route-family ownership and candidate generation"
    if classification in {"wrong_subsystem_label", "wrong_subsystem_route"}:
        return "subsystem label normalization or route ownership precedence"
    if classification in {"deictic_binding_failure", "followup_binding_failure"}:
        return "context/deictic/follow-up binding"
    if "latency" in classification:
        return "runtime latency attribution and route-family budget"
    return "route handler or expectation audit"


def _fix_text(cluster: dict[str, Any]) -> str:
    classification = cluster["cluster_classification"]
    expected = cluster["expected_route_family"]
    if classification in {"generic_provider_gate_too_eager", "native_candidate_missing", "route_ownership_gap"}:
        return f"add generalized {expected} ownership rules and keep generic_provider eligible only after native candidates decline"
    if classification == "native_candidate_declined_wrongly":
        return f"fix {expected} tool availability, target extraction, or native handler preconditions"
    if classification == "wrong_subsystem_label":
        return "normalize internal route-family aliases to the scored route taxonomy"
    if classification == "wrong_subsystem_route":
        return "adjust candidate precedence and near-miss guards so the correct native route wins"
    if classification in {"deictic_binding_failure", "followup_binding_failure"}:
        return "defer to a dedicated binding pass with active context/session fixtures"
    if "latency" in classification:
        return "audit and quarantine/fix latency separately from routing quality"
    return "defer pending routeability evidence"


def _overcapture_risk(cluster: dict[str, Any]) -> str:
    family = cluster["expected_route_family"]
    styles = set((cluster.get("wording_style_counts") or {}).keys())
    if family in {"browser_destination", "app_control", "window_control", "network", "unsupported"}:
        return "medium; require semantic near-misses that mention route keywords without command intent"
    if styles & {"deictic", "follow_up", "ambiguous"}:
        return "high; missing context must clarify rather than route confidently"
    return "low-to-medium"


def _near_miss_tests(cluster: dict[str, Any]) -> list[str]:
    family = cluster["expected_route_family"]
    examples = {
        "browser_destination": ["explain what a browser is", "almost open youtube but not exactly"],
        "app_control": ["what apps should I build", "explain application windows"],
        "window_control": ["what is a window function in SQL", "which window pattern should I use in code"],
        "network": ["explain network effects", "online payments overview"],
        "unsupported": ["compare flight prices", "hotel booking checklist"],
    }
    return examples.get(str(family), ["ambiguous request without actionable native intent"])


def _row_brief(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "prompt": row.get("prompt") or row.get("input"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "expected_subsystem": row.get("expected_subsystem"),
        "actual_subsystem": row.get("actual_subsystem"),
        "expected_tool": row.get("expected_tool"),
        "actual_tool": row.get("actual_tool"),
        "result_state": row.get("result_state") or row.get("actual_result_state"),
        "failure_category": row.get("failure_category"),
        "failure_reason": row.get("failure_reason"),
        "latency_ms": row.get("latency_ms"),
        "response_json_bytes": row.get("response_json_bytes"),
    }


def _fallback_classification(family: str) -> str:
    if family in {"time", "notes", "terminal", "development"}:
        return "implemented_direct_only"
    if family in {"trusted_hook_register"}:
        return "scaffold_only"
    return "implemented_routeable"


def _cluster_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 250 Failure Cluster Census",
        "",
        f"- Source: {payload['source']}",
        f"- Total scored failures: {payload['total_scored_failures']}",
        f"- Failure category counts: {payload['failure_category_counts']}",
        "",
        "| cluster | count | class | expected | actual | styles | fallback | examples |",
        "| --- | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for cluster in payload["clusters"]:
        examples = "<br>".join(cluster["representative_test_ids"][:4])
        lines.append(
            f"| {cluster['cluster_id']} | {cluster['failure_count']} | {cluster['cluster_classification']} | "
            f"{cluster['expected_route_family']}/{cluster['expected_subsystem']}/{cluster['expected_tool']} | "
            f"{cluster['actual_route_family']}/{cluster['actual_subsystem']}/{cluster['actual_tool']} | "
            f"{cluster['wording_style_counts']} | {cluster['fallback_reason']} | {examples} |"
        )
    return "\n".join(lines) + "\n"


def _plan_markdown(payload: dict[str, Any]) -> str:
    lines = ["# 250 Remediation Plan", "", "| cluster | count | decision | likely fix | overcapture risk |", "| --- | ---: | --- | --- | --- |"]
    for item in payload["plan"]:
        lines.append(f"| {item['cluster_id']} | {item['failure_count']} | {item['fix_now_or_defer']} | {item['likely_fix']} | {item['risk_of_overcapture']} |")
    return "\n".join(lines) + "\n"


def _routeability_markdown(payload: dict[str, Any]) -> str:
    lines = ["# 250 Routeability Audit", "", f"- Classification counts: {payload['classification_counts']}", "", "| family | classification | reachable / dry-run / scored | generic fallback acceptable | evidence |", "| --- | --- | --- | --- | --- |"]
    for item in payload["families"]:
        lines.append(
            f"| {item['family']} | {item['classification']} | "
            f"{item['reachable_through_chat_send']} / {item['dry_run_execution_can_validate']} / {item['should_be_scored_in_250']} | "
            f"{item['generic_provider_fallback_acceptable_for_native_prompt']} | {item['evidence_file_path']} |"
        )
    return "\n".join(lines) + "\n"


def _wrong_markdown(payload: dict[str, Any]) -> str:
    lines = ["# 250 Wrong-Subsystem Audit", "", f"- Count: {payload['count']}", "", "| test_id | expected | actual | classification | decision |", "| --- | --- | --- | --- | --- |"]
    for item in payload["items"]:
        lines.append(
            f"| {item['test_id']} | {item['expected_route_family']}/{item['expected_subsystem']}/{item['expected_tool']} | "
            f"{item['actual_route_family']}/{item['actual_subsystem']}/{item['actual_tool']} | {item['classification']} | {item['fix_or_defer_decision']} |"
        )
    return "\n".join(lines) + "\n"


def _latency_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 250 Latency Lane Audit",
        "",
        f"- Count: {payload['count']}",
        f"- Classification counts: {payload['classification_counts']}",
        "",
        "| test_id | route | total ms | route handler | unattributed | payload | classification | decision |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for item in payload["items"]:
        lines.append(
            f"| {item['test_id']} | {item['route_family']} | {item['total_latency_ms']} | {item['route_handler_ms']} | "
            f"{item['unattributed_latency_ms']} | {item['response_json_bytes']} | {item['classification']} | {item['decision']} |"
        )
    return "\n".join(lines) + "\n"


def _anti_overfit_markdown(payload: dict[str, Any]) -> str:
    lines = ["# 250 Anti-Overfitting Protocol", "", "## Rules"]
    lines.extend(f"- {rule}" for rule in payload["rules"])
    lines.extend(["", "## Repaired Cluster Patterns"])
    lines.extend(f"- {item}" for item in payload["repaired_cluster_patterns"])
    lines.extend(["", "## Required Final Rate Sections"])
    lines.extend(f"- {item}" for item in payload["required_rate_sections"])
    return "\n".join(lines) + "\n"


def _static_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 250 Static Anti-Hardcoding Check",
        "",
        f"- Status: {payload.get('status')}",
        f"- Scope: {payload.get('scope')}",
        f"- Added product source line count: {payload.get('added_line_count')}",
        f"- Exact prompt hits: {len(payload.get('exact_prompt_hits') or [])}",
        f"- Test id hits: {len(payload.get('test_id_hits') or [])}",
    ]
    if payload.get("exact_prompt_hits"):
        lines.extend(["", "## Exact Prompt Hits"])
        for item in payload["exact_prompt_hits"]:
            lines.append(f"- `{item['prompt']}` in `{item['line']}`")
    if payload.get("test_id_hits"):
        lines.extend(["", "## Test ID Hits"])
        for item in payload["test_id_hits"]:
            lines.append(f"- `{item['test_id']}` in `{item['line']}`")
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
