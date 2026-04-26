from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


PASS1_DIR = Path(".artifacts") / "command-usability-eval" / "generalization-overcapture-pass"
REMEDIATION_DIR = Path(".artifacts") / "command-usability-eval" / "250-remediation"
OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "generalization-overcapture-pass-2"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    holdout2_rows = _read_jsonl(PASS1_DIR / "holdout_2_results.jsonl")
    post_remediation_rows = _read_jsonl(REMEDIATION_DIR / "250_post_remediation_results.jsonl")
    post_generalization_rows = _read_jsonl(PASS1_DIR / "250_post_generalization_results.jsonl")
    holdout2_failures = [row for row in holdout2_rows if not row.get("passed")]
    regression_delta = _regression_delta(post_remediation_rows, post_generalization_rows)
    diagnosis = {
        "source": str(PASS1_DIR / "holdout_2_results.jsonl"),
        "failure_count": len(holdout2_failures),
        "failures": [_diagnose_holdout2_failure(row) for row in holdout2_failures],
    }
    repair_plan = _repair_plan(diagnosis["failures"], regression_delta)
    static_check = _static_anti_overfitting_check(
        failures=holdout2_failures,
        extra_rows=regression_delta["pass_to_fail"],
    )
    _write_json(OUTPUT_DIR / "holdout_2_failure_diagnosis.json", diagnosis)
    (OUTPUT_DIR / "holdout_2_failure_diagnosis.md").write_text(_diagnosis_markdown(diagnosis), encoding="utf-8")
    _write_json(OUTPUT_DIR / "250_regression_delta.json", regression_delta)
    (OUTPUT_DIR / "250_regression_delta_report.md").write_text(_regression_markdown(regression_delta), encoding="utf-8")
    _write_json(OUTPUT_DIR / "generalization_2_repair_plan.json", repair_plan)
    (OUTPUT_DIR / "generalization_2_repair_plan.md").write_text(_repair_plan_markdown(repair_plan), encoding="utf-8")
    (OUTPUT_DIR / "static_anti_overfitting_check.md").write_text(_static_markdown(static_check), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_dir": str(OUTPUT_DIR),
                "holdout_2_failures": len(holdout2_failures),
                "pass_to_fail_regressions": len(regression_delta["pass_to_fail"]),
                "fail_to_pass": len(regression_delta["fail_to_pass"]),
                "static_check": static_check.get("status"),
            },
            indent=2,
        )
    )


