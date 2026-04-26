from __future__ import annotations

import json
import subprocess
from collections import Counter
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any


SOURCE_DIR = Path(".artifacts") / "command-usability-eval" / "generalization-overcapture-pass-2"
SOURCE_RESULTS = SOURCE_DIR / "250_post_generalization_2_results.jsonl"
OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "readiness-pass-3"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _read_jsonl(SOURCE_RESULTS)
    failures = [row for row in rows if not row.get("passed")]
    census = _failure_census(failures)
    calc = _calculation_diagnosis(failures)
    approval = _approval_policy_audit(failures)
    response = _response_correctness_audit(failures)
    wrong = _wrong_subsystem_audit(failures)
    latency = _latency_audit(failures)
    static = _static_anti_overfitting_check(failures)
    provider_audit = _ai_provider_seam_audit(rows)
    _write_pair("current_failure_census", census, _census_markdown(census))
    _write_pair("calculation_deictic_followup_diagnosis", calc, _calc_markdown(calc))
    _write_pair("approval_policy_audit", approval, _approval_markdown(approval))
    _write_pair("response_correctness_audit", response, _response_markdown(response))
    _write_pair("wrong_subsystem_audit", wrong, _wrong_markdown(wrong))
    _write_pair("latency_issue_audit", latency, _latency_markdown(latency))
    _write_pair("ai_provider_seam_audit", provider_audit, _provider_audit_markdown(provider_audit))
    (OUTPUT_DIR / "static_anti_overfitting_check.md").write_text(_static_markdown(static), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_dir": str(OUTPUT_DIR),
                "source_rows": len(rows),
                "failures": len(failures),
                "static_check": static["status"],
                "ai_provider_seams": len(provider_audit["seams"]),
            },
            indent=2,
        )
    )


def _failure_census(failures: list[dict[str, Any]]) -> dict[str, Any]:
    cluster_counts: dict[str, int] = Counter()
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in failures:
        key = "|".join(
            [
                str(row.get("failure_category") or ""),
                str(row.get("expected_route_family") or ""),
                str(row.get("actual_route_family") or ""),
                str(row.get("expected_subsystem") or ""),
                str(row.get("actual_subsystem") or ""),
                ",".join(str(item) for item in row.get("expected_tool") or []),
                ",".join(str(item) for item in row.get("actual_tool") or []),
                str(row.get("wording_style") or _wording_from_tags(row)),
                _likely_fix_area(row),
            ]
        )
        cluster_counts[key] += 1
        clusters[key].append(_failure_item(row))
    cluster_payloads = []
    for index, (key, count) in enumerate(cluster_counts.most_common(), start=1):
        parts = key.split("|")
        cluster_payloads.append(
            {
                "cluster_id": f"RP3-{index:03d}",
                "failure_category": parts[0],
                "expected_route_family": parts[1],
                "actual_route_family": parts[2],
                "expected_subsystem": parts[3],
                "actual_subsystem": parts[4],
                "expected_tool": parts[5],
                "actual_tool": parts[6],
                "wording_style": parts[7],
                "likely_fix_area": parts[8],
                "failure_count": count,
                "examples": clusters[key][:8],
            }
        )
    return {
        "source": str(SOURCE_RESULTS),
        "failure_count": len(failures),
        "counts": {
            "by_failure_category": dict(Counter(row.get("failure_category") for row in failures)),
            "by_expected_route_family": dict(Counter(row.get("expected_route_family") for row in failures)),
            "by_actual_route_family": dict(Counter(row.get("actual_route_family") for row in failures)),
            "by_wording_style": dict(Counter(row.get("wording_style") or _wording_from_tags(row) for row in failures)),
        },
        "clusters": cluster_payloads,
        "all_failures": [_failure_item(row) for row in failures],
    }


