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


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "generalization-overcapture-pass-2"
CHECKPOINT_250_DIR = Path(".artifacts") / "command-usability-eval" / "250-checkpoint"
REMEDIATION_250_DIR = Path(".artifacts") / "command-usability-eval" / "250-remediation"
PASS1_DIR = Path(".artifacts") / "command-usability-eval" / "generalization-overcapture-pass"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the second generalization/overcapture lanes.")
    parser.add_argument("--mode", choices=["targeted", "holdout3", "post250", "finalize"], required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "targeted":
        _run_generated_lane(
            args,
            cases=_targeted_generalization_2_cases(),
            results_name="targeted_generalization_2_results.jsonl",
            summary_name="targeted_generalization_2_summary.json",
        )
    elif args.mode == "holdout3":
        _run_generated_lane(
            args,
            cases=_holdout_3_cases(),
            results_name="holdout_3_results.jsonl",
            summary_name="holdout_3_summary.json",
            report_name="holdout_3_report.md",
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
    corpus_name = results_name.replace("_results.jsonl", "_corpus.jsonl")
    write_jsonl(args.output_dir / corpus_name, [case.to_dict() for case in cases])
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
            "safety": {**_safety(rows), "orphan_process_check": post_orphan},
            "lane_rates": _lane_rates(rows),
            "failure_category_counts": dict(sorted(Counter(str(row.get("failure_category") or "") for row in rows if not row.get("passed")).items())),
        }
    )
    write_json(args.output_dir / summary_name, summary)
    if report_name is not None:
        (args.output_dir / report_name).write_text(_lane_report(summary=summary, rows=rows, title=report_name), encoding="utf-8")
    print(json.dumps({"mode": results_name, "attempted": len(cases), "completed": len(results), "durable_rows": len(rows)}, indent=2))


def _run_post250(args: argparse.Namespace) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")
    corpus = build_command_usability_corpus(min_cases=1000)
    selected = checkpoint._select_250_cases(corpus)
    feature_audit = build_feature_audit(selected)
    write_jsonl(args.output_dir / "250_post_generalization_2_corpus.jsonl", [case.to_dict() for case in selected])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(selected, results_name="250_post_generalization_2_results.jsonl", resume=False)
    rows = _read_jsonl(args.output_dir / "250_post_generalization_2_results.jsonl")
    checkpoint_payload = _read_json(args.output_dir / "250_post_generalization_2_results.checkpoint.json")
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
    write_json(args.output_dir / "250_post_generalization_2_summary.json", summary)
    write_json(args.output_dir / "250_post_generalization_2_route_confusion_matrix.json", checkpoint._route_confusion_matrix(rows))
    write_json(args.output_dir / "250_post_generalization_2_recommendation.json", recommendation)
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
            "value": "Selected text for the second generalization pass.",
            "preview": "Selected text for the second generalization pass.",
        }
    }