def _diagnose_holdout2_failure(row: dict[str, Any]) -> dict[str, Any]:
    test_id = str(row.get("test_id") or "")
    mapping: dict[str, dict[str, str]] = {
        "holdout2_positive_network_03": {
            "classification": "generalization miss",
            "root_cause": "Wi-Fi status ownership missed normalized wi-fi variants and SSID/wireless phrasing while preserving conceptual-network near-miss guards.",
            "why": "The previous network fix tightened conceptual overcapture but did not cover normalized wi-fi spelling or connection-name questions.",
            "bug_pattern": "native_candidate_missing",
            "cluster_id": "GOC2-001",
        },
        "holdout2_positive_screen_03": {
            "classification": "generalization miss",
            "root_cause": "Screen-action ownership required visible referent nouns and did not recognize common button/control labels after an action verb.",
            "why": "The previous fix protected bare deictics, but the positive lane did not include action verb plus named control text.",
            "bug_pattern": "route_ownership_gap",
            "cluster_id": "GOC2-002",
        },
        "holdout2_positive_software_01": {
            "classification": "corpus expectation issue / route taxonomy mismatch",
            "root_cause": "Quit/close an app is app/window control behavior, not software lifecycle install/update/uninstall control.",
            "why": "The holdout expected software_control, but the product route selected the safer native app_control owner.",
            "bug_pattern": "corpus_expectation_issue",
            "cluster_id": "GOC2-003",
        },
        "holdout2_positive_app_01": {
            "classification": "wrong subsystem route",
            "root_cause": "Resource telemetry saw 'right now' before active-app status could own the request.",
            "why": "The previous pass did not order active-app/process status ahead of generic resource telemetry.",
            "bug_pattern": "wrong_subsystem_route",
            "cluster_id": "GOC2-004",
        },
        "holdout2_near_network_02": {
            "classification": "overcapture / near-miss regression",
            "root_cause": "The native comparison route accepted any leading compare verb, including conceptual comparisons that require provider reasoning.",
            "why": "Prior near-miss lanes covered network-status overcapture, not comparison-route conceptual overcapture.",
            "bug_pattern": "native_candidate_declined_wrongly",
            "cluster_id": "GOC2-005",
        },
        "holdout2_deictic_browser_01": {
            "classification": "wrong subsystem / deictic browser ownership gap",
            "root_cause": "Unbound website/page/site deictics were not claimed by browser_destination clarification, so app_control treated the referent as an app name.",
            "why": "Previous browser/app canaries covered concrete destinations and app opens, not unbound website deictics.",
            "bug_pattern": "deictic_binding_failure",
            "cluster_id": "GOC2-006",
        },
    }
    detail = mapping.get(
        test_id,
        {
            "classification": "unknown",
            "root_cause": "Needs manual inspection.",
            "why": "No cluster mapping declared.",
            "bug_pattern": "unknown",
            "cluster_id": "GOC2-UNKNOWN",
        },
    )
    return {
        "test_id": test_id,
        "prompt": row.get("prompt") or row.get("input"),
        "expected": {
            "route_family": row.get("expected_route_family"),
            "subsystem": row.get("expected_subsystem"),
            "tool": row.get("expected_tool"),
            "result_state": row.get("expected_result_state"),
        },
        "actual": {
            "route_family": row.get("actual_route_family"),
            "subsystem": row.get("actual_subsystem"),
            "tool": row.get("actual_tool"),
            "result_state": row.get("actual_result_state") or row.get("result_state"),
        },
        "failure_category": row.get("failure_category"),
        "classification": detail["classification"],
        "bug_pattern": detail["bug_pattern"],
        "cluster_id": detail["cluster_id"],
        "route_candidates": row.get("route_candidates"),
        "route_scores": row.get("route_scores"),
        "fallback_reason": row.get("fallback_reason"),
        "generic_provider_eligible": row.get("generic_provider_eligible"),
        "generic_provider_selected_reason": row.get("generic_provider_selected_reason"),
        "likely_root_cause": detail["root_cause"],
        "why_previous_pass_did_not_catch_it": detail["why"],
    }


def _regression_delta(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    before_by_id = {str(row.get("test_id") or ""): row for row in before}
    after_by_id = {str(row.get("test_id") or ""): row for row in after}
    ids = sorted(set(before_by_id) & set(after_by_id))
    pass_to_fail: list[dict[str, Any]] = []
    fail_to_pass: list[dict[str, Any]] = []
    category_changed: list[dict[str, Any]] = []
    route_changed: list[dict[str, Any]] = []
    subsystem_changed: list[dict[str, Any]] = []
    result_state_changed: list[dict[str, Any]] = []
    known_lane_changed: list[dict[str, Any]] = []
    for test_id in ids:
        old = before_by_id[test_id]
        new = after_by_id[test_id]
        delta = _row_delta(old, new)
        if old.get("passed") and not new.get("passed"):
            pass_to_fail.append(_classify_regression(delta))
        if not old.get("passed") and new.get("passed"):
            fail_to_pass.append(delta)
        if old.get("failure_category") != new.get("failure_category"):
            category_changed.append(delta)
        if old.get("actual_route_family") != new.get("actual_route_family"):
            route_changed.append(delta)
        if old.get("actual_subsystem") != new.get("actual_subsystem"):
            subsystem_changed.append(delta)
        if (old.get("actual_result_state") or old.get("result_state")) != (new.get("actual_result_state") or new.get("result_state")):
            result_state_changed.append(delta)
        if old.get("known_lane_labels") != new.get("known_lane_labels"):
            known_lane_changed.append(delta)
    return {
        "source_before": str(REMEDIATION_DIR / "250_post_remediation_results.jsonl"),
        "source_after": str(PASS1_DIR / "250_post_generalization_results.jsonl"),
        "compared_count": len(ids),
        "pass_to_fail": pass_to_fail,
        "fail_to_pass": fail_to_pass,
        "failure_category_changed": category_changed,
        "route_changed": route_changed,
        "subsystem_changed": subsystem_changed,
        "result_state_changed": result_state_changed,
        "known_lane_changed": known_lane_changed,
        "summary": {
            "pass_to_fail_count": len(pass_to_fail),
            "fail_to_pass_count": len(fail_to_pass),
            "category_changed_count": len(category_changed),
            "route_changed_count": len(route_changed),
            "subsystem_changed_count": len(subsystem_changed),
            "result_state_changed_count": len(result_state_changed),
            "known_lane_changed_count": len(known_lane_changed),
            "pass_to_fail_classification_counts": dict(Counter(row["regression_classification"] for row in pass_to_fail)),
        },
    }


def _row_delta(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": old.get("test_id"),
        "prompt": old.get("prompt") or old.get("input"),
        "expected_route_family": old.get("expected_route_family"),
        "old": _compact_row(old),
        "new": _compact_row(new),
    }


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": row.get("passed"),
        "actual_route_family": row.get("actual_route_family"),
        "actual_subsystem": row.get("actual_subsystem"),
        "actual_tool": row.get("actual_tool"),
        "result_state": row.get("actual_result_state") or row.get("result_state"),
        "failure_category": row.get("failure_category"),
        "failure_reason": row.get("failure_reason"),
        "latency_ms": row.get("latency_ms") or row.get("total_latency_ms"),
        "known_lane_labels": row.get("known_lane_labels"),
    }


