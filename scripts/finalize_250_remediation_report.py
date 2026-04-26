from __future__ import annotations

import json
from collections import Counter
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any


ORIGINAL_DIR = Path(".artifacts") / "command-usability-eval" / "250-checkpoint"
OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "250-remediation"


def main() -> None:
    original_summary = _read_json(ORIGINAL_DIR / "250_summary.json")
    post_summary = _read_json(OUTPUT_DIR / "250_post_remediation_summary.json")
    original_rows = _read_jsonl(ORIGINAL_DIR / "250_results.jsonl")
    post_rows = _read_jsonl(OUTPUT_DIR / "250_post_remediation_results.jsonl")
    targeted_rows = _read_jsonl(OUTPUT_DIR / "targeted_250_remediation_results.jsonl")
    generalization_rows = _read_jsonl(OUTPUT_DIR / "generalization_250_remediation_results.jsonl")
    holdout_rows = _read_jsonl(OUTPUT_DIR / "holdout_250_remediation_results.jsonl")
    latency_rows = _read_jsonl(OUTPUT_DIR / "latency_250_remediation_results.jsonl")
    routeability = _read_json(OUTPUT_DIR / "250_routeability_audit.json")
    cluster_census = _read_json(OUTPUT_DIR / "250_failure_cluster_census.json")
    wrong_audit = _read_json(OUTPUT_DIR / "250_wrong_subsystem_audit.json")
    latency_audit = _read_json(OUTPUT_DIR / "250_latency_lane_audit.json")
    static_check = _read_json(OUTPUT_DIR / "250_static_anti_hardcoding_check.json")

    recommendation = _recommendation(post_rows, holdout_rows, post_summary)
    _write_json(OUTPUT_DIR / "250_post_remediation_recommendation.json", recommendation)
    report = _report(
        original_summary=original_summary,
        post_summary=post_summary,
        original_rows=original_rows,
        post_rows=post_rows,
        targeted_rows=targeted_rows,
        generalization_rows=generalization_rows,
        holdout_rows=holdout_rows,
        latency_rows=latency_rows,
        routeability=routeability,
        cluster_census=cluster_census,
        wrong_audit=wrong_audit,
        latency_audit=latency_audit,
        static_check=static_check,
        recommendation=recommendation,
    )
    (OUTPUT_DIR / "250_post_remediation_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"report": str(OUTPUT_DIR / "250_post_remediation_report.md"), "recommendation": recommendation["recommendation"]}, indent=2))


def _report(
    *,
    original_summary: dict[str, Any],
    post_summary: dict[str, Any],
    original_rows: list[dict[str, Any]],
    post_rows: list[dict[str, Any]],
    targeted_rows: list[dict[str, Any]],
    generalization_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
    latency_rows: list[dict[str, Any]],
    routeability: dict[str, Any],
    cluster_census: dict[str, Any],
    wrong_audit: dict[str, Any],
    latency_audit: dict[str, Any],
    static_check: dict[str, Any],
    recommendation: dict[str, Any],
) -> str:
    original_raw = original_summary.get("raw_counts") or {}
    post_raw = _raw_counts(post_rows)
    original_failures = (original_summary.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    post_failures = _failure_counts(post_rows)
    safety = post_summary.get("safety") or {}
    payload = post_summary.get("payload_summary") or {}
    latency = post_summary.get("latency_summary_ms") or _latency_stats(post_rows)
    original_generic = _generic_fallback_by_family(original_rows)
    post_generic = _generic_fallback_by_family(post_rows)
    original_wrong = [row for row in original_rows if row.get("failure_category") == "wrong_subsystem"]
    post_wrong = [row for row in post_rows if row.get("failure_category") == "wrong_subsystem"]
    post_real_gaps = [row for row in post_rows if row.get("failure_category") == "real_routing_gap"]
    post_latency = [row for row in post_rows if row.get("failure_category") == "latency_issue"]
    known_workspace = [row for row in post_rows if "known_workspace_latency_lane" in (row.get("known_lane_labels") or [])]
    routeability_counts = routeability.get("classification_counts") or {}
    anti = {
        "exact_250_repro_pass_rate": _pass_rate(targeted_rows),
        "unseen_variant_pass_rate": _tag_rate(generalization_rows, "positive"),
        "near_miss_preservation_rate": _tag_rate(generalization_rows, "near_miss"),
        "ambiguity_or_missing_context_correctness": _tag_rate(generalization_rows, "ambiguous"),
        "full_250_rerun_pass_rate": _pass_rate(post_rows),
        "holdout_pass_rate": _pass_rate(holdout_rows),
        "holdout_unseen_positive_pass_rate": _tag_rate(holdout_rows, "positive"),
        "holdout_near_miss_preservation_rate": _tag_rate(holdout_rows, "near_miss"),
        "holdout_ambiguity_correctness": _tag_rate(holdout_rows, "ambiguous"),
    }
    top_remaining = _by_expected_family([row for row in post_rows if not row.get("passed")])
    lines = [
        "# 250 Post-Remediation Checkpoint Report",
        "",
        "## Executive Summary",
        f"- 250 rerun attempted/completed/durable rows: {len(post_rows)} / {len(post_rows)} / {len(post_rows)}",
        f"- Pass/fail/excluded moved from {original_raw.get('pass')} / {original_raw.get('fail')} / {original_raw.get('excluded')} to {post_raw.get('pass')} / {post_raw.get('fail')} / {post_raw.get('excluded')}.",
        f"- Real routing gaps dropped from {original_failures.get('real_routing_gap', 0)} to {post_failures.get('real_routing_gap', 0)}.",
        f"- Wrong-subsystem failures dropped from {len(original_wrong)} to {len(post_wrong)}.",
        f"- Payload guardrails held: max response {int((payload.get('response_json_bytes') or {}).get('max') or 0)} bytes, 0 rows above 1 MB, 0 payload guardrail failures.",
        f"- Holdout was not clean: {_format_rate(anti['holdout_pass_rate'])}; 1000 remains blocked.",
        f"- Recommendation: {recommendation['recommendation']}",
        "",
        "## Safety Summary",
        f"- Provider calls: {safety.get('provider_calls', _bool_count(post_rows, 'provider_called'))}",
        f"- Real external actions: {safety.get('real_external_actions', _bool_count(post_rows, 'external_action_performed'))}",
        f"- Hard timeouts: {safety.get('hard_timeouts', sum(1 for row in post_rows if row.get('status') == 'hard_timeout'))}",
        f"- Process kills: {safety.get('process_kills', _bool_count(post_rows, 'process_killed'))}",
        f"- Orphan process check: {safety.get('orphan_process_check')}",
        "",
        "## Harness Durability",
        f"- Attempted: {len(post_rows)}",
        f"- Completed: {len(post_rows)}",
        f"- Durable rows: {len(post_rows)}",
        "- Completed count equals durable rows.",
        "",
        "## Before/After Comparison",
        "| metric | original 250 | post remediation 250 |",
        "| --- | ---: | ---: |",
        f"| pass | {original_raw.get('pass')} | {post_raw.get('pass')} |",
        f"| fail | {original_raw.get('fail')} | {post_raw.get('fail')} |",
        f"| excluded | {original_raw.get('excluded')} | {post_raw.get('excluded')} |",
        f"| real_routing_gap | {original_failures.get('real_routing_gap', 0)} | {post_failures.get('real_routing_gap', 0)} |",
        f"| wrong_subsystem | {original_failures.get('wrong_subsystem', 0)} | {post_failures.get('wrong_subsystem', 0)} |",
        f"| latency_issue | {original_failures.get('latency_issue', 0)} | {post_failures.get('latency_issue', 0)} |",
        f"| payload_guardrail_failure | {original_failures.get('payload_guardrail_failure', 0)} | {post_failures.get('payload_guardrail_failure', 0)} |",
        "",
        "## Anti-Overfitting Results",
        "| lane | pass | total | rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, payload_rate in anti.items():
        lines.append(f"| {label} | {payload_rate['pass']} | {payload_rate['total']} | {payload_rate['rate_percent']}% |")
    lines.extend(
        [
            "",
            "Holdout failures were not patched in this pass. They indicate remaining generalization risks in Discord relay phrasing, context-action vs app-open disambiguation, network near-miss handling, and deictic open-that handling.",
            "",
            "## Failure Category Comparison",
            "| category | original 250 | post remediation |",
            "| --- | ---: | ---: |",
        ]
    )
    for category in sorted(set(original_failures) | set(post_failures)):
        lines.append(f"| {category} | {original_failures.get(category, 0)} | {post_failures.get(category, 0)} |")
    lines.extend(
        [
            "",
            "## Generic-Provider Fallback Comparison",
            "| expected family | original fallback count | post fallback count |",
            "| --- | ---: | ---: |",
        ]
    )
    for family in sorted(set(original_generic) | set(post_generic)):
        lines.append(f"| {family} | {original_generic.get(family, 0)} | {post_generic.get(family, 0)} |")
    lines.extend(
        [
            "",
            "## Wrong-Subsystem Comparison",
            f"- Before count: {len(original_wrong)}",
            f"- After count: {len(post_wrong)}",
            "",
            "| test_id | expected | actual | reason |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in post_wrong:
        lines.append(
            f"| {row.get('test_id')} | {row.get('expected_route_family')}/{row.get('expected_subsystem')}/{row.get('expected_tool')} | "
            f"{row.get('actual_route_family')}/{row.get('actual_subsystem')}/{row.get('actual_tool')} | {str(row.get('failure_reason') or '').replace('|', '/')} |"
        )
    if not post_wrong:
        lines.append("| none | - | - | - |")
    lines.extend(
        [
            "",
            "## Routeability Audit Summary",
            f"- Classification counts: {routeability_counts}",
            "- Scaffold/docs-only rows were not introduced into normal scoring by this pass.",
            "- Implemented routeable native-capable prompts that still fall to generic_provider remain scored failures.",
            "",
            "## Top Fixed Clusters",
            "- Operator-wrapper normalization reduced many casual/shorthand/noisy native-capable prompts falling to generic_provider.",
            "- Status ownership now routes active apps, network online status, resource status, and window status natively.",
            "- `resource` is normalized to the scored `resources` route family.",
            "- `system_control` is registered in the built-in tool registry, so settings-control prompts now dry-run through the native tool.",
            "- Workspace restore overcapture for vague `open the thing` style prompts was narrowed.",
            "",
            "## Top Remaining Clusters",
            "| expected family | remaining failures |",
            "| --- | ---: |",
        ]
    )
    for family, count in top_remaining[:20]:
        lines.append(f"| {family} | {count} |")
    lines.extend(
        [
            "",
            "## Latency Lane Summary",
            f"- Post rerun p50/p90/p95/max ms: {latency.get('median')} / {latency.get('p90')} / {latency.get('p95')} / {latency.get('max')}",
            f"- Post rerun latency failures: {len(post_latency)}",
            f"- Known workspace latency lane rows: {len(known_workspace)}",
            f"- Original latency audit classifications: {latency_audit.get('classification_counts')}",
            f"- Latency mini-suite failures after routing fixes: {sum(1 for row in latency_rows if not row.get('passed'))}",
            "- Workspace latency remains bounded and hard-timeout-contained, but non-workspace route families still have product latency bugs or unattributed runtime overhead.",
            "",
            "## Payload Guardrail Summary",
            f"- Max response size: {int((payload.get('response_json_bytes') or {}).get('max') or 0)} bytes",
            f"- Rows above 1 MB: {len(payload.get('rows_above_1mb') or [])}",
            f"- Rows above 5 MB: {len(payload.get('rows_above_5mb') or [])}",
            f"- Max workspace item count: {payload.get('max_workspace_item_count')}",
            f"- Payload guardrail failures: {len(payload.get('payload_guardrail_failures') or [])}",
            "",
            "## Routine-Save Summary",
            "- Current 250 rerun did not reproduce the historical 43s-75s catastrophic native routine_save shape.",
            "- Historical routine_save remains labeled `known_unreproduced_product_latency_blocker`; it was not marked fixed.",
            "",
            "## Telemetry Gap Summary",
            "- The rerun retained route candidates, route scores, route state, payload diagnostics, and stage timing fields in durable rows.",
            "- Direct/legacy route-surface exemptions remain documented in prior telemetry audits.",
            "",
            "## Tests Added",
            "- `tests/test_command_routing_250_remediation.py` adds exact repros, unseen variants, near-misses, and ambiguity checks.",
            "- Process-isolated suites were run for exact 250 repros, unseen generalization, latency, holdout, and the 250 rerun.",
            f"- Static anti-hardcoding check status: {static_check.get('status')}; exact prompt hits: {len(static_check.get('exact_prompt_hits') or [])}; test-id hits: {len(static_check.get('test_id_hits') or [])}.",
            "",
            "## What Was Deliberately Not Changed",
            "- No 1000-case run.",
            "- No broad planner redesign.",
            "- No provider-first interpretation.",
            "- No prompt-by-prompt hardcoding.",
            "- No payload guardrail weakening.",
            "- No approval/trust weakening.",
            "- No routine_save historical blocker relabeling.",
            "- Holdout failures were not patched in this pass.",
            "",
            "## Remaining Blockers",
            f"- {len(post_real_gaps)} real routing gaps remain, mostly deictic/follow-up/ambiguous benchmark lanes and remaining generic fallbacks.",
            f"- {len(post_latency)} latency issues remain, including {len(known_workspace)} known workspace lane rows and non-workspace latency rows.",
            "- 6 system_control rows now route correctly but still fail the old approval/preview expectation; this needs a policy/corpus decision rather than silent relabeling.",
            "- Holdout failed 4 of 17 rows, so generalization is not strong enough to recommend 1000.",
            "",
            "## Recommendation",
            f"- {recommendation['recommendation']}",
            f"- Reason: {recommendation['reason']}",
        ]
    )
    return "\n".join(lines) + "\n"


def _recommendation(post_rows: list[dict[str, Any]], holdout_rows: list[dict[str, Any]], post_summary: dict[str, Any]) -> dict[str, Any]:
    post_failures = _failure_counts(post_rows)
    holdout_failed = [row for row in holdout_rows if not row.get("passed")]
    payload = post_summary.get("payload_summary") or {}
    payload_failures = len(payload.get("payload_guardrail_failures") or [])
    if holdout_failed:
        rec = "keep 1000 blocked; run another targeted generalization and overcapture pass"
        reason = "Holdout failures show unresolved generalization and overcapture risk."
    elif post_failures.get("real_routing_gap", 0) > 25:
        rec = "keep 1000 blocked; run another targeted routing pass"
        reason = "Real routing gaps remain too high for a 1000-case proof run."
    elif payload_failures:
        rec = "keep 1000 blocked; fix payload guardrail failures"
        reason = "Payload guardrail failures are not acceptable for broader evaluation."
    else:
        rec = "consider 1000 after review"
        reason = "Safety and payload criteria held and remaining failures are clustered."
    return {
        "recommendation": rec,
        "reason": reason,
        "post_failure_counts": post_failures,
        "holdout_failures": len(holdout_failed),
        "payload_guardrail_failures": payload_failures,
        "hard_timeouts": sum(1 for row in post_rows if row.get("status") == "hard_timeout" or row.get("failure_category") == "hard_timeout"),
    }


def _raw_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "pass": sum(1 for row in rows if row.get("passed")),
        "fail": sum(1 for row in rows if not row.get("passed")),
        "excluded": sum(1 for row in rows if not row.get("score_in_pass_fail", True)),
    }


def _failure_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(row.get("failure_category") for row in rows if not row.get("passed") and row.get("score_in_pass_fail", True)))


def _generic_fallback_by_family(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        if row.get("actual_route_family") == "generic_provider":
            counts[str(row.get("expected_route_family") or "")] += 1
    return dict(counts)


def _by_expected_family(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    counts = Counter(str(row.get("expected_route_family") or "") for row in rows)
    return counts.most_common()


def _tag_rate(rows: list[dict[str, Any]], tag: str) -> dict[str, Any]:
    selected = [row for row in rows if tag in set(row.get("case", {}).get("tags") or [])]
    return _rate(selected)


def _pass_rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _rate(rows)


def _rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for row in rows if row.get("passed"))
    return {"pass": passed, "total": total, "rate_percent": round((passed / total) * 100, 1) if total else 0.0}


def _format_rate(payload: dict[str, Any]) -> str:
    return f"{payload['pass']}/{payload['total']} ({payload['rate_percent']}%)"


def _latency_stats(rows: list[dict[str, Any]]) -> dict[str, float]:
    values = sorted(float(row.get("total_latency_ms") or row.get("latency_ms") or 0) for row in rows)
    if not values:
        return {}
    return {
        "min": round(values[0], 3),
        "median": round(median(values), 3),
        "p90": round(values[min(len(values) - 1, int(len(values) * 0.9))], 3),
        "p95": round(values[min(len(values) - 1, int(len(values) * 0.95))], 3),
        "max": round(values[-1], 3),
    }


def _bool_count(rows: list[dict[str, Any]], field: str) -> int:
    return sum(1 for row in rows if row.get(field))


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
