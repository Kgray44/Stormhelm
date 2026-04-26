from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / ".artifacts" / "command-usability-eval" / "router-architecture-reset"
PLANNER = ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "planner.py"
ROUTE_CONTEXT = ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "route_context.py"
CORPUS = ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "command_eval" / "corpus.py"

RUNS = {
    "original_250": ROOT / ".artifacts" / "command-usability-eval" / "250-checkpoint" / "250_results.jsonl",
    "post_remediation": ROOT / ".artifacts" / "command-usability-eval" / "250-remediation" / "250_post_remediation_results.jsonl",
    "post_generalization": ROOT
    / ".artifacts"
    / "command-usability-eval"
    / "generalization-overcapture-pass"
    / "250_post_generalization_results.jsonl",
    "post_generalization_2": ROOT
    / ".artifacts"
    / "command-usability-eval"
    / "generalization-overcapture-pass-2"
    / "250_post_generalization_2_results.jsonl",
    "post_readiness_3": ROOT
    / ".artifacts"
    / "command-usability-eval"
    / "readiness-pass-3"
    / "250_post_readiness_3_results.jsonl",
    "post_context_arbitration": ROOT
    / ".artifacts"
    / "command-usability-eval"
    / "context-arbitration-pass"
    / "250_post_context_arbitration_results.jsonl",
    "holdout_4": ROOT / ".artifacts" / "command-usability-eval" / "readiness-pass-3" / "holdout_4_results.jsonl",
    "holdout_5": ROOT
    / ".artifacts"
    / "command-usability-eval"
    / "context-arbitration-pass"
    / "holdout_5_results.jsonl",
}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    diagnosis = architecture_diagnosis()
    burndown = persistent_failure_burndown()
    intent_design = intent_frame_design()
    spec_design = route_family_spec_design()
    _write_pair("router_architecture_diagnosis", diagnosis, architecture_markdown(diagnosis))
    _write_pair("persistent_failure_burndown", burndown, burndown_markdown(burndown))
    _write_pair("intent_frame_design", intent_design, intent_markdown(intent_design))
    _write_pair("route_family_spec_design", spec_design, spec_markdown(spec_design))
    print(
        json.dumps(
            {
                "output_dir": str(OUTPUT_DIR),
                "planner_one_off_heuristic_branches": diagnosis["planner_metrics"]["one_off_phrase_heuristic_branches"],
                "persistent_failures": len(burndown["persistent_failures"]),
                "route_family_specs": len(spec_design["route_family_specs"]),
            },
            indent=2,
        )
    )