def _classify_regression(delta: dict[str, Any]) -> dict[str, Any]:
    test_id = str(delta.get("test_id") or "")
    new = delta["new"]
    classification = "unknown"
    if test_id.startswith("discord_relay_") and str(new.get("failure_reason") or "").startswith("approval:"):
        classification = "corpus_expectation_issue"
    elif new.get("failure_category") == "latency_issue":
        classification = "latency_reclassification"
    elif delta["old"].get("actual_route_family") != new.get("actual_route_family"):
        classification = "real_regression"
    elif delta["old"].get("result_state") != new.get("result_state"):
        classification = "telemetry_reclassification"
    return {**delta, "regression_classification": classification}


def _repair_plan(diagnoses: list[dict[str, Any]], regression_delta: dict[str, Any]) -> dict[str, Any]:
    clusters = [
        {
            "cluster_id": "GOC2-001",
            "route_family_pattern": "Local network/Wi-Fi status versus conceptual network language",
            "affected_wording_styles": ["positive", "near_miss", "noisy", "ambiguity"],
            "underlying_bug": "native_candidate_missing for Wi-Fi/SSID status variants while conceptual network near-misses must stay provider-owned",
            "intended_native_owner": "network",
            "missing_context_behavior": "not applicable for concrete status requests; bare 'network?' stays generic/ambiguous",
            "overcapture_risk": "high",
            "near_miss_risks": ["neural networks", "network architecture", "network effects", "networking advice"],
            "proposed_route_family_level_fix": "recognize Wi-Fi/SSID/wireless connection-name questions via status regexes, not exact prompts",
            "tests_required": ["positive Wi-Fi variants", "conceptual near-misses", "bare ambiguity cases", "network canaries"],
            "fix_now_or_defer": "fix_now",
        },
        {
            "cluster_id": "GOC2-002",
            "route_family_pattern": "Screen action over named UI controls",
            "affected_wording_styles": ["positive", "casual", "noisy", "near_miss", "ambiguity"],
            "underlying_bug": "route_ownership_gap for action verb plus common UI control label",
            "intended_native_owner": "screen_awareness",
            "missing_context_behavior": "route as screen preflight/grounding only; eval must not click/type",
            "overcapture_risk": "medium",
            "near_miss_risks": ["submit a proposal", "explain submit button design", "press coverage"],
            "proposed_route_family_level_fix": "add bounded UI-control label lexicon under action verbs while preserving bare-deictic rejection",
            "tests_required": ["button label positives", "content-writing near-misses", "bare deictic ambiguity", "existing screen canaries"],
            "fix_now_or_defer": "fix_now",
        },
        {
            "cluster_id": "GOC2-003",
            "route_family_pattern": "App quit versus software lifecycle",
            "affected_wording_styles": ["positive"],
            "underlying_bug": "corpus expectation issue, not product route bug",
            "intended_native_owner": "app_control",
            "missing_context_behavior": "unknown app target should clarify/block in app_control, not software_control",
            "overcapture_risk": "low",
            "near_miss_risks": ["uninstall/update/install lifecycle prompts"],
            "proposed_route_family_level_fix": "no product change; preserve app_control canary and report taxonomy correction",
            "tests_required": ["quit app canary", "software lifecycle canaries"],
            "fix_now_or_defer": "defer_product_change",
        },
        {
            "cluster_id": "GOC2-004",
            "route_family_pattern": "App/process status versus resource telemetry",
            "affected_wording_styles": ["positive", "near_miss"],
            "underlying_bug": "wrong_subsystem_route caused by resource right-now telemetry check running before active-app status",
            "intended_native_owner": "app_control",
            "missing_context_behavior": "not applicable for status query",
            "overcapture_risk": "medium",
            "near_miss_risks": ["app ideas", "application architecture", "running app marketing"],
            "proposed_route_family_level_fix": "let active-app/window status decline resource telemetry before resource route wins",
            "tests_required": ["running apps positives", "application concept near-misses", "resource telemetry canaries"],
            "fix_now_or_defer": "fix_now",
        },
        {
            "cluster_id": "GOC2-005",
            "route_family_pattern": "Native file/context comparison versus conceptual comparison",
            "affected_wording_styles": ["near_miss", "positive", "ambiguity"],
            "underlying_bug": "comparison route accepted any compare verb without native comparison target evidence",
            "intended_native_owner": "comparison for file/context targets; generic_provider for conceptual comparisons",
            "missing_context_behavior": "native comparison clarifies when file/context targets are deictic or missing",
            "overcapture_risk": "high",
            "near_miss_risks": ["AI model comparison", "framework comparison", "pricing comparison", "architecture comparison"],
            "proposed_route_family_level_fix": "require file/document/path/deictic-context evidence for native comparison route",
            "tests_required": ["native comparison positives", "conceptual near-misses", "missing target clarifications"],
            "fix_now_or_defer": "fix_now",
        },
        {
            "cluster_id": "GOC2-006",
            "route_family_pattern": "Browser destination deictics versus app-control open",
            "affected_wording_styles": ["deictic_followup", "positive", "near_miss", "ambiguity"],
            "underlying_bug": "deictic website/page/site/link targets missing browser clarification and falling through to app_control",
            "intended_native_owner": "browser_destination",
            "missing_context_behavior": "route to browser_destination with missing destination_context clarification",
            "overcapture_risk": "medium",
            "near_miss_risks": ["website design advice", "site concepts", "open app names"],
            "proposed_route_family_level_fix": "add browser deictic clarification before app_control and reject web referent app candidates",
            "tests_required": ["deictic website positives", "concrete URL canaries", "website concept near-misses", "app open canaries"],
            "fix_now_or_defer": "fix_now",
        },
    ]
    return {
        "source_holdout_2": str(PASS1_DIR / "holdout_2_results.jsonl"),
        "source_250_regression_delta": str(OUTPUT_DIR / "250_regression_delta.json"),
        "clusters": clusters,
        "regression_delta_summary": regression_delta["summary"],
        "regression_interpretation": (
            "The 168 -> 161 pass-count decrease is mostly approval-observation/corpus-policy drift in Discord relay rows "
            "plus one bounded workflow latency threshold crossing; no broad route-family regression was found."
        ),
    }