def _calculation_diagnosis(failures: list[dict[str, Any]]) -> dict[str, Any]:
    calc_rows = [row for row in failures if row.get("expected_route_family") == "calculations"]
    items = []
    for row in calc_rows:
        item = _failure_item(row)
        item.update(
            {
                "prior_turn_context": row.get("active_request_state") or (row.get("case") or {}).get("active_request_state"),
                "input_context": (row.get("case") or {}).get("input_context"),
                "previous_calculation_should_bind": _calc_should_bind(row),
                "deictic_binding_status": (row.get("deictic_binding_summary") or {}).get("binding_posture"),
                "root_cause": _calc_root_cause(row),
            }
        )
        items.append(item)
    return {
        "source": str(SOURCE_RESULTS),
        "cluster_count": len(items),
        "expected_behavior_laws": [
            "Direct math routes to calculations.",
            "Follow-ups stay in calculations when fresh prior calculation context exists.",
            "Deictic math binds only to fresh unambiguous numeric/calculation context.",
            "Missing/stale/ambiguous calculation context routes to native calculation clarification, not generic_provider.",
            "Conceptual non-calculation prompts must not be overcaptured.",
        ],
        "items": items,
        "root_cause_counts": dict(Counter(item["root_cause"] for item in items)),
    }


def _approval_policy_audit(failures: list[dict[str, Any]]) -> dict[str, Any]:
    policy = [
        _policy("read_only", False, False, False, False, "completed_or_status", "Do not claim external effects."),
        _policy("dry_run_plan", False, False, False, False, "dry_run", "Say no action was performed."),
        _policy("internal_command_deck_open", False, False, False, False, "dry_run_or_completed", "Internal surface handoff is not external execution."),
        _policy("internal_browser_or_file_surface_open", False, False, False, False, "dry_run_or_completed", "Internal open may be previewed but does not require external approval."),
        _policy("external_app_open", True, False, False, False, "dry_run", "Eval validates the route and suppresses the external handoff."),
        _policy("external_browser_open", True, False, False, False, "dry_run", "Eval validates URL handoff and suppresses execution."),
        _policy("destructive_or_mutating_local_action", True, False, True, False, "dry_run_or_blocked", "Live mutation needs approval; eval may dry-run truthfully."),
        _policy("external_message_send", True, True, True, True, "preview_or_approval_required", "Discord/external sends require preview and approval before live send."),
        _policy("software_install_update_uninstall", True, True, True, True, "preview_or_approval_required", "Software lifecycle changes require approval before live execution."),
        _policy("trust_sensitive_action", True, True, True, True, "blocked_or_approval_required", "Trust-sensitive actions need explicit approval."),
        _policy("unsupported_action", False, False, False, False, "unsupported_or_clarification", "Do not execute; explain unsupported boundary."),
    ]
    approval_rows = [
        row
        for row in failures
        if "approval" in str(row.get("failure_reason") or "").lower()
        or row.get("expected_route_family") in {"discord_relay", "system_control", "software_control", "trust_approvals"}
    ]
    audited = []
    for row in approval_rows:
        audited.append(
            {
                **_failure_item(row),
                "action_class": _approval_class(row),
                "current_expected_approval": row.get("expected_approval_state"),
                "actual_approval_state": row.get("actual_approval_state") or row.get("approval_state"),
                "recommendation": _approval_recommendation(row),
            }
        )
    return {
        "source": str(SOURCE_RESULTS),
        "policy_table": policy,
        "audited_rows": audited,
        "recommendation_counts": dict(Counter(item["recommendation"] for item in audited)),
    }


def _response_correctness_audit(failures: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in failures if row.get("failure_category") == "response_correctness_failure"]
    audited = []
    for row in rows:
        audited.append(
            {
                **_failure_item(row),
                "ui_response": row.get("ui_response"),
                "why_incorrect": row.get("failure_reason"),
                "route_correct_but_policy_mismatch": row.get("expected_route_family") == row.get("actual_route_family"),
                "overclaimed": _contains_overclaim(row.get("ui_response") or ""),
                "under_explained": False,
                "failed_to_clarify": "clarification" in str(row.get("failure_reason") or ""),
                "generic_wording_for_native_command": row.get("actual_route_family") == "generic_provider",
                "classification": _response_classification(row),
            }
        )
    return {
        "source": str(SOURCE_RESULTS),
        "count": len(audited),
        "items": audited,
        "classification_counts": dict(Counter(item["classification"] for item in audited)),
    }