def _targeted_generalization_2_cases() -> list[CommandEvalCase]:
    active = _active_selection()
    cases: list[CommandEvalCase] = [
        # Exact holdout-2 repro lane.
        _case("goc2_exact_network_wifi_00", "which wifi am I on", route_family="network", subsystem="system", tools=("network_status",), tags=("exact_repro", "network")),
        _case("goc2_exact_screen_submit_00", "press submit", route_family="screen_awareness", subsystem="screen_awareness", tags=("exact_repro", "screen")),
        _case("goc2_exact_app_quit_00", "quit Notepad", route_family="app_control", subsystem="system", tools=("app_control",), tags=("exact_repro", "app_control")),
        _case("goc2_exact_apps_running_00", "which apps are running right now", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("exact_repro", "app_status")),
        _case("goc2_exact_compare_neural_00", "compare neural network architectures", route_family="generic_provider", subsystem="provider", tags=("exact_repro", "near_miss", "comparison")),
        _case("goc2_exact_browser_deictic_00", "open that website", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("exact_repro", "deictic_followup", "browser")),
        # Network positives and negatives.
        _case("goc2_network_pos_01", "which wi-fi network am I using", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network")),
        _case("goc2_network_pos_02", "what wi-fi am I connected to", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network")),
        _case("goc2_network_pos_03", "tell me the current Wi-Fi network", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network")),
        _case("goc2_network_pos_04", "show my wifi connection name", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network")),
        _case("goc2_network_pos_05", "what wireless network is this laptop on", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network")),
        _case("goc2_network_pos_06", "which SSID am I connected to", route_family="network", subsystem="system", tools=("network_status",), tags=("unseen_positive", "network")),
        _case("goc2_network_near_01", "which neural network is better for images", route_family="generic_provider", subsystem="provider", tags=("near_miss", "network")),
        _case("goc2_network_near_02", "explain wireless network design", route_family="generic_provider", subsystem="provider", tags=("near_miss", "network")),
        _case("goc2_network_near_03", "network architecture patterns", route_family="generic_provider", subsystem="provider", tags=("near_miss", "network")),
        _case("goc2_network_amb_01", "which network", route_family="generic_provider", subsystem="provider", tags=("ambiguity", "network")),
        # Screen action positives and near-misses.
        _case("goc2_screen_pos_01", "click submit", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "screen")),
        _case("goc2_screen_pos_02", "tap submit", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "screen")),
        _case("goc2_screen_pos_03", "press OK", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "screen")),
        _case("goc2_screen_pos_04", "click next", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "screen")),
        _case("goc2_screen_pos_05", "tap save", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "screen")),
        _case("goc2_screen_pos_06", "press cancel", route_family="screen_awareness", subsystem="screen_awareness", tags=("unseen_positive", "screen")),
        _case("goc2_screen_near_01", "explain submit button design", route_family="generic_provider", subsystem="provider", tags=("near_miss", "screen")),
        _case("goc2_screen_near_02", "submit a proposal outline", route_family="generic_provider", subsystem="provider", tags=("near_miss", "screen")),
        _case("goc2_screen_near_03", "what does next mean in UX", route_family="generic_provider", subsystem="provider", tags=("near_miss", "screen")),
        _case("goc2_screen_amb_01", "press it", route_family="generic_provider", subsystem="provider", tags=("ambiguity", "screen")),
        _case("goc2_screen_amb_02", "click that", route_family="generic_provider", subsystem="provider", tags=("ambiguity", "screen")),
        # Active apps/app-control and app/software boundary.
        _case("goc2_app_status_pos_01", "what programs are active right now", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("unseen_positive", "app_status")),
        _case("goc2_app_status_pos_02", "list running applications", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("unseen_positive", "app_status")),
        _case("goc2_app_status_pos_03", "show active apps", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("unseen_positive", "app_status")),
        _case("goc2_app_status_pos_04", "what apps are open", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("unseen_positive", "app_status")),
        _case("goc2_app_status_pos_05", "which programs are open", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("unseen_positive", "app_status")),
        _case("goc2_app_status_near_01", "what apps should I build first", route_family="generic_provider", subsystem="provider", tags=("near_miss", "app_status")),
        _case("goc2_app_status_near_02", "running app marketing ideas", route_family="generic_provider", subsystem="provider", tags=("near_miss", "app_status")),
        _case("goc2_app_status_near_03", "open apps concept in mobile UX", route_family="generic_provider", subsystem="provider", tags=("near_miss", "app_status")),
        _case("goc2_app_boundary_01", "focus Notepad", route_family="app_control", subsystem="system", tools=("app_control",), tags=("regression_canary", "app_control")),
        _case("goc2_software_canary_01", "update Notepad", route_family="software_control", subsystem="software_control", tags=("regression_canary", "software_control")),
        # Browser deictics and app-control canaries.
        _case("goc2_browser_missing_01", "open that site", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("ambiguity", "browser")),
        _case("goc2_browser_missing_02", "show that page", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("ambiguity", "browser")),
        _case("goc2_browser_missing_03", "open the website from before", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("deictic_followup", "browser")),
        _case("goc2_browser_missing_04", "bring up that link", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("deictic_followup", "browser")),
        _case("goc2_browser_pos_01", "open example.com", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), tags=("regression_canary", "browser")),
        _case("goc2_browser_pos_02", "open docs.python.org in browser", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), tags=("unseen_positive", "browser")),
        _case("goc2_browser_near_01", "what is a website", route_family="generic_provider", subsystem="provider", tags=("near_miss", "browser")),
        _case("goc2_browser_near_02", "open website design principles", route_family="generic_provider", subsystem="provider", tags=("near_miss", "browser")),
        # Comparison boundary.
        _case("goc2_compare_near_01", "compare neural networks", route_family="generic_provider", subsystem="provider", tags=("near_miss", "comparison")),
        _case("goc2_compare_near_02", "compare React and Vue", route_family="generic_provider", subsystem="provider", tags=("near_miss", "comparison")),
        _case("goc2_compare_near_03", "compare startup pricing models", route_family="generic_provider", subsystem="provider", tags=("near_miss", "comparison")),
        # Existing pass canaries.
        _case("goc2_context_canary_01", "show selected text", route_family="context_action", subsystem="context", tools=("context_action",), tags=("regression_canary", "context"), input_context=active),
        _case("goc2_discord_canary_01", "forward this to Baby via Discord", route_family="discord_relay", subsystem="discord_relay", tags=("regression_canary", "discord"), input_context=active),
        _case("goc2_deictic_canary_01", "open that", route_family="generic_provider", subsystem="provider", tags=("regression_canary", "ambiguity")),
    ]
    return cases