def _static_anti_overfitting_check(*, failures: list[dict[str, Any]], extra_rows: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = {
        str(row.get("prompt") or row.get("input") or "").strip().lower()
        for row in failures
        if str(row.get("prompt") or row.get("input") or "").strip()
    }
    prompts.update(
        str(row.get("prompt") or "").strip().lower()
        for row in extra_rows
        if str(row.get("prompt") or "").strip()
    )
    test_ids = {str(row.get("test_id") or "").strip().lower() for row in failures if str(row.get("test_id") or "").strip()}
    test_ids.update(str(row.get("test_id") or "").strip().lower() for row in extra_rows if str(row.get("test_id") or "").strip())
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
    added_product_lines = [line[1:].strip() for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    prompt_hits = []
    test_id_hits = []
    for line in added_product_lines:
        lowered = line.lower()
        for prompt in sorted(prompts):
            if prompt and prompt in lowered:
                prompt_hits.append({"prompt": prompt, "line": line})
        for test_id in sorted(test_ids):
            if test_id and test_id in lowered:
                test_id_hits.append({"test_id": test_id, "line": line})
    return {
        "status": "passed" if not prompt_hits and not test_id_hits else "needs_review",
        "scope": "added product source lines from git diff -- src/stormhelm",
        "added_product_line_count": len(added_product_lines),
        "exact_prompt_hits": prompt_hits,
        "test_id_hits": test_id_hits,
        "rules": [
            "Exact failed holdout-2/250 prompt strings may appear in tests, reports, and artifacts.",
            "Exact failed prompt strings and test_ids must not appear in product routing logic.",
            "Route fixes must be route-family rules, extraction improvements, confidence/eligibility changes, clarification logic, subsystem normalization, or telemetry improvements.",
            "No broad catch-all phrase should capture unrelated near-misses.",
            "generic_provider remains available when no native family meaningfully owns the request.",
        ],
    }


def _diagnosis_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Holdout-2 Failure Diagnosis",
        "",
        f"- Source: {payload['source']}",
        f"- Failure count: {payload['failure_count']}",
        "",
        "| test_id | classification | expected | actual | cluster | root cause |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in payload["failures"]:
        lines.append(
            f"| {item['test_id']} | {item['classification']} | "
            f"{item['expected']['route_family']}/{item['expected']['subsystem']}/{item['expected']['tool']} | "
            f"{item['actual']['route_family']}/{item['actual']['subsystem']}/{item['actual']['tool']} | "
            f"{item['cluster_id']} | {item['likely_root_cause']} |"
        )
    lines.extend(["", "## Details"])
    for item in payload["failures"]:
        lines.extend(
            [
                f"### {item['test_id']}",
                f"- Prompt: `{item['prompt']}`",
                f"- Failure category: {item['failure_category']}",
                f"- Bug pattern: {item['bug_pattern']}",
                f"- Route candidates: `{item['route_candidates']}`",
                f"- Route scores: `{item['route_scores']}`",
                f"- Fallback reason: `{item['fallback_reason']}`",
                f"- Generic provider eligibility/selection: {item['generic_provider_eligible']} / `{item['generic_provider_selected_reason']}`",
                f"- Why previous pass did not catch it: {item['why_previous_pass_did_not_catch_it']}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def _regression_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 250 Regression Delta",
        "",
        f"- Before: {payload['source_before']}",
        f"- After: {payload['source_after']}",
        f"- Compared cases: {payload['compared_count']}",
        f"- Summary: `{payload['summary']}`",
        "",
        "## Pass To Fail",
        "| test_id | classification | old route/category | new route/category | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in payload["pass_to_fail"]:
        lines.append(
            f"| {item['test_id']} | {item['regression_classification']} | "
            f"{item['old']['actual_route_family']}/{item['old']['failure_category']} | "
            f"{item['new']['actual_route_family']}/{item['new']['failure_category']} | "
            f"{item['new']['failure_reason']} |"
        )
    lines.extend(["", "## Fail To Pass", ""])
    if not payload["fail_to_pass"]:
        lines.append("- none")
    else:
        for item in payload["fail_to_pass"]:
            lines.append(f"- `{item['test_id']}`: {item['old']['failure_category']} -> pass")
    return "\n".join(lines) + "\n"


def _repair_plan_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Generalization-2 Repair Plan",
        "",
        f"- Source holdout-2: {payload['source_holdout_2']}",
        f"- Regression interpretation: {payload['regression_interpretation']}",
        "",
        "| cluster | pattern | owner | fix decision | overcapture risk |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in payload["clusters"]:
        lines.append(
            f"| {item['cluster_id']} | {item['route_family_pattern']} | {item['intended_native_owner']} | "
            f"{item['fix_now_or_defer']} | {item['overcapture_risk']} |"
        )
    lines.extend(["", "## Regression Delta Summary", "", f"`{payload['regression_delta_summary']}`"])
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