def _wrong_subsystem_audit(failures: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in failures if row.get("failure_category") == "wrong_subsystem"]
    items = []
    for row in rows:
        items.append(
            {
                **_failure_item(row),
                "selected_handler": row.get("selected_handler") or _winner_field(row, "query_shape"),
                "subsystem_label_source": "command_eval normalized route/tool mapping",
                "normalized_subsystem_label": row.get("actual_subsystem"),
                "classification": _wrong_subsystem_classification(row),
                "fix_decision": "fix_route_priority_now" if row.get("expected_route_family") == "calculations" else "defer",
            }
        )
    return {"source": str(SOURCE_RESULTS), "count": len(items), "items": items}


def _latency_audit(failures: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in failures if row.get("failure_category") == "latency_issue"]
    items = []
    for row in rows:
        classification = _latency_classification(row)
        items.append(
            {
                "test_id": row.get("test_id"),
                "prompt": row.get("prompt") or row.get("input"),
                "route_family": row.get("actual_route_family"),
                "actual_subsystem": row.get("actual_subsystem"),
                "actual_tool": row.get("actual_tool"),
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
        "source": str(SOURCE_RESULTS),
        "count": len(items),
        "items": items,
        "classification_counts": dict(Counter(item["classification"] for item in items)),
        "classification_latency_summary": summaries,
    }


def _ai_provider_seam_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seams = [
        _seam(
            "src/stormhelm/core/providers/openai_responses.py",
            "OpenAIResponsesProvider.generate",
            "openai_responses",
            True,
            "generative LLM response/tool-call client",
            True,
            True,
            True,
        ),
        _seam(
            "src/stormhelm/core/orchestrator/assistant.py",
            "AssistantOrchestrator._handle_provider_turn",
            "generic assistant provider",
            False,
            "generic provider fallback planner/tool loop",
            True,
            True,
            True,
        ),
        _seam(
            "src/stormhelm/core/orchestrator/assistant.py",
            "AssistantOrchestrator._run_reasoner_summary",
            "generic assistant provider",
            False,
            "post-tool reasoner summary",
            True,
            True,
            True,
        ),
        _seam(
            "src/stormhelm/core/orchestrator/assistant.py",
            "AssistantOrchestrator._maybe_apply_browser_search_fallback",
            "generic assistant provider",
            False,
            "browser search provider URL fallback",
            True,
            True,
            True,
        ),
        _seam(
            "src/stormhelm/core/screen_awareness/service.py",
            "ScreenAwarenessSubsystem._visual_augmentation_status",
            "screen provider augmentation",
            False,
            "visual interpretation augmentation seam; currently deterministic/deferred",
            True,
            True,
            True,
        ),
        _seam(
            "src/stormhelm/core/software_recovery/service.py",
            "SoftwareRecoveryService.cloud_fallback_capability",
            "software recovery cloud fallback",
            False,
            "cloud/model recovery fallback eligibility only; no direct client call found",
            True,
            True,
            True,
        ),
        _seam(
            "src/stormhelm/core/memory/models.py",
            "MemoryRecord.semantic_embedding_ref",
            "embedding metadata",
            False,
            "embedding reference field only; no embedding client call found",
            True,
            True,
            False,
        ),
        _seam(
            "src/stormhelm/core/workspace/service.py",
            "WorkspaceService payload compaction",
            "embedding/vector payload guard",
            False,
            "filters stored embedding/vector/raw/content payload keys; no embedding client call found",
            True,
            True,
            True,
        ),
    ]
    usage = _ai_usage_from_rows(rows)
    return {
        "source": str(SOURCE_RESULTS),
        "seams": seams,
        "row_usage_summary": usage,
        "command_eval_default": {
            "provider_calls_disabled": True,
            "openai_calls_disabled": True,
            "blocked_attempts_are_recorded": True,
            "violation_rule": "Any provider/model call in command-eval is a failure unless the case is explicitly tagged provider_fallback_diagnostic/provider_allowed/ai_allowed/model_allowed.",
        },
    }


def _seam(
    path: str,
    function_class: str,
    provider_type: str,
    openai_specific: bool,
    call_purpose: str,
    instrumented: bool,
    blocked: bool,
    affects_chat_send: bool,
) -> dict[str, Any]:
    return {
        "file_path": path,
        "function_class": function_class,
        "provider_type": provider_type,
        "openai_specific": openai_specific,
        "call_purpose": call_purpose,
        "currently_instrumented": instrumented,
        "blocked_in_command_eval_mode": blocked,
        "can_affect_chat_send_command_eval_runs": affects_chat_send,
    }


def _ai_usage_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total_provider_calls": sum(int(row.get("provider_call_count") or (1 if row.get("provider_called") else 0)) for row in rows),
        "total_openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
        "total_llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
        "total_embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
        "provider_call_violations": sum(1 for row in rows if row.get("provider_call_violation")),
        "blocked_provider_attempt_rows": sum(
            1
            for row in rows
            for call in row.get("ai_provider_calls") or []
            if isinstance(call, dict) and call.get("blocked")
        ),
        "provider_calls_by_route_family": dict(
            Counter(
                row.get("actual_route_family")
                for row in rows
                if int(row.get("provider_call_count") or (1 if row.get("provider_called") else 0))
            )
        ),
        "provider_calls_by_purpose": dict(
            Counter(
                purpose
                for row in rows
                for purpose in row.get("provider_call_purposes") or []
            )
        ),
        "provider_allowed_rows": [row.get("test_id") for row in rows if row.get("provider_call_allowed")],
    }


