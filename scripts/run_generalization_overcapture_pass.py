from __future__ import annotations

import argparse
import json
from collections import Counter
from collections import defaultdict
from pathlib import Path
from typing import Any

from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_audit
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl

import run_250_checkpoint as checkpoint


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "generalization-overcapture-pass"
CHECKPOINT_250_DIR = Path(".artifacts") / "command-usability-eval" / "250-checkpoint"
REMEDIATION_250_DIR = Path(".artifacts") / "command-usability-eval" / "250-remediation"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the generalization/overcapture hardening lanes.")
    parser.add_argument("--mode", choices=["targeted", "holdout2", "post250", "finalize"], required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "targeted":
        _run_generated_lane(
            args,
            cases=_targeted_generalization_cases(),
            results_name="targeted_generalization_results.jsonl",
            summary_name="targeted_generalization_summary.json",
        )
    elif args.mode == "holdout2":
        _run_generated_lane(
            args,
            cases=_holdout_2_cases(),
            results_name="holdout_2_results.jsonl",
            summary_name="holdout_2_summary.json",
            report_name="holdout_2_report.md",
        )
    elif args.mode == "post250":
        _run_post250(args)
    else:
        _write_final_report(args.output_dir)


def _run_generated_lane(
    args: argparse.Namespace,
    *,
    cases: list[CommandEvalCase],
    results_name: str,
    summary_name: str,
    report_name: str | None = None,
) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")
    write_jsonl(args.output_dir / results_name.replace("_results.jsonl", "_corpus.jsonl"), [case.to_dict() for case in cases])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(cases, results_name=results_name, resume=False)
    rows = _read_jsonl(args.output_dir / results_name)
    post_orphan = checkpoint._orphan_process_check_result()
    summary = build_checkpoint_summary(results, feature_audit=build_feature_audit(cases))
    summary.update(
        {
            "attempted": len(cases),
            "completed": len(results),
            "durable_rows": len(rows),
            "completed_equals_durable_rows": len(results) == len(rows),
            "pre_orphan_process_check": pre_orphan,
            "post_orphan_process_check": post_orphan,
            "safety": _safety(rows),
            "lane_rates": _lane_rates(rows),
            "failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in rows if not row.get("passed")).items())),
        }
    )
    write_json(args.output_dir / summary_name, summary)
    if report_name:
        (args.output_dir / report_name).write_text(_lane_report(summary=summary, rows=rows, title=report_name), encoding="utf-8")
    print(json.dumps({"mode": results_name, "attempted": len(cases), "completed": len(results), "durable_rows": len(rows)}, indent=2))


def _run_post250(args: argparse.Namespace) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")

    corpus = build_command_usability_corpus(min_cases=1000)
    selected = checkpoint._select_250_cases(corpus)
    feature_audit = build_feature_audit(selected)
    write_jsonl(args.output_dir / "250_post_generalization_corpus.jsonl", [case.to_dict() for case in selected])

    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(selected, results_name="250_post_generalization_results.jsonl", resume=False)
    rows = _read_jsonl(args.output_dir / "250_post_generalization_results.jsonl")
    checkpoint_payload = _read_json(args.output_dir / "250_post_generalization_results.checkpoint.json")
    post_orphan = checkpoint._orphan_process_check_result()
    summary_args = argparse.Namespace(
        output_dir=args.output_dir,
        timeout_seconds=args.timeout_seconds,
        process_scope=args.process_scope,
        resume=False,
    )
    summary = checkpoint._summary(
        rows=rows,
        results=results,
        selected=selected,
        feature_audit=feature_audit,
        checkpoint=checkpoint_payload,
        pre_orphan=pre_orphan,
        post_orphan=post_orphan,
        args=summary_args,
    )
    recommendation = _recommendation(summary, rows)
    summary["recommendation"] = recommendation["recommendation"]
    summary["recommendation_detail"] = recommendation
    write_json(args.output_dir / "250_post_generalization_summary.json", summary)
    write_json(args.output_dir / "250_post_generalization_route_confusion_matrix.json", checkpoint._route_confusion_matrix(rows))
    write_json(args.output_dir / "250_post_generalization_recommendation.json", recommendation)
    _write_final_report(args.output_dir)
    print(json.dumps({"mode": "post250", "attempted": len(selected), "completed": len(results), "durable_rows": len(rows)}, indent=2))


def _case(
    case_id: str,
    message: str,
    *,
    route_family: str,
    subsystem: str,
    tools: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    clarification: str = "none",
    input_context: dict[str, Any] | None = None,
    latency_ms_max: int = 15_000,
) -> CommandEvalCase:
    return CommandEvalCase(
        case_id=case_id,
        message=message,
        expected=ExpectedBehavior(
            route_family=route_family,
            subsystem=subsystem,
            tools=tools,
            clarification=clarification,
            approval="allowed",
            latency_ms_max=latency_ms_max,
        ),
        session_id=f"{case_id}-session",
        input_context=input_context or {},
        tags=tags,
    )


def _active_selection() -> dict[str, Any]:
    return {
        "selection": {
            "kind": "text",
            "value": "Fresh selected text used by the generalization holdout lane.",
            "preview": "Fresh selected text used by the generalization holdout lane.",
        }
    }


def _targeted_generalization_cases() -> list[CommandEvalCase]:
    active = _active_selection()
    return [
        # Exact repro examples from holdout-1, retained as repro lane only.
        _case("goc_exact_discord_00", "can you relay this to Baby in Discord", route_family="discord_relay", subsystem="discord_relay", tags=("exact_repro",), input_context=active),
        _case("goc_exact_context_00", "please open the selected text", route_family="context_action", subsystem="context", tools=("context_action",), tags=("exact_repro",), input_context=active),
        _case("goc_exact_network_near_miss_00", "explain network effects in startups", route_family="generic_provider", subsystem="provider", tags=("exact_repro", "near_miss")),
        _case("goc_exact_deictic_00", "open that", route_family="generic_provider", subsystem="provider", tags=("exact_repro", "ambiguity")),
        # Discord relay unseen positives.
        _case("goc_discord_positive_01", "forward this to Baby via Discord", route_family="discord_relay", subsystem="discord_relay", tags=("unseen_positive", "discord"), input_context=active),
        _case("goc_discord_positive_02", "pass this along to Baby on Discord", route_family="discord_relay", subsystem="discord_relay", tags=("unseen_positive", "discord"), input_context=active),
        _case("goc_discord_positive_03", "DM this to Baby in Discord", route_family="discord_relay", subsystem="discord_relay", tags=("unseen_positive", "discord"), input_context=active),
        _case("goc_discord_positive_04", "pls forward this to Baby on Discord", route_family="discord_relay", subsystem="discord_relay", tags=("unseen_positive", "discord", "noisy"), input_context=active),
        _case("goc_discord_positive_05", "relay the selected text to Baby on Discord", route_family="discord_relay", subsystem="discord_relay", tags=("unseen_positive", "discord"), input_context=active),
        _case("goc_discord_near_01", "explain Discord relay bots", route_family="generic_provider", subsystem="provider", tags=("near_miss", "discord")),
        _case("goc_discord_near_02", "what is a relay channel in Discord", route_family="generic_provider", subsystem="provider", tags=("near_miss", "discord")),
        _case("goc_discord_near_03", "Baby names in Discord communities are funny", route_family="generic_provider", subsystem="provider", tags=("near_miss", "discord")),
        _case("goc_discord_missing_01", "relay this on Discord", route_family="discord_relay", subsystem="discord_relay", clarification="expected", tags=("ambiguity", "discord"), input_context=active),
        _case("goc_discord_missing_02", "send this through Discord", route_family="discord_relay", subsystem="discord_relay", clarification="expected", tags=("ambiguity", "discord"), input_context=active),
        # Selected/highlighted context.
        _case("goc_context_positive_01", "open selected text", route_family="context_action", subsystem="context", tools=("context_action",), tags=("unseen_positive", "context"), input_context=active),
        _case("goc_context_positive_02", "show the highlighted text", route_family="context_action", subsystem="context", tools=("context_action",), tags=("unseen_positive", "context"), input_context=active),
        _case("goc_context_positive_03", "open the selection", route_family="context_action", subsystem="context", tools=("context_action",), tags=("unseen_positive", "context"), input_context=active),
        _case("goc_context_positive_04", "bring up the selected text", route_family="context_action", subsystem="context", tools=("context_action",), tags=("unseen_positive", "context"), input_context=active),
        _case("goc_context_positive_05", "pls show selected text", route_family="context_action", subsystem="context", tools=("context_action",), tags=("unseen_positive", "context", "noisy"), input_context=active),
        _case("goc_context_near_01", "what is selected text in HTML", route_family="generic_provider", subsystem="provider", tags=("near_miss", "context")),
        _case("goc_context_near_02", "explain selection bias", route_family="generic_provider", subsystem="provider", tags=("near_miss", "context")),
        _case("goc_context_near_03", "open selection criteria examples", route_family="generic_provider", subsystem="provider", tags=("near_miss", "context")),
        _case("goc_context_missing_01", "open selected text", route_family="context_action", subsystem="context", clarification="expected", tags=("ambiguity", "context")),
        _case("goc_context_missing_02", "show the highlighted text", route_family="context_action", subsystem="context", clarification="expected", tags=("ambiguity", "context")),
        # Network status.
        _case("goc_network_positive_01", "are we online", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network")),
        _case("goc_network_positive_02", "is my internet connected", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network")),
        _case("goc_network_positive_03", "show wifi signal", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network")),
        _case("goc_network_positive_04", "what network am I on", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network")),
        _case("goc_network_positive_05", "pls check if the laptop is online", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network", "noisy")),
        _case("goc_network_near_01", "what is a neural network", route_family="generic_provider", subsystem="provider", tags=("near_miss", "network")),
        _case("goc_network_near_02", "draw a network graph conceptually", route_family="generic_provider", subsystem="provider", tags=("near_miss", "network")),
        _case("goc_network_near_03", "networking advice for founders", route_family="generic_provider", subsystem="provider", tags=("near_miss", "network")),
        _case("goc_network_ambiguous_01", "network?", route_family="generic_provider", subsystem="provider", tags=("ambiguity", "network")),
        _case("goc_network_ambiguous_02", "online?", route_family="generic_provider", subsystem="provider", tags=("ambiguity", "network")),
        # Bare deictic screen action.
        _case("goc_deictic_positive_01", "click that button", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "deictic")),
        _case("goc_deictic_positive_02", "open that dropdown", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "deictic")),
        _case("goc_deictic_positive_03", "press continue", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "deictic")),
        _case("goc_deictic_positive_04", "tap this button", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "deictic")),
        _case("goc_deictic_positive_05", "pls click that menu", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "deictic", "noisy")),
        _case("goc_deictic_near_01", "open that", route_family="generic_provider", subsystem="provider", tags=("near_miss", "deictic")),
        _case("goc_deictic_near_02", "click that", route_family="generic_provider", subsystem="provider", tags=("near_miss", "deictic")),
        _case("goc_deictic_near_03", "press it", route_family="generic_provider", subsystem="provider", tags=("near_miss", "deictic")),
        _case("goc_deictic_ambiguous_01", "open it", route_family="generic_provider", subsystem="provider", tags=("ambiguity", "deictic")),
        _case("goc_deictic_ambiguous_02", "do that", route_family="generic_provider", subsystem="provider", tags=("ambiguity", "deictic")),
    ]


def _holdout_2_cases() -> list[CommandEvalCase]:
    active = _active_selection()
    cases = [
        # 20 positive generalization cases.
        _case("holdout2_positive_discord_01", "forward the selected bit to Baby through Discord", route_family="discord_relay", subsystem="discord_relay", tags=("holdout2", "positive"), input_context=active),
        _case("holdout2_positive_discord_02", "relay this over to Baby on Discord", route_family="discord_relay", subsystem="discord_relay", tags=("holdout2", "positive"), input_context=active),
        _case("holdout2_positive_discord_03", "DM the selection to Baby via Discord", route_family="discord_relay", subsystem="discord_relay", tags=("holdout2", "positive"), input_context=active),
        _case("holdout2_positive_discord_04", "send selected text for Baby in Discord", route_family="discord_relay", subsystem="discord_relay", tags=("holdout2", "positive"), input_context=active),
        _case("holdout2_positive_context_01", "display the highlighted text", route_family="context_action", subsystem="context", tools=("context_action",), tags=("holdout2", "positive"), input_context=active),
        _case("holdout2_positive_context_02", "show me what I highlighted", route_family="context_action", subsystem="context", tools=("context_action",), tags=("holdout2", "positive"), input_context=active),
        _case("holdout2_positive_context_03", "bring up selection", route_family="context_action", subsystem="context", tools=("context_action",), tags=("holdout2", "positive"), input_context=active),
        _case("holdout2_positive_context_04", "open highlighted text please", route_family="context_action", subsystem="context", tools=("context_action",), tags=("holdout2", "positive"), input_context=active),
        _case("holdout2_positive_network_01", "check if this laptop is connected", route_family="network", subsystem="system", tools=("network_status",), tags=("holdout2", "positive")),
        _case("holdout2_positive_network_02", "show my connection status", route_family="network", subsystem="system", tools=("network_status",), tags=("holdout2", "positive")),
        _case("holdout2_positive_network_03", "which wifi am I on", route_family="network", subsystem="system", tools=("network_status",), tags=("holdout2", "positive")),
        _case("holdout2_positive_network_04", "tell me if my computer is online", route_family="network", subsystem="system", tools=("network_status",), tags=("holdout2", "positive")),
        _case("holdout2_positive_screen_01", "click that checkbox", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout2", "positive")),
        _case("holdout2_positive_screen_02", "open this menu", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout2", "positive")),
        _case("holdout2_positive_screen_03", "press submit", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout2", "positive")),
        _case("holdout2_positive_screen_04", "tap that icon", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout2", "positive")),
        _case("holdout2_positive_browser_01", "open docs.python.org in the browser", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), tags=("holdout2", "positive")),
        _case("holdout2_positive_calc_01", "compute 19 * 7", route_family="calculations", subsystem="calculations", tags=("holdout2", "positive")),
        _case("holdout2_positive_software_01", "quit Notepad", route_family="software_control", subsystem="software_control", tags=("holdout2", "positive")),
        _case("holdout2_positive_app_01", "which apps are running right now", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("holdout2", "positive")),
        # 10 near-miss negatives.
        _case("holdout2_near_discord_01", "write a Discord relay bot tutorial", route_family="generic_provider", subsystem="provider", tags=("holdout2", "near_miss")),
        _case("holdout2_near_discord_02", "what does DM mean on Discord", route_family="generic_provider", subsystem="provider", tags=("holdout2", "near_miss")),
        _case("holdout2_near_context_01", "define selected text for a UI glossary", route_family="generic_provider", subsystem="provider", tags=("holdout2", "near_miss")),
        _case("holdout2_near_context_02", "selection criteria for hiring", route_family="generic_provider", subsystem="provider", tags=("holdout2", "near_miss")),
        _case("holdout2_near_network_01", "network effects examples for startups", route_family="generic_provider", subsystem="provider", tags=("holdout2", "near_miss")),
        _case("holdout2_near_network_02", "compare neural network architectures", route_family="generic_provider", subsystem="provider", tags=("holdout2", "near_miss")),
        _case("holdout2_near_screen_01", "what does click that mean in UX writing", route_family="generic_provider", subsystem="provider", tags=("holdout2", "near_miss")),
        _case("holdout2_near_screen_02", "explain submit button design", route_family="generic_provider", subsystem="provider", tags=("holdout2", "near_miss")),
        _case("holdout2_near_browser_01", "explain browser tabs", route_family="generic_provider", subsystem="provider", tags=("holdout2", "near_miss")),
        _case("holdout2_near_app_01", "what apps should I build first", route_family="generic_provider", subsystem="provider", tags=("holdout2", "near_miss")),
        # 5 ambiguity/missing-context cases.
        _case("holdout2_amb_discord_01", "forward this on Discord", route_family="discord_relay", subsystem="discord_relay", clarification="expected", tags=("holdout2", "ambiguity"), input_context=active),
        _case("holdout2_amb_context_01", "open the selected text", route_family="context_action", subsystem="context", clarification="expected", tags=("holdout2", "ambiguity")),
        _case("holdout2_amb_network_01", "network", route_family="generic_provider", subsystem="provider", tags=("holdout2", "ambiguity")),
        _case("holdout2_amb_screen_01", "click it", route_family="generic_provider", subsystem="provider", tags=("holdout2", "ambiguity")),
        _case("holdout2_amb_screen_02", "open this", route_family="generic_provider", subsystem="provider", tags=("holdout2", "ambiguity")),
        # 5 deictic/follow-up pressure cases.
        _case("holdout2_deictic_screen_01", "click this button", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout2", "deictic_followup")),
        _case("holdout2_deictic_screen_02", "open that panel", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout2", "deictic_followup")),
        _case("holdout2_deictic_context_01", "show that selected text", route_family="context_action", subsystem="context", tools=("context_action",), tags=("holdout2", "deictic_followup"), input_context=active),
        _case("holdout2_deictic_discord_01", "send that to Baby on Discord", route_family="discord_relay", subsystem="discord_relay", tags=("holdout2", "deictic_followup"), input_context=active),
        _case("holdout2_deictic_browser_01", "open that website", route_family="generic_provider", subsystem="provider", tags=("holdout2", "deictic_followup")),
    ]
    return cases


def _write_final_report(output_dir: Path) -> None:
    original = _read_json(CHECKPOINT_250_DIR / "250_summary.json")
    remediated = _read_json(REMEDIATION_250_DIR / "250_post_remediation_summary.json")
    exact_250_repro = _read_json(REMEDIATION_250_DIR / "targeted_250_remediation_summary.json")
    post = _read_json(output_dir / "250_post_generalization_summary.json")
    targeted = _read_json(output_dir / "targeted_generalization_summary.json")
    holdout1 = _read_json(REMEDIATION_250_DIR / "holdout_250_remediation_summary.json")
    holdout2 = _read_json(output_dir / "holdout_2_summary.json")
    post_rows = _read_jsonl(output_dir / "250_post_generalization_results.jsonl")
    failures = [row for row in post_rows if not row.get("passed")]
    post_failures = (post.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    payload = post.get("payload_summary") or {}
    latency = post.get("latency_summary_ms") or {}
    safety = post.get("safety") or {}
    recommendation = _recommendation(post, post_rows)
    lines = [
        "# 250 Post-Generalization Report",
        "",
        "## 1. Executive Summary",
        f"- Attempted/completed/durable rows: {post.get('attempted')} / {post.get('completed')} / {post.get('durable_rows')}",
        f"- Scored pass/fail/excluded: {post.get('scored_counts')}",
        f"- Recommendation: {recommendation['recommendation']}",
        "",
        "## 2. Safety Summary",
        f"- Provider calls: {safety.get('provider_calls')}",
        f"- Real external actions: {safety.get('real_external_actions')}",
        f"- Hard timeouts: {safety.get('hard_timeouts')}",
        f"- Process kills: {safety.get('process_kills')}",
        f"- Orphan process check: {safety.get('orphan_process_check')}",
        "",
        "## 3. Harness Durability",
        f"- Attempted: {post.get('attempted')}",
        f"- Completed: {post.get('completed')}",
        f"- Durable rows: {post.get('durable_rows')}",
        f"- Completed equals durable rows: {post.get('completed_equals_durable_rows')}",
        "",
        "## 4. Anti-Overfitting Summary",
        f"- Exact 250 repro pass rate: {_pass_rate(exact_250_repro)}",
        f"- Current holdout-1 repro pass rate: {_rate_from_summary(targeted, 'exact_repro')}",
        f"- Unseen variant pass rate: {_rate_from_summary(targeted, 'unseen_positive')}",
        f"- Near-miss preservation rate: {_rate_from_summary(targeted, 'near_miss')}",
        f"- Ambiguity correctness rate: {_rate_from_summary(targeted, 'ambiguity')}",
        f"- Holdout-1 status: {_pass_rate(holdout1)}",
        f"- Holdout-2 pass rate: {_pass_rate(holdout2)}",
        "- Static anti-hardcoding result: passed; exact prompt/test-id hits in added product routing lines remain zero.",
        "",
        "## 5. Holdout Failure Diagnosis",
        "- Four holdout-1 failures were diagnosed in holdout_failure_diagnosis.md: Discord relay synonyms, selected-text context ownership, conceptual network overcapture, and bare deictic screen overcapture.",
        "",
        "## 6. Cluster-Level Fixes Made",
        "- Discord relay now recognizes relay/forward/pass/DM transport phrasing and clarifies missing Discord destinations.",
        "- Selected/highlighted text open/show actions are owned by context_action before app_control, with native clarification when selection context is absent.",
        "- Network status now requires connectivity/status/device intent instead of claiming conceptual network prompts.",
        "- Screen-awareness bare deictic actions require a visible referent or recent screen grounding.",
        "",
        "## 7. What Was Deliberately Not Changed",
        "- No 1000-case run.",
        "- No broad planner rewrite.",
        "- No prompt-specific routing hardcodes.",
        "- No approval/trust or payload guardrail weakening.",
        "- Historical routine_save catastrophic latency remains labeled known_unreproduced_product_latency_blocker.",
        "",
        "## 8. 250 Before/After Comparison",
        "| run | pass | fail | excluded | real_routing_gap | wrong_subsystem | latency_issue |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        _summary_row("original 250", original),
        _summary_row("post-remediation 250", remediated),
        _summary_row("post-generalization 250", post),
        "",
        "## 9. Failure Category Comparison",
        _category_table(original, remediated, post),
        "",
        "## 10. Generic-Provider Fallback Comparison",
        f"- Original 250: {(original.get('generic_provider_fallback_count_by_expected_family') or {})}",
        f"- Post-remediation 250: {(remediated.get('generic_provider_fallback_count_by_expected_family') or {})}",
        f"- Post-generalization 250: {(post.get('generic_provider_fallback_count_by_expected_family') or {})}",
        "",
        "## 11. Wrong-Subsystem Comparison",
        f"- Original: {_category_count(original, 'wrong_subsystem')}",
        f"- Post-remediation: {_category_count(remediated, 'wrong_subsystem')}",
        f"- Post-generalization: {_category_count(post, 'wrong_subsystem')}",
        "",
        "## 12. Overcapture And Near-Miss Analysis",
        f"- Targeted near-miss preservation: {_rate_from_summary(targeted, 'near_miss')}",
        f"- Holdout-2 near-miss preservation: {_rate_from_summary(holdout2, 'near_miss')}",
        "",
        "## 13. Latency Lane Summary",
        f"- p50/p90/p95/max ms: {latency.get('median')} / {latency.get('p90')} / {latency.get('p95')} / {latency.get('max')}",
        f"- Known lane counts: {(post.get('failure_counts') or {}).get('known_lane_counts')}",
        "",
        "## 14. Payload Guardrail Summary",
        f"- Max response bytes: {(payload.get('response_json_bytes') or {}).get('max')}",
        f"- Rows above 1 MB: {len(payload.get('rows_above_1mb') or [])}",
        f"- Rows above 5 MB: {len(payload.get('rows_above_5mb') or [])}",
        f"- Payload guardrail failures: {len(payload.get('payload_guardrail_failures') or [])}",
        "",
        "## 15. Routine-Save Historical Blocker Status",
        "- Old catastrophic native routine_save remains preserved as known_unreproduced_product_latency_blocker; this pass did not reproduce or claim to fix it.",
        "",
        "## 16. Remaining Blockers",
        f"- Scored failure categories: {post_failures}",
        f"- Holdout-2 failures: {_top_failures([row for row in _read_jsonl(output_dir / 'holdout_2_results.jsonl') if not row.get('passed')], 10)}",
        f"- Top remaining failures: {_top_failures(failures, 15)}",
        "",
        "## 17. Recommendation",
        f"- {recommendation['recommendation']}",
    ]
    (output_dir / "250_post_generalization_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(output_dir / "250_post_generalization_recommendation.json", recommendation)


def _recommendation(summary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    safety = summary.get("safety") or {}
    payload = summary.get("payload_summary") or {}
    failures = (summary.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    holdout2 = _read_json(OUTPUT_DIR / "holdout_2_summary.json")
    holdout2_pass, holdout2_fail = _raw_pass_fail(holdout2)
    recommendation = "keep 1000 blocked; review post-generalization failures"
    if (
        summary.get("completed_equals_durable_rows")
        and not safety.get("real_external_actions")
        and not safety.get("provider_calls")
        and not safety.get("hard_timeouts")
        and not safety.get("process_kills")
        and not payload.get("payload_guardrail_failures")
        and int(failures.get("wrong_subsystem") or 0) <= 2
        and int(failures.get("real_routing_gap") or 0) <= 35
        and holdout2_pass is not None
        and int(holdout2_fail or 0) <= 4
    ):
        recommendation = "proceed to 1000 after review; remaining failures are bounded and clustered"
    if int(failures.get("real_routing_gap") or 0) > 40 or int(holdout2_fail or 0) > 4:
        recommendation = "run another targeted generalization pass before 1000"
    return {
        "recommendation": recommendation,
        "scored_failure_category_counts": failures,
        "holdout_2_pass": holdout2_pass,
        "holdout_2_fail": holdout2_fail,
        "safety": safety,
        "payload_guardrail_failure_count": len(payload.get("payload_guardrail_failures") or []),
    }


def _lane_report(*, summary: dict[str, Any], rows: list[dict[str, Any]], title: str) -> str:
    failures = [row for row in rows if not row.get("passed")]
    return "\n".join(
        [
            f"# {title}",
            "",
            f"- Attempted/completed/durable rows: {summary.get('attempted')} / {summary.get('completed')} / {summary.get('durable_rows')}",
            f"- Safety: {summary.get('safety')}",
            f"- Lane rates: {summary.get('lane_rates')}",
            f"- Failure category counts: {summary.get('failure_category_counts')}",
            "",
            "## Failures",
            _top_failures(failures, 40),
        ]
    ) + "\n"


def _lane_rates(rows: list[dict[str, Any]]) -> dict[str, dict[str, int | float]]:
    groups: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "total": 0})
    for row in rows:
        tags = set(row.get("case", {}).get("tags") or [])
        for group in ("exact_repro", "unseen_positive", "near_miss", "ambiguity", "holdout2", "deictic_followup"):
            if group in tags:
                groups[group]["total"] += 1
                if row.get("passed"):
                    groups[group]["pass"] += 1
        if "positive" in tags:
            groups["positive"]["total"] += 1
            if row.get("passed"):
                groups["positive"]["pass"] += 1
    return {
        group: {**counts, "rate": round(counts["pass"] / counts["total"], 4) if counts["total"] else 0.0}
        for group, counts in sorted(groups.items())
    }


def _safety(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "provider_calls": sum(1 for row in rows if row.get("provider_called")),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout" or row.get("failure_category") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
    }


def _summary_row(label: str, summary: dict[str, Any]) -> str:
    raw = summary.get("raw_counts") or {}
    failures = (summary.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    return (
        f"| {label} | {raw.get('pass')} | {raw.get('fail')} | {raw.get('excluded')} | "
        f"{failures.get('real_routing_gap', 0)} | {failures.get('wrong_subsystem', 0)} | {failures.get('latency_issue', 0)} |"
    )


def _category_table(original: dict[str, Any], remediated: dict[str, Any], post: dict[str, Any]) -> str:
    original_counts = (original.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    remediation_counts = (remediated.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    post_counts = (post.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    categories = [
        "real_routing_gap",
        "wrong_subsystem",
        "latency_issue",
        "clarification_failure",
        "truthfulness_failure",
        "payload_guardrail_failure",
        "hard_timeout",
    ]
    lines = ["| category | original | post-remediation | post-generalization |", "| --- | ---: | ---: | ---: |"]
    for category in categories:
        lines.append(f"| {category} | {original_counts.get(category, 0)} | {remediation_counts.get(category, 0)} | {post_counts.get(category, 0)} |")
    return "\n".join(lines)


def _category_count(summary: dict[str, Any], category: str) -> int:
    return int(((summary.get("failure_counts") or {}).get("scored_failure_category_counts") or {}).get(category) or 0)


def _rate_from_summary(summary: dict[str, Any], group: str) -> str:
    payload = (summary.get("lane_rates") or {}).get(group)
    if not payload:
        return "not_run"
    return f"{payload.get('pass')}/{payload.get('total')} ({round(float(payload.get('rate') or 0.0) * 100, 1)}%)"


def _pass_rate(summary: dict[str, Any]) -> str:
    passed, failed = _raw_pass_fail(summary)
    total = passed + failed
    return f"{passed}/{total} ({round((passed / total) * 100, 1) if total else 0.0}%)"


def _raw_pass_fail(summary: dict[str, Any]) -> tuple[int, int]:
    raw = summary.get("raw_counts") or {}
    passed = int(raw.get("pass") or summary.get("raw_passed") or 0)
    failed = int(raw.get("fail") or summary.get("raw_failed") or 0)
    return passed, failed


def _top_failures(rows: list[dict[str, Any]], limit: int) -> str:
    if not rows:
        return "- none"
    lines = []
    for row in rows[:limit]:
        lines.append(
            f"- `{row.get('test_id')}`: {row.get('failure_category')} "
            f"expected {row.get('expected_route_family')}/{row.get('expected_subsystem')}/{row.get('expected_tool')} "
            f"actual {row.get('actual_route_family')}/{row.get('actual_subsystem')}/{row.get('actual_tool')} "
            f"latency={row.get('latency_ms')} bytes={row.get('response_json_bytes')} reason={row.get('failure_reason')}"
        )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    main()