def architecture_diagnosis() -> dict[str, Any]:
    planner_text = _read_text(PLANNER)
    route_context_text = _read_text(ROUTE_CONTEXT)
    corpus_text = _read_text(CORPUS)
    source_metrics = _source_metrics(planner_text, route_context_text, corpus_text)
    families = [
        _family_status(
            "calculations",
            evidence=[
                "src/stormhelm/core/calculations/planner.py",
                "src/stormhelm/core/calculations/normalizer.py",
                "src/stormhelm/core/orchestrator/planner.py",
            ],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=True,
            required_context=True,
            clarification=True,
            generic_fallback_risk=True,
            overcapture_risk=True,
            typed_target_extraction="partial",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "browser_destination",
            evidence=[
                "src/stormhelm/core/orchestrator/browser_destinations.py",
                "src/stormhelm/core/orchestrator/route_context.py",
                "src/stormhelm/core/orchestrator/planner.py",
            ],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=True,
            required_context=True,
            clarification=True,
            generic_fallback_risk=True,
            overcapture_risk=True,
            typed_target_extraction="partial",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "app_control",
            evidence=["src/stormhelm/core/orchestrator/planner.py", "src/stormhelm/core/tools/builtins/__init__.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=True,
            required_context=False,
            clarification=False,
            generic_fallback_risk=False,
            overcapture_risk=True,
            typed_target_extraction="weak",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "file",
            evidence=["src/stormhelm/core/orchestrator/route_context.py", "src/stormhelm/core/orchestrator/planner.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=True,
            required_context=True,
            clarification=True,
            generic_fallback_risk=True,
            overcapture_risk=True,
            typed_target_extraction="partial",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "file_operation",
            evidence=["src/stormhelm/core/orchestrator/route_context.py", "src/stormhelm/core/orchestrator/planner.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=False,
            required_context=True,
            clarification=True,
            generic_fallback_risk=True,
            overcapture_risk=False,
            typed_target_extraction="weak",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "context_action",
            evidence=["src/stormhelm/core/orchestrator/route_context.py", "src/stormhelm/core/context/service.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=True,
            required_context=True,
            clarification=True,
            generic_fallback_risk=True,
            overcapture_risk=True,
            typed_target_extraction="partial",
            bypasses_common_arbitration=False,
        ),
        _family_status(
            "screen_awareness",
            evidence=["src/stormhelm/core/screen_awareness/planner.py", "src/stormhelm/core/orchestrator/planner.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=True,
            required_context=True,
            clarification=True,
            generic_fallback_risk=True,
            overcapture_risk=True,
            typed_target_extraction="partial",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "workspace_operations",
            evidence=["src/stormhelm/core/workspace/service.py", "src/stormhelm/core/orchestrator/planner.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=False,
            required_context=False,
            clarification=False,
            generic_fallback_risk=False,
            overcapture_risk=False,
            typed_target_extraction="weak",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "routine",
            evidence=["src/stormhelm/core/orchestrator/planner.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=False,
            required_context=True,
            clarification=True,
            generic_fallback_risk=True,
            overcapture_risk=False,
            typed_target_extraction="weak",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "workflow",
            evidence=["src/stormhelm/core/orchestrator/planner.py", "src/stormhelm/core/tasks/service.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=False,
            required_context=False,
            clarification=False,
            generic_fallback_risk=True,
            overcapture_risk=True,
            typed_target_extraction="weak",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "task_continuity",
            evidence=["src/stormhelm/core/orchestrator/planner.py", "src/stormhelm/core/workspace/service.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=False,
            required_context=True,
            clarification=False,
            generic_fallback_risk=True,
            overcapture_risk=True,
            typed_target_extraction="weak",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "discord_relay",
            evidence=["src/stormhelm/core/orchestrator/planner.py", "src/stormhelm/core/discord_relay/service.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=False,
            required_context=True,
            clarification=True,
            generic_fallback_risk=True,
            overcapture_risk=True,
            typed_target_extraction="partial",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "software_control",
            evidence=["src/stormhelm/core/software_control/planner.py", "src/stormhelm/core/orchestrator/planner.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=True,
            required_context=False,
            clarification=False,
            generic_fallback_risk=False,
            overcapture_risk=True,
            typed_target_extraction="partial",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "watch_runtime",
            evidence=["src/stormhelm/core/orchestrator/route_context.py", "src/stormhelm/core/orchestrator/planner.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=True,
            required_context=False,
            clarification=False,
            generic_fallback_risk=False,
            overcapture_risk=True,
            typed_target_extraction="weak",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "maintenance",
            evidence=["src/stormhelm/core/orchestrator/planner.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=False,
            required_context=False,
            clarification=False,
            generic_fallback_risk=False,
            overcapture_risk=False,
            typed_target_extraction="weak",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "trust_approvals",
            evidence=["src/stormhelm/core/orchestrator/route_context.py", "src/stormhelm/core/trust/service.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=False,
            required_context=True,
            clarification=True,
            generic_fallback_risk=True,
            overcapture_risk=False,
            typed_target_extraction="weak",
            bypasses_common_arbitration=False,
        ),
        _family_status(
            "terminal",
            evidence=["src/stormhelm/core/orchestrator/planner.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=False,
            required_context=False,
            clarification=False,
            generic_fallback_risk=True,
            overcapture_risk=True,
            typed_target_extraction="weak",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "desktop_search",
            evidence=["src/stormhelm/core/orchestrator/planner.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=False,
            required_context=False,
            clarification=True,
            generic_fallback_risk=True,
            overcapture_risk=True,
            typed_target_extraction="partial",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "power",
            evidence=["src/stormhelm/core/orchestrator/planner.py", "src/stormhelm/core/tools/builtins/system_state.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=True,
            required_context=False,
            clarification=False,
            generic_fallback_risk=False,
            overcapture_risk=True,
            typed_target_extraction="partial",
            bypasses_common_arbitration=True,
        ),
        _family_status(
            "machine",
            evidence=["src/stormhelm/core/orchestrator/planner.py", "src/stormhelm/core/system/probe.py"],
            centralized=False,
            phrase_checks=True,
            near_miss_guards=True,
            required_context=False,
            clarification=False,
            generic_fallback_risk=False,
            overcapture_risk=True,
            typed_target_extraction="partial",
            bypasses_common_arbitration=True,
        ),
    ]
    return {
        "sources": {
            "planner": str(PLANNER.relative_to(ROOT)),
            "route_context": str(ROUTE_CONTEXT.relative_to(ROOT)),
            "corpus": str(CORPUS.relative_to(ROOT)),
        },
        "planner_metrics": source_metrics,
        "summary_answers": {
            "where_rules_defined": [
                "Most route-family rules are in DeterministicPlanner._semantic_parse_proposal and helper methods.",
                "Several families also have seams: calculations, software_control, screen_awareness, browser_destinations.",
                "Recent context/deictic fixes live in route_context.py but do not replace planner.py branch ordering.",
            ],
            "centralized_vs_scattered": "Scattered. The planner collects seam results, route_context arbitration, phrase helpers, direct tool proposals, and fallback candidates in one ordered function.",
            "route_context_usage": "DeterministicPlanner owns a RouteContextArbitrator and calls _route_context_arbitration_request early in _semantic_parse_proposal after trust/search/calculation/deictic-open prechecks.",
            "route_context_authority": "Advisory and early-return for matched contexts, not globally authoritative. Many route decisions never consult RouteContextArbitrator or RouteFamily contracts.",
            "one_off_phrase_heuristics": source_metrics["one_off_phrase_heuristic_branches"],
            "branches_to_move_to_contracts": [
                "workspace _looks_like_* chain",
                "network/watch/runtime status checks",
                "app/software/file/browser open boundary checks",
                "routine/workflow/task continuity checks",
                "discord/trust missing-context checks",
                "selected/highlighted text checks",
                "screen visible UI action checks",
            ],
            "bypass_common_arbitration": [
                family["route_family"] for family in families if family["bypasses_common_arbitration"]
            ],
        },
        "route_family_status": families,
        "architecture_risks": [
            {
                "risk": "ordered_branch_shadowing",
                "detail": "Earlier phrase branches can capture intent before later family-specific logic gets a chance.",
            },
            {
                "risk": "missing_context_falls_to_provider",
                "detail": "Some native-owned deictic/follow-up prompts still reach generic_provider when no context is bound.",
            },
            {
                "risk": "conceptual_overcapture",
                "detail": "Action/status keywords can capture conceptual prompts unless every family repeats negative guards.",
            },
            {
                "risk": "telemetry_not_contractual",
                "detail": "Route decline reasons are present for some candidates, but not generated consistently from shared family contracts.",
            },
            {
                "risk": "typed_target_extraction_gap",
                "detail": "Targets are extracted by family-specific regexes; no common target_type/operation/risk frame currently drives ownership.",
            },
        ],
    }


def persistent_failure_burndown() -> dict[str, Any]:
    run_rows = {name: _read_jsonl(path) for name, path in RUNS.items() if path.exists()}
    by_run = {name: {str(row.get("test_id")): row for row in rows} for name, rows in run_rows.items()}
    ordered_250 = [
        "original_250",
        "post_remediation",
        "post_generalization",
        "post_generalization_2",
        "post_readiness_3",
        "post_context_arbitration",
    ]
    all_test_ids = sorted({test_id for run_name in ordered_250 for test_id in by_run.get(run_name, {})})
    classifications: list[dict[str, Any]] = []
    for test_id in all_test_ids:
        states = []
        for run_name in ordered_250:
            row = by_run.get(run_name, {}).get(test_id)
            if row is None:
                states.append({"run": run_name, "present": False, "passed": None})
                continue
            states.append(
                {
                    "run": run_name,
                    "present": True,
                    "passed": bool(row.get("passed")),
                    "failure_category": row.get("failure_category"),
                    "expected_route_family": row.get("expected_route_family"),
                    "actual_route_family": row.get("actual_route_family"),
                    "known_lane_labels": row.get("known_lane_labels") or [],
                }
            )
        present_states = [state for state in states if state["present"]]
        pass_flags = [bool(state["passed"]) for state in present_states]
        category = _burndown_category(pass_flags, present_states)
        classifications.append(
            {
                "test_id": test_id,
                "classification": category,
                "final_failure_category": present_states[-1].get("failure_category") if present_states else None,
                "expected_route_family": present_states[-1].get("expected_route_family") if present_states else None,
                "actual_route_family": present_states[-1].get("actual_route_family") if present_states else None,
                "states": states,
            }
        )
    holdout_failures = []
    for run_name in ("holdout_4", "holdout_5"):
        for row in run_rows.get(run_name, []):
            if not row.get("passed"):
                holdout_failures.append(
                    {
                        "run": run_name,
                        "test_id": row.get("test_id"),
                        "prompt": row.get("prompt") or row.get("input"),
                        "failure_category": row.get("failure_category"),
                        "expected_route_family": row.get("expected_route_family"),
                        "actual_route_family": row.get("actual_route_family"),
                        "root_architecture_issue": _architecture_issue(row),
                    }
                )
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in classifications:
        if item["classification"] in {"failed_every_run", "fixed_then_regressed", "newly_failed_after_stricter_routing"}:
            clusters[_architecture_issue(item)].append(item)
    for item in holdout_failures:
        clusters[item["root_architecture_issue"]].append(item)
    cluster_payloads = [
        {
            "cluster_id": f"ARCH-{index:03d}",
            "root_architecture_issue": issue,
            "count": len(items),
            "examples": items[:10],
        }
        for index, (issue, items) in enumerate(sorted(clusters.items(), key=lambda kv: len(kv[1]), reverse=True), start=1)
    ]
    latest_rows = run_rows.get("post_context_arbitration", [])
    latest_failures = [row for row in latest_rows if not row.get("passed")]
    return {
        "runs": {name: {"path": str(path), "rows": len(run_rows.get(name, []))} for name, path in RUNS.items()},
        "classification_counts": dict(Counter(item["classification"] for item in classifications)),
        "persistent_failures": [item for item in classifications if item["classification"] == "failed_every_run"],
        "fixed_then_regressed": [item for item in classifications if item["classification"] == "fixed_then_regressed"],
        "newly_failed_after_stricter_routing": [
            item for item in classifications if item["classification"] == "newly_failed_after_stricter_routing"
        ],
        "holdout_generalization_failures": holdout_failures,
        "latest_250_failure_counts": dict(Counter(row.get("failure_category") for row in latest_failures)),
        "top_architecture_clusters": cluster_payloads,
    }


def intent_frame_design() -> dict[str, Any]:
    fields = [
        ("raw_text", "string", "Original user utterance."),
        ("normalized_text", "string", "Normalized, invocation-stripped command text."),
        ("invocation_prefix_removed", "boolean", "Whether Stormhelm/command prefix was removed."),
        (
            "speech_act",
            [
                "command",
                "question",
                "status_check",
                "comparison",
                "explanation_request",
                "followup",
                "correction",
                "ambiguous",
            ],
            "High-level utterance act.",
        ),
        (
            "operation",
            [
                "open",
                "close",
                "quit",
                "launch",
                "calculate",
                "explain",
                "compare",
                "send",
                "save",
                "assemble",
                "inspect",
                "search",
                "verify",
                "install",
                "uninstall",
                "update",
                "repair",
                "status",
                "unknown",
            ],
            "Normalized operator intent.",
        ),
        (
            "target_type",
            [
                "app",
                "file",
                "folder",
                "url",
                "website",
                "selected_text",
                "visible_ui",
                "prior_result",
                "prior_calculation",
                "workspace",
                "routine",
                "discord_recipient",
                "software_package",
                "system_resource",
                "unknown",
            ],
            "Best typed target.",
        ),
        ("target_text", "string", "Text span for the target, if any."),
        ("extracted_entities", "object", "Structured target candidates and quantities."),
        (
            "context_reference",
            [
                "none",
                "this",
                "that",
                "selected",
                "highlighted",
                "current_page",
                "current_file",
                "current_app",
                "previous_result",
                "previous_calculation",
                "visible_target",
            ],
            "Deictic/follow-up reference kind.",
        ),
        ("context_status", ["available", "missing", "stale", "ambiguous", "unsupported"], "Context binding status."),
        (
            "risk_class",
            [
                "read_only",
                "dry_run_plan",
                "internal_surface_open",
                "external_app_open",
                "external_browser_open",
                "local_mutation",
                "destructive",
                "external_send",
                "software_lifecycle",
            ],
            "Safety/approval class.",
        ),
        ("candidate_route_families", "list[string]", "Native families with nonzero ownership."),
        ("native_owner_hint", "string|null", "Best native owner before scoring."),
        ("clarification_needed", "boolean", "Whether a native owner lacks required context."),
        ("clarification_reason", "string", "Missing/stale/ambiguous context reason."),
        ("generic_provider_allowed", "boolean", "Only true after native families decline."),
        ("generic_provider_reason", "string", "Reason generic is allowed or blocked."),
    ]
    return {
        "purpose": "A typed intermediate frame that separates utterance parsing from route-family scoring.",
        "fields": [
            {"name": name, "type_or_values": values, "description": description}
            for name, values, description in fields
        ],
        "extraction_order": [
            "normalize and remove invocation prefix",
            "detect speech_act and operation",
            "extract explicit targets and entities",
            "resolve context_reference against active_context/active_request_state/recent_tool_results",
            "assign risk_class from operation and target_type",
            "ask RouteFamilySpec registry for candidate_route_families",
            "set generic_provider_allowed only after native decline reasons are known",
        ],
        "telemetry_contract": [
            "intent_frame",
            "intent_frame.extracted_entities",
            "intent_frame.context_status",
            "intent_frame.generic_provider_allowed",
            "intent_frame.generic_provider_reason",
        ],
    }


def route_family_spec_design() -> dict[str, Any]:
    specs = [
        _spec(
            "calculations",
            "calculations",
            operations=["calculate", "verify", "explain", "compare"],
            targets=["prior_calculation", "prior_result", "unknown"],
            required_context=["prior_calculation for deictic/follow-up math"],
            allowed_context=["prior_calculation", "prior_result", "selected_text"],
            disallowed_context=["app", "website"],
            risks=["read_only"],
            positive=["arithmetic operators", "numeric expression", "answer/compute/solve", "previous answer/result"],
            negative=["calculator app", "math teaching ideas", "neural network comparison without numeric context"],
            near=["open Calculator", "compare neural networks", "why is multiplication useful"],
            missing="route calculations and clarify for calculation_context",
            tools=[],
        ),
        _spec(
            "browser_destination",
            "browser",
            operations=["open", "search", "inspect"],
            targets=["url", "website", "current_page"],
            required_context=["url/website/current_page for deictic opens"],
            allowed_context=["current_page", "url", "website"],
            disallowed_context=["app", "file"],
            risks=["external_browser_open", "internal_surface_open"],
            positive=["url", "website", "page", "site", "link"],
            negative=["open app", "software install", "file path"],
            near=["open link-building ideas", "what is a website", "open Chrome"],
            missing="route browser_destination and clarify for destination_context",
            tools=["external_open_url", "deck_open_url"],
        ),
        _spec(
            "app_control",
            "system",
            operations=["open", "launch", "close", "quit"],
            targets=["app", "current_app"],
            required_context=["app target for deictic close/quit/open"],
            allowed_context=["app", "current_app"],
            disallowed_context=["software_package when install/update/uninstall", "website", "file"],
            risks=["external_app_open"],
            positive=["launch/open/quit/close app", "focus window"],
            negative=["install/update/uninstall/repair", "open that website", "open file path"],
            near=["quit procrastinating", "open source idea", "close reading notes"],
            missing="route app_control and clarify for app target if the verb is app-owned",
            tools=["app_control", "window_control"],
        ),
        _spec(
            "file",
            "files",
            operations=["open", "inspect"],
            targets=["file", "folder", "current_file"],
            required_context=["file path or current_file for deictic file references"],
            allowed_context=["file", "folder", "current_file"],
            disallowed_context=["app", "website"],
            risks=["internal_surface_open", "read_only"],
            positive=["file/document/doc/path/read/open"],
            negative=["app launch", "website page", "conceptual file naming"],
            near=["what is a file", "file naming philosophy"],
            missing="route file and clarify for file_context",
            tools=["deck_open_file", "external_open_file", "file_reader"],
        ),
        _spec(
            "file_operation",
            "files",
            operations=["save", "update", "repair"],
            targets=["file", "folder", "current_file"],
            required_context=["file/folder target for rename/move/tag/delete"],
            allowed_context=["file", "folder", "current_file"],
            disallowed_context=["app", "website"],
            risks=["local_mutation", "destructive"],
            positive=["rename/move/delete/tag/archive file"],
            negative=["rename an app idea", "move on emotionally"],
            near=["rename this concept", "archive old memories"],
            missing="route file_operation and clarify for file_context",
            tools=["file_operation"],
        ),
        _spec(
            "context_action",
            "context",
            operations=["explain", "save", "assemble", "inspect"],
            targets=["selected_text", "highlighted"],
            required_context=["selected/highlighted text or clipboard"],
            allowed_context=["selected_text", "highlighted"],
            disallowed_context=["website", "app"],
            risks=["read_only", "dry_run_plan"],
            positive=["selected/highlighted/clipboard text"],
            negative=["selection bias concept", "highlighted typography ideas"],
            near=["what is selected text in HTML"],
            missing="route context_action and clarify for context",
            tools=["context_action"],
        ),
        _spec(
            "screen_awareness",
            "screen_awareness",
            operations=["inspect", "open", "verify"],
            targets=["visible_ui", "visible_target"],
            required_context=["visible screen grounding before UI action"],
            allowed_context=["visible_ui", "visible_target"],
            disallowed_context=["conceptual screen topic"],
            risks=["read_only", "dry_run_plan"],
            positive=["button/menu/icon/field/panel visible target"],
            negative=["screenwriting", "coverage summary", "conceptual screen question"],
            near=["press coverage summary", "click that"],
            missing="route screen_awareness and clarify/ground before acting",
            tools=[],
        ),
        _spec(
            "workspace_operations",
            "workspace",
            operations=["assemble", "save", "open", "search"],
            targets=["workspace"],
            required_context=[],
            allowed_context=["workspace", "file", "folder"],
            disallowed_context=["conceptual workspace article"],
            risks=["read_only", "dry_run_plan", "local_mutation"],
            positive=["workspace/project setup/docs workspace"],
            negative=["workspace design theory"],
            near=["what is a workspace", "workspace philosophy"],
            missing="clarify only when target workspace is ambiguous",
            tools=["workspace_restore", "workspace_assemble", "workspace_save", "workspace_list"],
        ),
        _spec(
            "routine",
            "routine",
            operations=["save", "open", "launch"],
            targets=["routine", "prior_result"],
            required_context=["routine name for execute, bounded active context for save-this"],
            allowed_context=["routine", "prior_result", "workspace"],
            disallowed_context=["conceptual routine discussion"],
            risks=["dry_run_plan", "local_mutation"],
            positive=["routine/saved workflow/run cleanup"],
            negative=["daily routine advice"],
            near=["what is a routine", "routine design ideas"],
            missing="route routine and clarify for routine_context or steps_or_recent_action",
            tools=["routine_execute", "routine_save"],
        ),
        _spec(
            "workflow",
            "workflow",
            operations=["assemble", "open", "launch"],
            targets=["workspace", "routine", "unknown"],
            required_context=[],
            allowed_context=["workspace", "file", "folder"],
            disallowed_context=["conceptual workflow discussion"],
            risks=["dry_run_plan"],
            positive=["set up writing environment/workflow"],
            negative=["workflow theory"],
            near=["explain a workflow"],
            missing="clarify when the workflow target is absent",
            tools=["workflow_execute"],
        ),
        _spec(
            "task_continuity",
            "workspace",
            operations=["status", "inspect", "assemble"],
            targets=["workspace", "prior_result"],
            required_context=["workspace/task history for deictic continuation"],
            allowed_context=["workspace", "prior_result", "selected_text"],
            disallowed_context=["conceptual tasks"],
            risks=["read_only"],
            positive=["where left off/next steps/resume"],
            negative=["task management philosophy"],
            near=["what are next steps in algebra"],
            missing="route and clarify if no task/workspace continuity exists",
            tools=["workspace_where_left_off", "workspace_next_steps", "context_action"],
        ),
        _spec(
            "discord_relay",
            "discord_relay",
            operations=["send"],
            targets=["discord_recipient", "selected_text"],
            required_context=["payload and destination"],
            allowed_context=["selected_text", "prior_result", "discord_recipient"],
            disallowed_context=["general Discord discussion"],
            risks=["external_send"],
            positive=["send/share/message/post to Discord"],
            negative=["talk about Discord architecture"],
            near=["what is Discord", "message format for Discord docs"],
            missing="route discord_relay and clarify for payload/destination",
            tools=[],
        ),
        _spec(
            "software_control",
            "software_control",
            operations=["install", "uninstall", "update", "repair"],
            targets=["software_package"],
            required_context=["software package target"],
            allowed_context=["software_package"],
            disallowed_context=["app quit/open", "website", "file"],
            risks=["software_lifecycle"],
            positive=["install/update/uninstall/repair/remove software"],
            negative=["quit app", "open app", "remove text from file"],
            near=["remove anxiety", "update me on news"],
            missing="route and clarify for package target",
            tools=[],
        ),
        _spec(
            "watch_runtime",
            "operations",
            operations=["status", "inspect"],
            targets=["system_resource", "app", "current_app"],
            required_context=[],
            allowed_context=["system_resource", "app", "current_app"],
            disallowed_context=["conceptual network/app prompts"],
            risks=["read_only"],
            positive=["which apps are running/what did I miss/window status"],
            negative=["app architecture ideas", "neural network"],
            near=["which app architecture is better"],
            missing="status routes do not usually need clarification",
            tools=["active_apps", "activity_summary", "window_status"],
        ),
        _spec(
            "maintenance",
            "maintenance",
            operations=["repair", "update"],
            targets=["folder", "system_resource"],
            required_context=[],
            allowed_context=["folder", "system_resource"],
            disallowed_context=["conceptual cleanup advice"],
            risks=["dry_run_plan", "local_mutation"],
            positive=["clean up downloads/archive stale files"],
            negative=["clean writing style"],
            near=["clean up this paragraph"],
            missing="clarify destructive target if absent",
            tools=["maintenance_action"],
        ),
        _spec(
            "trust_approvals",
            "trust",
            operations=["verify", "status"],
            targets=["prior_result"],
            required_context=["active approval object"],
            allowed_context=["prior_result"],
            disallowed_context=["generic permission concept"],
            risks=["trust_sensitive_action"],
            positive=["approve/deny/allow/why confirmation"],
            negative=["approval policy discussion"],
            near=["what is approval voting"],
            missing="route trust_approvals and clarify for approval_object",
            tools=[],
        ),
        _spec(
            "terminal",
            "terminal",
            operations=["open", "launch"],
            targets=["folder", "workspace"],
            required_context=["folder/path for deictic terminal open"],
            allowed_context=["folder", "workspace", "current_file"],
            disallowed_context=["conceptual terminal discussion"],
            risks=["internal_surface_open"],
            positive=["open terminal/run command shell"],
            negative=["terminal illness", "terminal value"],
            near=["terminal velocity explanation"],
            missing="clarify for working directory when deictic",
            tools=[],
        ),
        _spec(
            "desktop_search",
            "files",
            operations=["search", "open"],
            targets=["file", "folder", "workspace"],
            required_context=[],
            allowed_context=["file", "folder", "workspace"],
            disallowed_context=["web search", "conceptual search"],
            risks=["read_only", "internal_surface_open"],
            positive=["find/search/recent files"],
            negative=["research online", "search the web"],
            near=["search algorithms explanation"],
            missing="clarify when search target is too vague",
            tools=["desktop_search", "recent_files"],
        ),
        _spec(
            "power",
            "system",
            operations=["status", "inspect"],
            targets=["system_resource"],
            required_context=[],
            allowed_context=["system_resource"],
            disallowed_context=["political power concept"],
            risks=["read_only"],
            positive=["battery/power/charging/time to empty"],
            negative=["power dynamics essay"],
            near=["explain power in physics"],
            missing="not usually required",
            tools=["power_status", "power_projection", "power_diagnosis"],
        ),
        _spec(
            "machine",
            "system",
            operations=["status", "inspect"],
            targets=["system_resource"],
            required_context=[],
            allowed_context=["system_resource"],
            disallowed_context=["machine learning concept"],
            risks=["read_only"],
            positive=["machine name/os version/this computer/timezone"],
            negative=["machine learning model comparison"],
            near=["what is machine learning"],
            missing="not usually required",
            tools=["machine_status", "resource_status"],
        ),
    ]
    return {
        "contract_model": {
            "required_fields": [
                "route_family",
                "subsystem",
                "owned_operations",
                "owned_target_types",
                "required_context_types",
                "allowed_context_types",
                "disallowed_context_types",
                "risk_classes",
                "positive_intent_signals",
                "negative_intent_signals",
                "near_miss_examples",
                "missing_context_behavior",
                "ambiguity_behavior",
                "generic_provider_allowed_when",
                "clarification_template",
                "expected_result_states",
                "tool_candidates",
                "confidence_floor",
                "overcapture_guards",
                "telemetry_fields",
            ]
        },
        "route_family_specs": specs,
    }


def _source_metrics(planner_text: str, route_context_text: str, corpus_text: str) -> dict[str, Any]:
    branch_lines = [
        line.strip()
        for line in planner_text.splitlines()
        if re.match(r"^(if|elif)\s+", line.strip())
        and any(marker in line for marker in ("lower", "_looks_like", "phrase", "token", "re.search", "startswith"))
    ]
    helper_names = re.findall(r"def (_looks_like_[a-zA-Z0-9_]+)", planner_text)
    route_context_predicates = re.findall(r"def (_looks_like_[a-zA-Z0-9_]+)", route_context_text)
    corpus_blueprints = re.findall(r'_Blueprint\(\s*"([^"]+)"', corpus_text)
    return {
        "planner_lines": planner_text.count("\n") + 1,
        "route_context_lines": route_context_text.count("\n") + 1,
        "planner_looks_like_helpers": len(helper_names),
        "planner_looks_like_helper_names": sorted(set(helper_names)),
        "route_context_predicates": len(route_context_predicates),
        "route_context_predicate_names": sorted(set(route_context_predicates)),
        "one_off_phrase_heuristic_branches": len(branch_lines),
        "one_off_phrase_heuristic_examples": branch_lines[:60],
        "corpus_blueprint_count": len(corpus_blueprints),
        "corpus_blueprint_families": sorted(set(corpus_blueprints)),
    }


def _family_status(
    route_family: str,
    *,
    evidence: list[str],
    centralized: bool,
    phrase_checks: bool,
    near_miss_guards: bool,
    required_context: bool,
    clarification: bool,
    generic_fallback_risk: bool,
    overcapture_risk: bool,
    typed_target_extraction: str,
    bypasses_common_arbitration: bool,
) -> dict[str, Any]:
    return {
        "route_family": route_family,
        "evidence_files": evidence,
        "rules_centralized": centralized,
        "relies_on_phrase_checks": phrase_checks,
        "has_negative_near_miss_guards": near_miss_guards,
        "knows_required_context": required_context,
        "clarifies_when_context_missing": clarification,
        "generic_provider_fallback_risk_when_context_missing": generic_fallback_risk,
        "conceptual_overcapture_risk": overcapture_risk,
        "typed_target_extraction": typed_target_extraction,
        "bypasses_common_arbitration": bypasses_common_arbitration,
    }


def _spec(
    route_family: str,
    subsystem: str,
    *,
    operations: list[str],
    targets: list[str],
    required_context: list[str],
    allowed_context: list[str],
    disallowed_context: list[str],
    risks: list[str],
    positive: list[str],
    negative: list[str],
    near: list[str],
    missing: str,
    tools: list[str],
) -> dict[str, Any]:
    return {
        "route_family": route_family,
        "subsystem": subsystem,
        "owned_operations": operations,
        "owned_target_types": targets,
        "required_context_types": required_context,
        "allowed_context_types": allowed_context,
        "disallowed_context_types": disallowed_context,
        "risk_classes": risks,
        "positive_intent_signals": positive,
        "negative_intent_signals": negative,
        "near_miss_examples": near,
        "missing_context_behavior": missing,
        "ambiguity_behavior": "route native and clarify when ownership is clear but bindings conflict",
        "generic_provider_allowed_when": "only when this spec has no operation/target/context ownership or all candidates decline with reasons",
        "clarification_template": missing,
        "expected_result_states": ["completed", "dry_run", "needs_clarification", "blocked_missing_context"],
        "tool_candidates": tools,
        "confidence_floor": 0.58,
        "overcapture_guards": negative,
        "telemetry_fields": [
            "intent_frame",
            "route_family_spec",
            "candidate_score",
            "score_factors",
            "decline_reasons",
            "missing_preconditions",
        ],
    }


def _burndown_category(pass_flags: list[bool], states: list[dict[str, Any]]) -> str:
    if not pass_flags:
        return "not_present"
    final = pass_flags[-1]
    if all(pass_flags):
        return "fixed_and_stayed_fixed"
    if not any(pass_flags):
        if states[-1].get("failure_category") == "latency_issue":
            return "latency_only"
        return "failed_every_run"
    if pass_flags[0] is False and final is True:
        return "fixed_and_stayed_fixed"
    if True in pass_flags and final is False:
        if states[-1].get("failure_category") == "latency_issue":
            return "latency_only"
        return "fixed_then_regressed"
    return "newly_failed_after_stricter_routing"


def _architecture_issue(row: dict[str, Any]) -> str:
    category = str(row.get("failure_category") or row.get("final_failure_category") or "")
    expected = str(row.get("expected_route_family") or "")
    actual = str(row.get("actual_route_family") or "")
    if category == "latency_issue":
        return "latency_lane_not_route_architecture"
    if actual == "generic_provider":
        return "generic_provider_gate_without_contract_declines"
    if expected == "calculations":
        return "calculation_deictic_followup_contract_gap"
    if expected in {"browser_destination", "file", "context_action"}:
        return "typed_target_context_binding_gap"
    if expected in {"screen_awareness", "app_control", "software_control", "watch_runtime"}:
        return "cross_family_operation_target_arbitration_gap"
    if category == "response_correctness_failure":
        return "native_clarification_result_state_contract_gap"
    return "scattered_phrase_branch_contract_gap"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _write_pair(name: str, payload: dict[str, Any], markdown: str) -> None:
    (OUTPUT_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (OUTPUT_DIR / f"{name}.md").write_text(markdown, encoding="utf-8")


def architecture_markdown(payload: dict[str, Any]) -> str:
    metrics = payload["planner_metrics"]
    status_rows = payload["route_family_status"]
    lines = [
        "# Router Architecture Diagnosis",
        "",
        "## Executive Summary",
        "",
        "Stormhelm routing is still dominated by ordered planner branches and family-specific phrase predicates. "
        "`route_context.py` improved deictic and missing-context behavior, but it is advisory rather than an authoritative routing contract layer.",
        "",
        "## Key Metrics",
        "",
        f"- Planner lines inspected: {metrics['planner_lines']}",
        f"- Planner `_looks_like_*` helpers: {metrics['planner_looks_like_helpers']}",
        f"- One-off phrase heuristic branches: {metrics['one_off_phrase_heuristic_branches']}",
        f"- Route-context predicates: {metrics['route_context_predicates']}",
        f"- Corpus blueprints found: {metrics['corpus_blueprint_count']}",
        "",
        "## Diagnosis Answers",
        "",
    ]
    for key, value in payload["summary_answers"].items():
        lines.append(f"- **{key}**: {value}")
    lines.extend(["", "## Route Family Status", ""])
    lines.append(
        "| Family | Phrase Checks | Near-Miss Guards | Required Context | Clarifies Missing Context | Bypasses Arbitration | Typed Target |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in status_rows:
        lines.append(
            f"| {row['route_family']} | {row['relies_on_phrase_checks']} | {row['has_negative_near_miss_guards']} | "
            f"{row['knows_required_context']} | {row['clarifies_when_context_missing']} | "
            f"{row['bypasses_common_arbitration']} | {row['typed_target_extraction']} |"
        )
    lines.extend(["", "## Architecture Risks", ""])
    for risk in payload["architecture_risks"]:
        lines.append(f"- **{risk['risk']}**: {risk['detail']}")
    return "\n".join(lines) + "\n"


def burndown_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Persistent Failure Burn-Down",
        "",
        "## Run Coverage",
        "",
    ]
    for name, meta in payload["runs"].items():
        lines.append(f"- {name}: {meta['rows']} rows ({meta['path']})")
    lines.extend(["", "## Classification Counts", ""])
    for key, count in sorted(payload["classification_counts"].items()):
        lines.append(f"- {key}: {count}")
    lines.extend(["", "## Latest 250 Failure Counts", ""])
    for key, count in sorted(payload["latest_250_failure_counts"].items()):
        lines.append(f"- {key}: {count}")
    lines.extend(["", "## Top Architecture Clusters", ""])
    for cluster in payload["top_architecture_clusters"][:12]:
        lines.append(f"- {cluster['cluster_id']} {cluster['root_architecture_issue']}: {cluster['count']}")
    lines.extend(["", "## Interpretation", ""])
    lines.append(
        "The repeated 250/holdout cycle fixed many exact clusters, but holdout failures remain concentrated in generic-provider gating, "
        "deictic/follow-up binding, and cross-family operation/target arbitration. Those are architecture issues rather than isolated prompt bugs."
    )
    return "\n".join(lines) + "\n"


def intent_markdown(payload: dict[str, Any]) -> str:
    lines = ["# IntentFrame Design", "", payload["purpose"], "", "## Fields", ""]
    lines.append("| Field | Type / Values | Description |")
    lines.append("| --- | --- | --- |")
    for field in payload["fields"]:
        values = field["type_or_values"]
        if isinstance(values, list):
            values = ", ".join(values)
        lines.append(f"| {field['name']} | {values} | {field['description']} |")
    lines.extend(["", "## Extraction Order", ""])
    for item in payload["extraction_order"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def spec_markdown(payload: dict[str, Any]) -> str:
    lines = ["# RouteFamilySpec Design", "", "## Contract Fields", ""]
    for field in payload["contract_model"]["required_fields"]:
        lines.append(f"- {field}")
    lines.extend(["", "## Family Specs", ""])
    lines.append("| Family | Subsystem | Operations | Targets | Tools |")
    lines.append("| --- | --- | --- | --- | --- |")
    for spec in payload["route_family_specs"]:
        lines.append(
            f"| {spec['route_family']} | {spec['subsystem']} | {', '.join(spec['owned_operations'])} | "
            f"{', '.join(spec['owned_target_types'])} | {', '.join(spec['tool_candidates'])} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