def _static_anti_overfitting_check(failures: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = {str(row.get("prompt") or row.get("input") or "").strip().lower() for row in failures}
    test_ids = {str(row.get("test_id") or "").strip().lower() for row in failures}
    diff = subprocess.run(
        ["git", "diff", "--unified=0", "--", "src/stormhelm"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    ).stdout
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
            "Exact failed prompt strings may appear only in tests, reports, or corpus artifacts.",
            "Product routing fixes must be route-family rules, extraction improvements, clarification logic, policy alignment, or telemetry.",
            "No benchmark prompt or test-id literals in product routing logic.",
            "Near-miss and ambiguity protection must remain intact.",
        ],
    }


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
        "actual_result_state": row.get("actual_result_state") or row.get("result_state"),
        "expected_approval_state": row.get("expected_approval_state"),
        "actual_approval_state": row.get("actual_approval_state") or row.get("approval_state"),
        "route_candidates": row.get("route_candidates"),
        "route_scores": row.get("route_scores"),
        "fallback_reason": row.get("fallback_reason"),
        "generic_provider_eligible": row.get("generic_provider_eligible"),
        "generic_provider_selected_reason": row.get("generic_provider_selected_reason"),
        "result_state": row.get("result_state"),
        "failure_category": row.get("failure_category"),
        "failure_reason": row.get("failure_reason"),
        "latency_ms": row.get("latency_ms") or row.get("total_latency_ms"),
        "likely_fix_area": _likely_fix_area(row),
    }


def _likely_fix_area(row: dict[str, Any]) -> str:
    category = row.get("failure_category")
    expected = row.get("expected_route_family")
    if expected == "calculations":
        return "calculation_deictic_followup_and_embedded_expression_routing"
    if category == "response_correctness_failure" and "approval" in str(row.get("failure_reason") or ""):
        return "approval_policy_or_corpus_expectation"
    if category == "latency_issue":
        return "latency_lane_classification"
    if category == "wrong_subsystem":
        return "subsystem_route_priority"
    if row.get("actual_route_family") == "generic_provider":
        return "native_candidate_or_followup_binding"
    return "product_or_corpus_investigation"


