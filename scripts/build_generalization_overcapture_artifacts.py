from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


PREVIOUS_DIR = Path(".artifacts") / "command-usability-eval" / "250-remediation"
OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "generalization-overcapture-pass"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    holdout_rows = _read_jsonl(PREVIOUS_DIR / "holdout_250_remediation_results.jsonl")
    post_rows = _read_jsonl(PREVIOUS_DIR / "250_post_remediation_results.jsonl")
    failures = [row for row in holdout_rows if not row.get("passed")]
    diagnosis = {
        "source": str(PREVIOUS_DIR / "holdout_250_remediation_results.jsonl"),
        "failure_count": len(failures),
        "failures": [_diagnose_holdout_failure(row) for row in failures],
    }
    repair_plan = _repair_plan(diagnosis["failures"], post_rows)
    static_check = _static_anti_overfitting_check(failures)
    _write_json(OUTPUT_DIR / "holdout_failure_diagnosis.json", diagnosis)
    (OUTPUT_DIR / "holdout_failure_diagnosis.md").write_text(_diagnosis_markdown(diagnosis), encoding="utf-8")
    _write_json(OUTPUT_DIR / "generalization_repair_plan.json", repair_plan)
    (OUTPUT_DIR / "generalization_repair_plan.md").write_text(_repair_plan_markdown(repair_plan), encoding="utf-8")
    (OUTPUT_DIR / "static_anti_overfitting_check.md").write_text(_static_markdown(static_check), encoding="utf-8")
    print(json.dumps({"output_dir": str(OUTPUT_DIR), "holdout_failures": len(failures)}, indent=2))


def _diagnose_holdout_failure(row: dict[str, Any]) -> dict[str, Any]:
    test_id = str(row.get("test_id") or "")
    expected = str(row.get("expected_route_family") or "")
    actual = str(row.get("actual_route_family") or "")
    if test_id == "holdout_positive_discord_00":
        classification = "generalization miss"
        root_cause = "Discord relay ownership recognized send/share/message, but not relay/forward/pass/DM phrasing with Discord transport prepositions."
        why = "Prior fix covered send/share forms and exact prior variants, not the route-family verb family."
    elif test_id == "holdout_positive_context_00":
        classification = "wrong subsystem / target extraction failure"
        root_cause = "Selected-text context actions were checked too narrowly and app_control treated 'selected text' as an app name."
        why = "Prior context-action rules handled explicit 'selection' forms but did not normalize operator wrappers or selected-text aliases before app-control matching."
    elif test_id == "holdout_near_miss_network_00":
        classification = "overcapture / near-miss regression"
        root_cause = "Network status ownership accepted the bare token 'network' without requiring device connectivity/status intent."
        why = "Prior network fix added online/status coverage but left a broad token trigger in place."
    elif test_id == "holdout_ambiguous_this_00":
        classification = "ambiguity handling failure / overcapture"
        root_cause = "Screen-awareness action routing accepted bare deictic action verbs without recent screen grounding or visible target words."
        why = "Prior screen near-miss guard covered code/window status overcapture but not bare 'open/click that' forms."
    else:
        classification = "unknown"
        root_cause = "Needs manual inspection."
        why = "No cluster mapping was declared."
    return {
        "test_id": test_id,
        "prompt": row.get("prompt") or row.get("input"),
        "expected": {
            "route_family": expected,
            "subsystem": row.get("expected_subsystem"),
            "tool": row.get("expected_tool"),
            "result_state": row.get("expected_result_state"),
        },
        "actual": {
            "route_family": actual,
            "subsystem": row.get("actual_subsystem"),
            "tool": row.get("actual_tool"),
            "result_state": row.get("actual_result_state") or row.get("result_state"),
        },
        "failure_category": row.get("failure_category"),
        "classification": classification,
        "route_candidates": row.get("route_candidates"),
        "route_scores": row.get("route_scores"),
        "fallback_reason": row.get("fallback_reason"),
        "generic_provider_eligible": row.get("generic_provider_eligible"),
        "generic_provider_selected_reason": row.get("generic_provider_selected_reason"),
        "likely_root_cause": root_cause,
        "why_previous_fix_did_not_generalize": why,
    }