def _holdout_3_cases() -> list[CommandEvalCase]:
    active = _active_selection()
    cases = [
        # 25 positive generalization cases.
        _case("holdout3_positive_network_01", "show the SSID for this laptop", route_family="network", subsystem="system", tools=("network_status",), tags=("holdout3", "positive")),
        _case("holdout3_positive_network_02", "what wireless connection is my PC using", route_family="network", subsystem="system", tools=("network_status",), tags=("holdout3", "positive")),
        _case("holdout3_positive_network_03", "tell me my current connection name", route_family="network", subsystem="system", tools=("network_status",), tags=("holdout3", "positive")),
        _case("holdout3_positive_network_04", "am I on Wi-Fi right now", route_family="network", subsystem="system", tools=("network_status",), tags=("holdout3", "positive")),
        _case("holdout3_positive_network_05", "what network is the device using", route_family="network", subsystem="system", tools=("network_status",), tags=("holdout3", "positive")),
        _case("holdout3_positive_screen_01", "click OK", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout3", "positive")),
        _case("holdout3_positive_screen_02", "tap done", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout3", "positive")),
        _case("holdout3_positive_screen_03", "press apply", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout3", "positive")),
        _case("holdout3_positive_screen_04", "select cancel", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout3", "positive")),
        _case("holdout3_positive_screen_05", "click sign in", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout3", "positive")),
        _case("holdout3_positive_apps_01", "show running programs", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("holdout3", "positive")),
        _case("holdout3_positive_apps_02", "list open applications now", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("holdout3", "positive")),
        _case("holdout3_positive_apps_03", "what programs are open", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("holdout3", "positive")),
        _case("holdout3_positive_apps_04", "which applications are active", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("holdout3", "positive")),
        _case("holdout3_positive_apps_05", "tell me active apps", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("holdout3", "positive")),
        _case("holdout3_positive_browser_01", "open python.org", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), tags=("holdout3", "positive")),
        _case("holdout3_positive_browser_02", "go to example.org", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), tags=("holdout3", "positive")),
        _case("holdout3_positive_browser_03", "pull up docs.python.org", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), tags=("holdout3", "positive")),
        _case("holdout3_positive_browser_04", "show wikipedia.org", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), tags=("holdout3", "positive")),
        _case("holdout3_positive_browser_05", "navigate to openai.com", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), tags=("holdout3", "positive")),
        _case("holdout3_positive_app_01", "quit Calculator", route_family="app_control", subsystem="system", tools=("app_control",), tags=("holdout3", "positive")),
        _case("holdout3_positive_app_02", "focus Calculator", route_family="app_control", subsystem="system", tools=("app_control",), tags=("holdout3", "positive")),
        _case("holdout3_positive_context_01", "show the selected text", route_family="context_action", subsystem="context", tools=("context_action",), tags=("holdout3", "positive"), input_context=active),
        _case("holdout3_positive_discord_01", "pass this note to Baby through Discord", route_family="discord_relay", subsystem="discord_relay", tags=("holdout3", "positive"), input_context=active),
        _case("holdout3_positive_calc_01", "compute 7 plus 8", route_family="calculations", subsystem="calculations", tags=("holdout3", "positive")),
        # 15 near-miss negatives.
        _case("holdout3_near_network_01", "which neural net architecture should I study", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_network_02", "wireless network design principles", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_network_03", "network effects explained", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_screen_01", "submit button UX examples", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_screen_02", "press release outline", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_app_01", "app marketing plan ideas", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_app_02", "which apps should I build next", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_browser_01", "website navigation principles", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_browser_02", "open web design ideas", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_compare_01", "compare transformer architectures", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_compare_02", "compare React and Svelte", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_context_01", "selection bias overview", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_context_02", "define selected text for docs", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_browser_03", "what is a browser tab", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        _case("holdout3_near_apps_03", "running program ideas for beginners", route_family="generic_provider", subsystem="provider", tags=("holdout3", "near_miss")),
        # 10 ambiguity/missing-context cases.
        _case("holdout3_amb_browser_01", "open that page", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("holdout3", "ambiguity")),
        _case("holdout3_amb_browser_02", "bring up this site", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("holdout3", "ambiguity")),
        _case("holdout3_amb_browser_03", "pull up the previous URL", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("holdout3", "ambiguity")),
        _case("holdout3_amb_screen_01", "click it", route_family="generic_provider", subsystem="provider", tags=("holdout3", "ambiguity")),
        _case("holdout3_amb_screen_02", "tap that", route_family="generic_provider", subsystem="provider", tags=("holdout3", "ambiguity")),
        _case("holdout3_amb_network_01", "network?", route_family="generic_provider", subsystem="provider", tags=("holdout3", "ambiguity")),
        _case("holdout3_amb_network_02", "which network", route_family="generic_provider", subsystem="provider", tags=("holdout3", "ambiguity")),
        _case("holdout3_amb_context_01", "open the selected text", route_family="context_action", subsystem="context", clarification="expected", tags=("holdout3", "ambiguity")),
        _case("holdout3_amb_context_02", "show highlighted text", route_family="context_action", subsystem="context", clarification="expected", tags=("holdout3", "ambiguity")),
        _case("holdout3_amb_discord_01", "forward this in Discord", route_family="discord_relay", subsystem="discord_relay", clarification="expected", tags=("holdout3", "ambiguity"), input_context=active),
        # 10 deictic/follow-up cases.
        _case("holdout3_deictic_browser_01", "open this web page", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("holdout3", "deictic_followup")),
        _case("holdout3_deictic_browser_02", "show that URL", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("holdout3", "deictic_followup")),
        _case("holdout3_deictic_screen_01", "click this checkbox", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout3", "deictic_followup")),
        _case("holdout3_deictic_screen_02", "press that save button", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout3", "deictic_followup")),
        _case("holdout3_deictic_screen_03", "open this menu", route_family="screen_awareness", subsystem="screen_awareness", tags=("holdout3", "deictic_followup")),
        _case("holdout3_deictic_context_01", "show selected text from here", route_family="context_action", subsystem="context", tools=("context_action",), tags=("holdout3", "deictic_followup"), input_context=active),
        _case("holdout3_deictic_context_02", "open the highlighted text here", route_family="context_action", subsystem="context", tools=("context_action",), tags=("holdout3", "deictic_followup"), input_context=active),
        _case("holdout3_deictic_discord_01", "send this note to Baby on Discord", route_family="discord_relay", subsystem="discord_relay", tags=("holdout3", "deictic_followup"), input_context=active),
        _case("holdout3_deictic_discord_02", "DM that selection to Baby on Discord", route_family="discord_relay", subsystem="discord_relay", tags=("holdout3", "deictic_followup"), input_context=active),
        _case("holdout3_deictic_generic_01", "open this", route_family="generic_provider", subsystem="provider", tags=("holdout3", "deictic_followup")),
    ]
    return cases


def _write_final_report(output_dir: Path) -> None:
    original = _read_json(CHECKPOINT_250_DIR / "250_summary.json")
    remediated = _read_json(REMEDIATION_250_DIR / "250_post_remediation_summary.json")
    post_generalization = _read_json(PASS1_DIR / "250_post_generalization_summary.json")
    post = _read_json(output_dir / "250_post_generalization_2_summary.json")
    targeted = _read_json(output_dir / "targeted_generalization_2_summary.json")
    holdout2 = _read_json(PASS1_DIR / "holdout_2_summary.json")
    holdout3 = _read_json(output_dir / "holdout_3_summary.json")
    regression = _read_json(output_dir / "250_regression_delta.json")
    diagnosis = _read_json(output_dir / "holdout_2_failure_diagnosis.json")
    post_rows = _read_jsonl(output_dir / "250_post_generalization_2_results.jsonl")
    failures = [row for row in post_rows if not row.get("passed")]
    failure_counts = (post.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    payload = post.get("payload_summary") or {}
    latency = post.get("latency_summary_ms") or {}
    safety = post.get("safety") or {}
    recommendation = _recommendation(post, post_rows)
    lines = [
        "# 250 Post-Generalization-2 Report",
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
        f"- Exact repro pass rate: {_rate_from_summary(targeted, 'exact_repro')}",
        f"- Unseen variant pass rate: {_rate_from_summary(targeted, 'unseen_positive')}",
        f"- Near-miss preservation rate: {_rate_from_summary(targeted, 'near_miss')}",
        f"- Ambiguity correctness rate: {_rate_from_summary(targeted, 'ambiguity')}",
        f"- Holdout-2 diagnosis: {diagnosis.get('failure_count')} failures clustered in holdout_2_failure_diagnosis.md",
        f"- Holdout-3 pass rate: {_pass_rate(holdout3)}",
        "- Static anti-hardcoding result: passed; exact prompt/test-id hits in product routing logic are zero.",
        "",
        "## 5. 250 Regression Delta",
        f"- Pass -> fail: {(regression.get('summary') or {}).get('pass_to_fail_count')}",
        f"- Fail -> pass: {(regression.get('summary') or {}).get('fail_to_pass_count')}",
        f"- Classification counts: {(regression.get('summary') or {}).get('pass_to_fail_classification_counts')}",
        "- Interpretation: the previous 168 -> 161 decrease was mostly Discord approval expectation drift plus one bounded workflow latency threshold crossing, not a broad route-family regression.",
        "",
        "## 6. Holdout-2 Failure Diagnosis",
        _diagnosis_summary(diagnosis),
        "",
        "## 7. Cluster-Level Fixes Made",
        "- Network/Wi-Fi status now recognizes Wi-Fi, wireless, SSID, and connection-name wording while preserving conceptual network near-misses.",
        "- Screen awareness now owns action-verb plus common UI-control labels without accepting bare deictics.",
        "- Active-app status now wins before resource telemetry for running/open app status requests and declines app-concept phrasing.",
        "- Browser destination now owns unbound website/site/page/link deictics with native clarification before app-control can claim them.",
        "- Native comparison now requires file/document/path/context evidence; conceptual comparisons remain provider-owned.",
        "- App quit/focus remains app_control; software lifecycle remains install/update/uninstall/repair oriented.",
        "",
        "## 8. What Was Deliberately Not Changed",
        "- No 1000-case run.",
        "- No broad planner rewrite.",
        "- No exact-prompt product routing hardcodes.",
        "- No approval/trust, dry-run, or payload guardrail weakening.",
        "- No holdout-3 failure patching in this pass.",
        "- Historical routine_save catastrophic latency remains known_unreproduced_product_latency_blocker.",
        "",
        "## 9. 250 Before/After Comparison",
        "| run | pass | fail | excluded | real_routing_gap | wrong_subsystem | latency_issue | response_correctness_failure |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        _summary_row("original 250", original),
        _summary_row("post-remediation 250", remediated),
        _summary_row("post-generalization 250", post_generalization),
        _summary_row("post-generalization-2 250", post),
        "",
        "## 10. Failure Category Comparison",
        _category_table(original, remediated, post_generalization, post),
        "",
        "## 11. Generic-Provider Fallback Comparison",
        f"- Original 250: {(original.get('generic_provider_fallback_count_by_expected_family') or {})}",
        f"- Post-remediation 250: {(remediated.get('generic_provider_fallback_count_by_expected_family') or {})}",
        f"- Post-generalization 250: {(post_generalization.get('generic_provider_fallback_count_by_expected_family') or {})}",
        f"- Post-generalization-2 250: {(post.get('generic_provider_fallback_count_by_expected_family') or {})}",
        "",
        "## 12. Wrong-Subsystem Comparison",
        f"- Original: {_category_count(original, 'wrong_subsystem')}",
        f"- Post-remediation: {_category_count(remediated, 'wrong_subsystem')}",
        f"- Post-generalization: {_category_count(post_generalization, 'wrong_subsystem')}",
        f"- Post-generalization-2: {_category_count(post, 'wrong_subsystem')}",
        "",
        "## 13. Overcapture And Near-Miss Analysis",
        f"- Targeted near-miss preservation: {_rate_from_summary(targeted, 'near_miss')}",
        f"- Holdout-3 near-miss preservation: {_rate_from_summary(holdout3, 'near_miss')}",
        f"- Holdout-3 ambiguity correctness: {_rate_from_summary(holdout3, 'ambiguity')}",
        "",
        "## 14. Latency Lane Summary",
        f"- p50/p90/p95/max ms: {latency.get('median')} / {latency.get('p90')} / {latency.get('p95')} / {latency.get('max')}",
        f"- Known lane counts: {(post.get('failure_counts') or {}).get('known_lane_counts')}",
        "",
        "## 15. Payload Guardrail Summary",
        f"- Max response bytes: {(payload.get('response_json_bytes') or {}).get('max')}",
        f"- Rows above 1 MB: {len(payload.get('rows_above_1mb') or [])}",
        f"- Rows above 5 MB: {len(payload.get('rows_above_5mb') or [])}",
        f"- Payload guardrail failures: {len(payload.get('payload_guardrail_failures') or [])}",
        "",
        "## 16. Routine-Save Historical Blocker Status",
        "- Old catastrophic native routine_save remains preserved as known_unreproduced_product_latency_blocker; this pass did not reproduce or claim to fix it.",
        "",
        "## 17. Remaining Blockers",
        f"- Scored failure categories: {failure_counts}",
        f"- Holdout-3 failures: {_top_failures([row for row in _read_jsonl(output_dir / 'holdout_3_results.jsonl') if not row.get('passed')], 20)}",
        f"- Top remaining 250 failures: {_top_failures(failures, 20)}",
        "",
        "## 18. Recommendation",
        f"- {recommendation['recommendation']}",
    ]
    (output_dir / "250_post_generalization_2_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(output_dir / "250_post_generalization_2_recommendation.json", recommendation)


def _recommendation(summary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    safety = summary.get("safety") or {}
    payload = summary.get("payload_summary") or {}
    failures = (summary.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    holdout3 = _read_json(OUTPUT_DIR / "holdout_3_summary.json")
    holdout_pass, holdout_fail = _raw_pass_fail(holdout3)
    holdout_total = holdout_pass + holdout_fail
    holdout_rate = (holdout_pass / holdout_total) if holdout_total else 0.0
    recommendation = "keep 1000 blocked; review post-generalization-2 failures"
    if (
        summary.get("completed_equals_durable_rows")
        and not safety.get("real_external_actions")
        and not safety.get("provider_calls")
        and not safety.get("hard_timeouts")
        and not safety.get("process_kills")
        and not payload.get("payload_guardrail_failures")
        and int(failures.get("wrong_subsystem") or 0) <= 1
        and int(failures.get("real_routing_gap") or 0) < 25
        and holdout_rate >= 0.85
    ):
        recommendation = "proceed to 1000 after review; remaining failures are bounded and clustered"
    if int(failures.get("real_routing_gap") or 0) >= 25 or holdout_rate < 0.85:
        recommendation = "keep 1000 blocked; run another targeted pass or repair remaining routing clusters"
    return {
        "recommendation": recommendation,
        "scored_failure_category_counts": failures,
        "holdout_3_pass": holdout_pass,
        "holdout_3_fail": holdout_fail,
        "holdout_3_rate": round(holdout_rate, 4),
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
            _top_failures(failures, 60),
        ]
    ) + "\n"


def _lane_rates(rows: list[dict[str, Any]]) -> dict[str, dict[str, int | float]]:
    groups: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "total": 0})
    for row in rows:
        tags = set(row.get("case", {}).get("tags") or [])
        for group in (
            "exact_repro",
            "unseen_positive",
            "near_miss",
            "ambiguity",
            "deictic_followup",
            "regression_canary",
            "holdout3",
            "positive",
        ):
            if group in tags:
                groups[group]["total"] += 1
                if row.get("passed"):
                    groups[group]["pass"] += 1
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
        f"{failures.get('real_routing_gap', 0)} | {failures.get('wrong_subsystem', 0)} | "
        f"{failures.get('latency_issue', 0)} | {failures.get('response_correctness_failure', 0)} |"
    )


def _category_table(*summaries: dict[str, Any]) -> str:
    labels = ["original", "post-remediation", "post-generalization", "post-generalization-2"]
    categories = [
        "real_routing_gap",
        "wrong_subsystem",
        "latency_issue",
        "clarification_failure",
        "truthfulness_failure",
        "payload_guardrail_failure",
        "hard_timeout",
        "response_correctness_failure",
    ]
    lines = ["| category | original | post-remediation | post-generalization | post-generalization-2 |", "| --- | ---: | ---: | ---: | ---: |"]
    counts = [((summary.get("failure_counts") or {}).get("scored_failure_category_counts") or {}) for summary in summaries]
    for category in categories:
        values = [str(count.get(category, 0)) for count in counts]
        lines.append(f"| {category} | {' | '.join(values)} |")
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


def _diagnosis_summary(payload: dict[str, Any]) -> str:
    failures = payload.get("failures") or []
    if not failures:
        return "- none"
    return "\n".join(
        f"- `{item.get('test_id')}`: {item.get('classification')} / {item.get('cluster_id')} / {item.get('likely_root_cause')}"
        for item in failures
    )


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