def _wording_from_tags(row: dict[str, Any]) -> str:
    tags = (row.get("case") or {}).get("tags") or []
    for tag in ("deictic", "follow_up", "ambiguous", "near_miss", "cross_family", "canonical", "shorthand", "typo", "indirect", "explicit"):
        if tag in tags:
            return tag
    return "unknown"


def _calc_should_bind(row: dict[str, Any]) -> str:
    tags = set((row.get("case") or {}).get("tags") or [])
    case = row.get("case") or {}
    if case.get("active_request_state", {}).get("family") == "calculations":
        return "prior_route_family_available_but_no_expression_payload"
    if tags & {"deictic", "ambiguous"}:
        context = case.get("input_context") or {}
        selection = context.get("selection") if isinstance(context.get("selection"), dict) else {}
        if selection:
            value = str(selection.get("value") or "")
            return "selection_available_but_not_numeric" if not any(ch.isdigit() for ch in value) else "numeric_selection_available"
        return "missing_context"
    return "not_deictic"


def _calc_root_cause(row: dict[str, Any]) -> str:
    test_id = str(row.get("test_id") or "")
    if test_id.endswith("cross_family_00"):
        return "native_calculation_candidate_missing_for_embedded_expression"
    if test_id.endswith(("near_miss_00", "unsupported_probe_00")):
        return "calculation_native_candidate_missing_for_noisy_embedded_expression"
    if test_id.endswith(("deictic_00", "ambiguous_00")):
        return "missing_context_should_clarify"
    if test_id.endswith(("follow_up_00", "confirm_00", "correction_00")):
        return "followup_binding_missing"
    return "calculation_native_candidate_missing"


def _approval_class(row: dict[str, Any]) -> str:
    family = row.get("expected_route_family")
    tools = set(row.get("expected_tool") or [])
    if family == "discord_relay":
        return "external_message_send"
    if family == "software_control":
        return "software_install_update_uninstall"
    if family == "trust_approvals":
        return "trust_sensitive_action"
    if family == "system_control" and "system_control" in tools:
        return "dry_run_plan"
    if tools & {"external_open_file", "external_open_url", "app_control"}:
        return "external_app_open"
    return "read_only"


def _approval_recommendation(row: dict[str, Any]) -> str:
    family = row.get("expected_route_family")
    if family == "discord_relay":
        return "change_corpus_expectation_to_expected_or_preview"
    if family == "system_control" and "approval: expected 'expected_or_preview'" in str(row.get("failure_reason") or ""):
        return "change_corpus_expectation_to_not_expected_for_eval_dry_run"
    return "keep_product_failure_or_review"


def _policy(
    action_class: str,
    approval_required_live: bool,
    approval_required_eval_dry_run: bool,
    preview_required_live: bool,
    preview_required_eval_dry_run: bool,
    result_state_expectation: str,
    truthfulness_wording_expectation: str,
) -> dict[str, Any]:
    return {
        "action_class": action_class,
        "approval_required_live": approval_required_live,
        "approval_required_eval_dry_run": approval_required_eval_dry_run,
        "preview_required_live": preview_required_live,
        "preview_required_eval_dry_run": preview_required_eval_dry_run,
        "result_state_expectation": result_state_expectation,
        "truthfulness_wording_expectation": truthfulness_wording_expectation,
    }


def _response_classification(row: dict[str, Any]) -> str:
    recommendation = _approval_recommendation(row)
    if recommendation.startswith("change_corpus"):
        return "corpus_expectation_issue"
    return "product_response_or_policy_bug"


def _wrong_subsystem_classification(row: dict[str, Any]) -> str:
    if row.get("expected_route_family") == "calculations" and row.get("actual_route_family") == "app_control":
        return "true_route_bug"
    return "route_taxonomy_mismatch"