def _repair_plan(diagnoses: list[dict[str, Any]], post_rows: list[dict[str, Any]]) -> dict[str, Any]:
    post_failures = [row for row in post_rows if not row.get("passed")]
    clusters = [
        {
            "cluster_id": "GOC-001",
            "route_family_pattern": "Discord relay transport synonyms",
            "affected_wording_styles": ["positive", "casual", "shorthand"],
            "underlying_bug": "native candidate missing for relay/forward/pass/DM verbs when Discord is explicit",
            "intended_native_owner": "discord_relay",
            "intended_clarification_behavior": "route to discord_relay and ask for destination if destination alias is missing",
            "overcapture_risk": "medium; Discord educational or bot-building prompts must remain generic_provider",
            "near_miss_risks": ["Discord relay bots", "relay channel explanations", "Baby names/community chatter"],
            "proposed_route_family_level_fix": "expand Discord relay verb/entity extraction and missing-destination clarification without exact prompt literals",
            "required_positive_unseen_variants": ["forward this to Baby via Discord", "DM this to Baby in Discord", "pass this along to Baby on Discord"],
            "required_near_miss_negatives": ["explain Discord relay bots", "what is a relay channel in Discord", "Baby names in Discord communities"],
            "required_ambiguity_missing_context_cases": ["relay this on Discord", "send this through Discord"],
            "fix_now_or_defer": "fix_now",
        },
        {
            "cluster_id": "GOC-002",
            "route_family_pattern": "Selected-context open/show actions",
            "affected_wording_styles": ["positive", "casual", "shorthand", "ambiguity"],
            "underlying_bug": "app_control overcaptures selected/highlighted text as an app target",
            "intended_native_owner": "context_action",
            "intended_clarification_behavior": "route to context_action and ask for selection/clipboard context when missing",
            "overcapture_risk": "medium; educational phrases about selected text/selection bias must remain generic_provider",
            "near_miss_risks": ["selected text in HTML", "selection bias", "selection criteria examples"],
            "proposed_route_family_level_fix": "normalize selected/highlighted text aliases before app_control and add missing-context clarification",
            "required_positive_unseen_variants": ["show the highlighted text", "bring up the selected text", "show what I highlighted"],
            "required_near_miss_negatives": ["what is selected text in HTML", "explain selection bias", "open selection criteria examples"],
            "required_ambiguity_missing_context_cases": ["open selected text", "show the highlighted text"],
            "fix_now_or_defer": "fix_now",
        },
        {
            "cluster_id": "GOC-003",
            "route_family_pattern": "Network status versus conceptual network language",
            "affected_wording_styles": ["near_miss", "positive"],
            "underlying_bug": "network_status accepts the bare word network without status/connectivity intent",
            "intended_native_owner": "network for device connectivity; generic_provider for conceptual prompts",
            "intended_clarification_behavior": "not applicable for conceptual near-misses",
            "overcapture_risk": "high; network effects, neural network, and networking advice should not route to system status",
            "near_miss_risks": ["network effects", "neural network", "network graph", "networking advice"],
            "proposed_route_family_level_fix": "require connectivity/status/device intent around online/network/internet terms",
            "required_positive_unseen_variants": ["is my internet connected", "check if the laptop is online"],
            "required_near_miss_negatives": ["explain network effects in startups", "what is a neural network", "networking advice for founders"],
            "required_ambiguity_missing_context_cases": ["network?", "online?"],
            "fix_now_or_defer": "fix_now",
        },
        {
            "cluster_id": "GOC-004",
            "route_family_pattern": "Bare deictic UI action without screen grounding",
            "affected_wording_styles": ["ambiguity", "deictic"],
            "underlying_bug": "screen_awareness accepts bare action verb plus deictic token without recent screen context or visible referent",
            "intended_native_owner": "generic_provider unless visible target wording or recent screen resolution exists",
            "intended_clarification_behavior": "future pass may route to native clarification; this pass prevents false screen action ownership",
            "overcapture_risk": "high; bare open/click/press it must not claim screen ownership without evidence",
            "near_miss_risks": ["open that", "open it", "click that", "press it"],
            "proposed_route_family_level_fix": "screen-awareness action request requires visible referent or recent screen resolution",
            "required_positive_unseen_variants": ["click that button", "open that dropdown", "press continue"],
            "required_near_miss_negatives": ["open that", "open it", "click that"],
            "required_ambiguity_missing_context_cases": ["press it", "open that"],
            "fix_now_or_defer": "fix_now",
        },
    ]
    high_value_remaining = dict(Counter(row.get("expected_route_family") for row in post_failures).most_common(12))
    return {
        "source_holdout": str(PREVIOUS_DIR / "holdout_250_remediation_results.jsonl"),
        "source_250_post_remediation": str(PREVIOUS_DIR / "250_post_remediation_results.jsonl"),
        "holdout_clusters": clusters,
        "remaining_high_value_250_clusters_by_expected_family": high_value_remaining,
        "deferred_clusters": [
            "broad deictic/follow-up benchmark lanes requiring session-state fixtures",
            "system_control approval expectation policy/corpus decision",
            "non-workspace latency product issues",
        ],
    }