def _latency_classification(row: dict[str, Any]) -> str:
    labels = set(row.get("known_lane_labels") or [])
    if "known_workspace_latency_lane" in labels:
        return "known_workspace_latency_lane"
    family = row.get("actual_route_family")
    if family in {"file_operation", "maintenance", "routine", "software_recovery", "workflow"}:
        return "known_bounded_latency_lane"
    if float(row.get("route_handler_ms") or 0) < 500 and float(row.get("response_json_bytes") or 0) < 100_000:
        return "harness_overhead"
    return "unknown_latency_issue"


def _winner_field(row: dict[str, Any], field: str) -> Any:
    winner = (row.get("route_state") or {}).get("winner")
    return winner.get(field) if isinstance(winner, dict) else None


def _contains_overclaim(text: str) -> bool:
    lower = text.lower()
    return any(token in lower for token in {"sent it", "deleted it", "successfully installed", "verified that"})


def _write_pair(stem: str, payload: dict[str, Any], markdown: str) -> None:
    (OUTPUT_DIR / f"{stem}.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (OUTPUT_DIR / f"{stem}.md").write_text(markdown, encoding="utf-8")


def _census_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Current Failure Census", "", f"- Source: {payload['source']}", f"- Failure count: {payload['failure_count']}", "", "## Counts", ""]
    for key, value in payload["counts"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Clusters", "", "| cluster | count | category | expected -> actual | wording | likely fix |", "| --- | ---: | --- | --- | --- | --- |"])
    for cluster in payload["clusters"]:
        lines.append(
            f"| {cluster['cluster_id']} | {cluster['failure_count']} | {cluster['failure_category']} | "
            f"{cluster['expected_route_family']} -> {cluster['actual_route_family']} | {cluster['wording_style']} | {cluster['likely_fix_area']} |"
        )
    return "\n".join(lines) + "\n"


def _calc_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Calculation Deictic/Follow-Up Diagnosis", "", f"- Items: {payload['cluster_count']}", f"- Root causes: `{payload['root_cause_counts']}`", "", "| test_id | prompt | actual | root cause | binding |", "| --- | --- | --- | --- | --- |"]
    for item in payload["items"]:
        lines.append(
            f"| {item['test_id']} | {item['prompt']} | {item['actual_route_family']}/{item['actual_subsystem']} | "
            f"{item['root_cause']} | {item['deictic_binding_status']} |"
        )
    return "\n".join(lines) + "\n"


def _approval_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Approval Policy Audit", "", "## Policy Table", "", "| class | live approval | eval approval | live preview | eval preview | result state |", "| --- | --- | --- | --- | --- | --- |"]
    for row in payload["policy_table"]:
        lines.append(
            f"| {row['action_class']} | {row['approval_required_live']} | {row['approval_required_eval_dry_run']} | "
            f"{row['preview_required_live']} | {row['preview_required_eval_dry_run']} | {row['result_state_expectation']} |"
        )
    lines.extend(["", "## Audited Rows", "", "| test_id | class | expected | actual | recommendation |", "| --- | --- | --- | --- | --- |"])
    for row in payload["audited_rows"]:
        lines.append(
            f"| {row['test_id']} | {row['action_class']} | {row['current_expected_approval']} | "
            f"{row['actual_approval_state']} | {row['recommendation']} |"
        )
    return "\n".join(lines) + "\n"


def _response_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Response Correctness Audit", "", f"- Count: {payload['count']}", f"- Classification counts: `{payload['classification_counts']}`", "", "| test_id | route | reason | classification |", "| --- | --- | --- | --- |"]
    for row in payload["items"]:
        lines.append(f"| {row['test_id']} | {row['actual_route_family']} | {row['why_incorrect']} | {row['classification']} |")
    return "\n".join(lines) + "\n"


def _wrong_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Wrong-Subsystem Audit", "", f"- Count: {payload['count']}", "", "| test_id | expected -> actual | classification | fix |", "| --- | --- | --- | --- |"]
    for row in payload["items"]:
        lines.append(
            f"| {row['test_id']} | {row['expected_route_family']}/{row['expected_subsystem']} -> {row['actual_route_family']}/{row['actual_subsystem']} | "
            f"{row['classification']} | {row['fix_decision']} |"
        )
    return "\n".join(lines) + "\n"


def _latency_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Latency Issue Audit", "", f"- Count: {payload['count']}", f"- Classification counts: `{payload['classification_counts']}`", "", "## Latency Summary By Classification", ""]
    for key, value in payload["classification_latency_summary"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "| test_id | family | latency | classification |", "| --- | --- | ---: | --- |"])
    for row in payload["items"]:
        lines.append(f"| {row['test_id']} | {row['route_family']} | {row['total_latency_ms']} | {row['classification']} |")
    return "\n".join(lines) + "\n"


def _provider_audit_markdown(payload: dict[str, Any]) -> str:
    usage = payload["row_usage_summary"]
    lines = [
        "# AI / Provider Seam Audit",
        "",
        f"- Source: {payload['source']}",
        f"- Total provider calls in source rows: {usage['total_provider_calls']}",
        f"- Total OpenAI calls in source rows: {usage['total_openai_calls']}",
        f"- Total LLM calls in source rows: {usage['total_llm_calls']}",
        f"- Total embedding calls in source rows: {usage['total_embedding_calls']}",
        f"- Provider-call violations in source rows: {usage['provider_call_violations']}",
        f"- Blocked provider attempt rows: {usage['blocked_provider_attempt_rows']}",
        "",
        "## Command-Eval Rule",
        "",
        f"- Provider calls disabled by default: `{payload['command_eval_default']['provider_calls_disabled']}`",
        f"- OpenAI calls disabled by default: `{payload['command_eval_default']['openai_calls_disabled']}`",
        f"- Blocked attempts are recorded: `{payload['command_eval_default']['blocked_attempts_are_recorded']}`",
        f"- Violation rule: {payload['command_eval_default']['violation_rule']}",
        "",
        "## Seams",
        "",
        "| file/path | function/class | provider type | OpenAI-specific | purpose | instrumented | blocked in eval | affects /chat/send |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for seam in payload["seams"]:
        lines.append(
            f"| {seam['file_path']} | {seam['function_class']} | {seam['provider_type']} | "
            f"{seam['openai_specific']} | {seam['call_purpose']} | {seam['currently_instrumented']} | "
            f"{seam['blocked_in_command_eval_mode']} | {seam['can_affect_chat_send_command_eval_runs']} |"
        )
    lines.extend(
        [
            "",
            "## Provider Calls By Route Family",
            "",
            f"`{usage['provider_calls_by_route_family']}`",
            "",
            "## Provider Calls By Purpose",
            "",
            f"`{usage['provider_calls_by_purpose']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _static_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Static Anti-Overfitting Check",
        "",
        f"- Status: {payload['status']}",
        f"- Scope: {payload['scope']}",
        f"- Added product line count: {payload['added_product_line_count']}",
        f"- Exact prompt hits: {len(payload['exact_prompt_hits'])}",
        f"- Test-id hits: {len(payload['test_id_hits'])}",
        "",
        "## Rules",
    ]
    lines.extend(f"- {rule}" for rule in payload["rules"])
    if payload["exact_prompt_hits"]:
        lines.extend(["", "## Exact Prompt Hits"])
        lines.extend(f"- `{item['prompt']}` in `{item['line']}`" for item in payload["exact_prompt_hits"])
    if payload["test_id_hits"]:
        lines.extend(["", "## Test ID Hits"])
        lines.extend(f"- `{item['test_id']}` in `{item['line']}`" for item in payload["test_id_hits"])
    return "\n".join(lines) + "\n"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    main()