def _static_anti_overfitting_check(failures: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = [str(row.get("prompt") or row.get("input") or "").strip().lower() for row in failures]
    test_ids = [str(row.get("test_id") or "").strip().lower() for row in failures]
    try:
        diff = subprocess.run(
            ["git", "diff", "--unified=0", "--", "src/stormhelm"],
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
            check=False,
        ).stdout
    except Exception as exc:  # pragma: no cover
        return {"status": "error", "error": str(exc)}
    added_product_lines = [
        line[1:].strip()
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    prompt_hits = []
    test_id_hits = []
    for line in added_product_lines:
        lowered = line.lower()
        for prompt in prompts:
            if prompt and prompt in lowered:
                prompt_hits.append({"prompt": prompt, "line": line})
        for test_id in test_ids:
            if test_id and test_id in lowered:
                test_id_hits.append({"test_id": test_id, "line": line})
    return {
        "status": "passed" if not prompt_hits and not test_id_hits else "needs_review",
        "rules": [
            "Exact failed prompt strings may appear in tests, reports, and artifacts.",
            "Exact failed prompt strings and test_ids must not appear in product routing logic.",
            "Product routing fixes must be expressed as route-family ownership, extraction, clarification, confidence, or telemetry logic.",
            "No broad catch-all phrase should capture unrelated near-misses.",
            "generic_provider remains available when no native family meaningfully owns the request.",
        ],
        "scope": "added product source lines from git diff -- src/stormhelm",
        "added_product_line_count": len(added_product_lines),
        "exact_prompt_hits": prompt_hits,
        "test_id_hits": test_id_hits,
    }


def _diagnosis_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Holdout Failure Diagnosis",
        "",
        f"- Source: {payload['source']}",
        f"- Failure count: {payload['failure_count']}",
        "",
        "| test_id | classification | expected | actual | likely root cause |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in payload["failures"]:
        lines.append(
            f"| {item['test_id']} | {item['classification']} | "
            f"{item['expected']['route_family']}/{item['expected']['subsystem']}/{item['expected']['tool']} | "
            f"{item['actual']['route_family']}/{item['actual']['subsystem']}/{item['actual']['tool']} | "
            f"{item['likely_root_cause']} |"
        )
    lines.extend(["", "## Details"])
    for item in payload["failures"]:
        lines.extend(
            [
                f"### {item['test_id']}",
                f"- Prompt: `{item['prompt']}`",
                f"- Failure category: {item['failure_category']}",
                f"- Route scores: `{item['route_scores']}`",
                f"- Fallback reason: `{item['fallback_reason']}`",
                f"- Generic provider eligible/selected reason: {item['generic_provider_eligible']} / `{item['generic_provider_selected_reason']}`",
                f"- Why previous fix did not generalize: {item['why_previous_fix_did_not_generalize']}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def _repair_plan_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Generalization Repair Plan",
        "",
        f"- Source holdout: {payload['source_holdout']}",
        f"- Source 250 post-remediation: {payload['source_250_post_remediation']}",
        "",
        "| cluster | pattern | owner | fix now | overcapture risk |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in payload["holdout_clusters"]:
        lines.append(
            f"| {item['cluster_id']} | {item['route_family_pattern']} | {item['intended_native_owner']} | "
            f"{item['fix_now_or_defer']} | {item['overcapture_risk']} |"
        )
    lines.extend(["", "## Remaining 250 Clusters", ""])
    for family, count in payload["remaining_high_value_250_clusters_by_expected_family"].items():
        lines.append(f"- {family}: {count}")
    lines.extend(["", "## Deferred", ""])
    lines.extend(f"- {item}" for item in payload["deferred_clusters"])
    return "\n".join(lines) + "\n"


def _static_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Static Anti-Overfitting Check",
        "",
        f"- Status: {payload.get('status')}",
        f"- Scope: {payload.get('scope')}",
        f"- Added product line count: {payload.get('added_product_line_count')}",
        f"- Exact prompt hits: {len(payload.get('exact_prompt_hits') or [])}",
        f"- Test-id hits: {len(payload.get('test_id_hits') or [])}",
        "",
        "## Rules",
    ]
    lines.extend(f"- {rule}" for rule in payload.get("rules") or [])
    if payload.get("exact_prompt_hits"):
        lines.extend(["", "## Exact Prompt Hits"])
        lines.extend(f"- `{item['prompt']}` in `{item['line']}`" for item in payload["exact_prompt_hits"])
    if payload.get("test_id_hits"):
        lines.extend(["", "## Test ID Hits"])
        lines.extend(f"- `{item['test_id']}` in `{item['line']}`" for item in payload["test_id_hits"])
    return "\n".join(lines) + "\n"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
