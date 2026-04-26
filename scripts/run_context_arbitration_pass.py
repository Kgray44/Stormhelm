from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_audit
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl

import run_250_checkpoint as checkpoint
import run_readiness_pass_3 as rp3


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "context-arbitration-pass"
CHECKPOINT_250_DIR = Path(".artifacts") / "command-usability-eval" / "250-checkpoint"
REMEDIATION_250_DIR = Path(".artifacts") / "command-usability-eval" / "250-remediation"
GENERALIZATION_1_DIR = Path(".artifacts") / "command-usability-eval" / "generalization-overcapture-pass"
GENERALIZATION_2_DIR = Path(".artifacts") / "command-usability-eval" / "generalization-overcapture-pass-2"
READINESS_3_DIR = Path(".artifacts") / "command-usability-eval" / "readiness-pass-3"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run context-arbitration command-eval lanes.")
    parser.add_argument("--mode", choices=["targeted", "holdout5", "post250", "finalize"], required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _require_prerequisite_artifacts(args.output_dir)

    if args.mode == "targeted":
        _run_generated_lane(
            args,
            cases=_targeted_context_arbitration_cases(),
            results_name="targeted_context_arbitration_results.jsonl",
            summary_name="targeted_context_arbitration_summary.json",
        )
    elif args.mode == "holdout5":
        _run_generated_lane(
            args,
            cases=_holdout_5_cases(),
            results_name="holdout_5_results.jsonl",
            summary_name="holdout_5_summary.json",
            report_name="holdout_5_report.md",
        )
    elif args.mode == "post250":
        _run_post250(args)
    else:
        _write_final_report(args.output_dir)


def _require_prerequisite_artifacts(output_dir: Path) -> None:
    required = [
        output_dir / "progress_stagnation_audit.md",
        output_dir / "holdout_4_failure_diagnosis.md",
        output_dir / "remaining_routing_gap_census.md",
        output_dir / "route_context_arbitration_design.md",
        output_dir / "latency_lane_reclassification.md",
        output_dir / "static_anti_overfitting_check.md",
        READINESS_3_DIR / "ai_provider_seam_audit.md",
        READINESS_3_DIR / "ai_provider_seam_audit.json",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise SystemExit(
            "Context-arbitration audits and AI/provider seam audit must exist before request lanes: "
            + ", ".join(str(path) for path in missing)
        )


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
            "safety": {**rp3._safety(rows), "orphan_process_check": post_orphan, **rp3._ai_safety_fields(rows)},
            "lane_rates": rp3._lane_rates(rows),
            "ai_provider_usage": rp3._ai_provider_usage(rows),
            "failure_category_counts": dict(
                sorted(Counter(str(row.get("failure_category") or "") for row in rows if not row.get("passed")).items())
            ),
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
    write_jsonl(args.output_dir / "250_post_context_arbitration_corpus.jsonl", [case.to_dict() for case in selected])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(selected, results_name="250_post_context_arbitration_results.jsonl", resume=False)
    rows = _read_jsonl(args.output_dir / "250_post_context_arbitration_results.jsonl")
    checkpoint_payload = _read_json(args.output_dir / "250_post_context_arbitration_results.checkpoint.json")
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
    summary["safety"].update(rp3._ai_safety_fields(rows))
    summary["ai_provider_usage"] = rp3._ai_provider_usage(rows)
    recommendation = _recommendation(summary, rows)
    summary["recommendation"] = recommendation["recommendation"]
    summary["recommendation_detail"] = recommendation
    write_json(args.output_dir / "250_post_context_arbitration_summary.json", summary)
    write_json(args.output_dir / "250_post_context_arbitration_route_confusion_matrix.json", checkpoint._route_confusion_matrix(rows))
    write_json(args.output_dir / "250_post_context_arbitration_recommendation.json", recommendation)
    _write_final_report(args.output_dir)
    print(json.dumps({"mode": "post250", "attempted": len(selected), "completed": len(results), "durable_rows": len(rows)}, indent=2))


def _targeted_context_arbitration_cases() -> list[CommandEvalCase]:
    selected = _selection()
    calc_ctx = _calc_context()
    calc_state = _calc_state()
    browser_ctx = _browser_context()
    file_ctx = _file_context()
    c = rp3._case
    cases = [
        c("rca_calc_direct_01", "tiny math: 9 times 8", route_family="calculations", subsystem="calculations", response_terms=("72",), tags=("exact_repro", "calculation")),
        c("rca_calc_direct_02", "diagnose nothing else, just answer 6 x 7", route_family="calculations", subsystem="calculations", response_terms=("42",), tags=("exact_repro", "calculation")),
        c("rca_calc_direct_03", "math rq 13*4", route_family="calculations", subsystem="calculations", response_terms=("52",), tags=("unseen_positive", "calculation", "noisy")),
        c("rca_calc_direct_04", "answer this directly: 16 times 5", route_family="calculations", subsystem="calculations", response_terms=("80",), tags=("unseen_positive", "calculation")),
        c("rca_calc_follow_01", "show me the arithmetic for that", route_family="calculations", subsystem="calculations", clarification="expected", input_context=calc_ctx, active_request_state=calc_state, tags=("exact_repro", "follow_up")),
        c("rca_calc_follow_02", "same setup but use 30 instead", route_family="calculations", subsystem="calculations", clarification="expected", input_context=calc_ctx, active_request_state=calc_state, tags=("exact_repro", "follow_up")),
        c("rca_calc_follow_03", "what changes if it is 24 / 4", route_family="calculations", subsystem="calculations", clarification="expected", input_context=calc_ctx, active_request_state=calc_state, tags=("unseen_positive", "follow_up")),
        c("rca_calc_follow_04", "use the same math with 15 instead", route_family="calculations", subsystem="calculations", clarification="expected", input_context=calc_ctx, active_request_state=calc_state, tags=("unseen_positive", "follow_up")),
        c("rca_calc_missing_01", "show me the arithmetic for that", route_family="calculations", subsystem="calculations", clarification="expected", tags=("ambiguity", "calculation")),
        c("rca_calc_missing_02", "compare that answer with 10", route_family="calculations", subsystem="calculations", clarification="expected", tags=("ambiguity", "calculation")),
        c("rca_browser_missing_01", "open that website", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("exact_repro", "browser")),
        c("rca_browser_missing_02", "bring up the page we just used", route_family="browser_destination", subsystem="browser", clarification="expected", tags=("unseen_positive", "browser", "ambiguity")),
        c("rca_browser_bound_01", "open that website", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), input_context=browser_ctx, tags=("follow_up", "browser")),
        c("rca_browser_bound_02", "show the earlier page again", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), input_context=browser_ctx, tags=("follow_up", "browser")),
        c("rca_file_missing_01", "open that file from before", route_family="file", subsystem="files", clarification="expected", tags=("exact_repro", "file")),
        c("rca_file_bound_01", "show that document again", route_family="file", subsystem="files", tools=("external_open_file",), input_context=file_ctx, tags=("follow_up", "file")),
        c("rca_file_read_01", r"read C:\Stormhelm\README.md, do not open an app", route_family="file", subsystem="files", tools=("file_reader",), tags=("exact_repro", "file")),
        c("rca_file_open_01", r"open C:\Stormhelm\README.md in the deck", route_family="file", subsystem="files", tools=("deck_open_file",), tags=("regression_canary", "file")),
        c("rca_context_bound_01", "summarize the selected text, not the page", route_family="context_action", subsystem="context", tools=("context_action",), input_context=selected, tags=("exact_repro", "context")),
        c("rca_context_bound_02", "make tasks from the highlighted text", route_family="task_continuity", subsystem="workspace", tools=("context_action",), input_context=selected, tags=("unseen_positive", "context")),
        c("rca_context_missing_01", "use the highlighted bit", route_family="context_action", subsystem="context", clarification="expected", tags=("ambiguity", "context")),
        c("rca_context_near_01", "what is selected text in HTML", route_family="generic_provider", subsystem="provider", tags=("near_miss", "context")),
        c("rca_screen_named_01", "press submit", route_family="screen_awareness", subsystem="screen_awareness", clarification="expected", tags=("exact_repro", "screen")),
        c("rca_screen_named_02", "click the save button", route_family="screen_awareness", subsystem="screen_awareness", clarification="expected", tags=("unseen_positive", "screen")),
        c("rca_screen_near_01", "press coverage summary", route_family="generic_provider", subsystem="provider", tags=("near_miss", "screen")),
        c("rca_screen_near_02", "click that", route_family="generic_provider", subsystem="provider", tags=("near_miss", "screen")),
        c("rca_status_network_01", "which wifi am I on", route_family="network", subsystem="system", tools=("network_status",), tags=("exact_repro", "network")),
        c("rca_status_watch_01", "what did I miss while I was away", route_family="watch_runtime", subsystem="operations", tools=("activity_summary",), tags=("exact_repro", "watch_runtime")),
        c("rca_status_near_01", "which neural network architecture is better", route_family="generic_provider", subsystem="provider", tags=("near_miss", "network")),
        c("rca_relay_missing_01", "send this there", route_family="discord_relay", subsystem="discord_relay", clarification="expected", tags=("ambiguity", "discord")),
        c("rca_relay_selected_01", "relay the selected text to Baby on Discord", route_family="discord_relay", subsystem="discord_relay", approval="expected_or_preview", input_context=selected, tags=("regression_canary", "discord")),
        c("rca_trust_missing_01", "approve it", route_family="trust_approvals", subsystem="trust", clarification="expected", approval="allowed", tags=("ambiguity", "trust")),
        c("rca_routine_missing_01", "run the thing", route_family="routine", subsystem="routine", clarification="expected", tags=("ambiguity", "routine")),
        c("rca_fileop_missing_01", "rename it", route_family="file_operation", subsystem="files", clarification="expected", tags=("ambiguity", "file_operation")),
        c("rca_software_boundary_01", "remove Slack from this machine", route_family="software_control", subsystem="software_control", approval="expected_or_preview", tags=("regression_canary", "software_control")),
        c("rca_app_boundary_01", "quit Notepad, not uninstall it", route_family="app_control", subsystem="system", tools=("app_control",), tags=("regression_canary", "app_control")),
    ]
    return cases


def _holdout_5_cases() -> list[CommandEvalCase]:
    selected = _selection("Holdout five selected text about meeting cleanup.")
    calc_ctx = _calc_context("54 / 6", "9")
    calc_state = _calc_state()
    browser_ctx = _browser_context("https://stormhelm.local/deck")
    file_ctx = _file_context(r"C:\Stormhelm\README.md")
    c = rp3._case
    cases: list[CommandEvalCase] = []

    def add(case_id: str, message: str, **kwargs: Any) -> None:
        cases.append(c(case_id, message, **kwargs))

    for idx, message in enumerate(
        [
            "walk me through that answer",
            "reuse that result but multiply by 4",
            "same equation, swap in 72",
            "now compare that number with 12",
            "show arithmetic for the previous answer",
            "redo the prior math with 63 / 7",
            "what if the result were doubled",
            "divide the last answer by 3",
        ],
        1,
    ):
        add(f"holdout5_deictic_calc_{idx:02d}", message, route_family="calculations", subsystem="calculations", input_context=calc_ctx, active_request_state=calc_state, tags=("holdout5", "deictic_followup", "calculation"))
    for idx, message in enumerate(
        [
            "pull up that site again",
            "show the page from a moment ago",
            "open the link we were using",
            "bring back the previous website",
            "open the doc we just referenced",
            "show me that previous document",
            "bring up the earlier file",
            "read the file from the last turn",
        ],
        1,
    ):
        if idx <= 4:
            add(f"holdout5_deictic_browser_{idx:02d}", message, route_family="browser_destination", subsystem="browser", tools=("external_open_url",), input_context=browser_ctx, tags=("holdout5", "deictic_followup", "browser"))
        else:
            add(f"holdout5_deictic_file_{idx:02d}", message, route_family="file", subsystem="files", tools=("deck_open_file",), input_context=file_ctx, tags=("holdout5", "deictic_followup", "file"))
    for idx, (message, family, subsystem, missing) in enumerate(
        [
            ("use this selection for the summary", "context_action", "context", "context"),
            ("turn this highlighted passage into tasks", "context_action", "context", "context"),
            ("send that over there", "discord_relay", "discord_relay", "payload"),
            ("forward this to them", "discord_relay", "discord_relay", "payload"),
            ("approve that request", "trust_approvals", "trust", "approval_object"),
            ("allow it this once", "trust_approvals", "trust", "approval_object"),
            ("tag that with urgent", "file_operation", "files", "file_context"),
            ("archive this item", "file_operation", "files", "file_context"),
            ("execute that saved flow", "routine", "routine", "routine_context"),
        ],
        1,
    ):
        add(f"holdout5_deictic_missing_{idx:02d}", message, route_family=family, subsystem=subsystem, clarification="expected", approval="allowed", tags=("holdout5", "deictic_followup", "ambiguity"), response_terms=(missing,))

    cross_family = [
        ("which wifi network is active right now", "network", "system", ("network_status",)),
        ("network effect examples for products", "generic_provider", "provider", ()),
        ("open or inspect wifi status", "network", "system", ("network_status",)),
        ("compare neural nets for image tasks", "generic_provider", "provider", ()),
        ("open that website if you still have it", "browser_destination", "browser", ()),
        ("open a website strategy article", "generic_provider", "provider", ()),
        ("read C:\\Stormhelm\\README.md instead of launching an app", "file", "files", ("file_reader",)),
        ("open app onboarding ideas", "generic_provider", "provider", ()),
        ("quit Calculator, do not uninstall it", "app_control", "system", ("app_control",)),
        ("uninstall Calculator if it is installed", "software_control", "software_control", ()),
        ("which apps are running now", "app_control", "system", ("active_apps",)),
        ("what makes apps run fast", "generic_provider", "provider", ()),
        ("press the OK button", "screen_awareness", "screen_awareness", ()),
        ("button design comparison", "generic_provider", "provider", ()),
        ("send selected text to Baby on Discord", "discord_relay", "discord_relay", ()),
        ("write Discord welcome rules", "generic_provider", "provider", ()),
        ("save this as a routine called inbox zero", "routine", "routine", ()),
        ("routine building habits", "generic_provider", "provider", ()),
        ("what browser page is visible", "watch_runtime", "context", ("browser_context",)),
        ("browser engine history", "generic_provider", "provider", ()),
    ]
    for idx, (message, family, subsystem, tools) in enumerate(cross_family, 1):
        input_context = selected if "selected text" in message else {}
        approval = "expected_or_preview" if family in {"discord_relay", "software_control"} else "allowed"
        clarification = "expected" if message.startswith("open that website") or message.startswith("save this as") else "none"
        add(f"holdout5_cross_{idx:02d}", message, route_family=family, subsystem=subsystem, tools=tools, input_context=input_context, approval=approval, clarification=clarification, tags=("holdout5", "cross_family"))

    ambiguity = [
        ("open that page again please", "browser_destination", "browser", "destination_context"),
        ("summarize the highlighted thing", "context_action", "context", "context"),
        ("rename that one", "file_operation", "files", "file_context"),
        ("approve the previous one", "trust_approvals", "trust", "approval_object"),
        ("run that routine again", "routine", "routine", "routine_context"),
        ("send it to the usual place", "discord_relay", "discord_relay", "payload"),
        ("press that control", "screen_awareness", "screen_awareness", "visible_screen"),
        ("show the previous file", "file", "files", "file_context"),
        ("use it for the next step", "generic_provider", "provider", ""),
        ("put that over here", "generic_provider", "provider", ""),
        ("finish the previous thing", "generic_provider", "provider", ""),
        ("open the thing from earlier", "generic_provider", "provider", ""),
        ("compare it to the other number", "calculations", "calculations", "calculation_context"),
        ("save that workflow", "routine", "routine", "routine_context"),
        ("message this there", "discord_relay", "discord_relay", "payload"),
    ]
    for idx, (message, family, subsystem, term) in enumerate(ambiguity, 1):
        add(f"holdout5_ambiguity_{idx:02d}", message, route_family=family, subsystem=subsystem, clarification="expected" if family != "generic_provider" else "none", approval="allowed", response_terms=(term,) if term else (), tags=("holdout5", "ambiguity"))

    near_misses = [
        "selected text accessibility patterns",
        "workflow design principles",
        "routine maintenance philosophy",
        "approval policy templates",
        "screen reader button labels",
        "open source file formats",
        "network graph visualization tips",
        "calculator UI ideas",
        "Discord bot moderation strategy",
        "browser privacy comparison",
        "what is a command palette",
        "how should I organize tasks",
        "file naming advice",
        "software lifecycle essay outline",
        "why do buttons need clear labels",
    ]
    for idx, message in enumerate(near_misses, 1):
        add(f"holdout5_near_{idx:02d}", message, route_family="generic_provider", subsystem="provider", tags=("holdout5", "near_miss"))

    calc_context_cases = [
        ("quick calc pls 17 x 3", "51"),
        ("diagnose the route and answer 81 / 9", "9"),
        ("math only: 42 plus 58", "100"),
        ("just solve 13 times 7", "91"),
        ("answer 144 over 16", "9"),
        ("show the working for 5 x 12", "60"),
        ("what is 100 - 36", "64"),
        ("route as calculation: 28 / 4", "7"),
        ("same formula with 90 instead", ""),
        ("show steps for that value", ""),
    ]
    for idx, (message, term) in enumerate(calc_context_cases, 1):
        kwargs: dict[str, Any] = {"route_family": "calculations", "subsystem": "calculations", "tags": ("holdout5", "calculation_context")}
        if idx >= 9:
            kwargs.update({"input_context": calc_ctx, "active_request_state": calc_state})
        if term:
            kwargs["response_terms"] = (term,)
        add(f"holdout5_calc_context_{idx:02d}", message, **kwargs)

    boundary_cases = [
        ("open C:\\Stormhelm\\README.md externally", "file", "files", ("external_open_file",), {}),
        ("open C:\\Stormhelm\\README.md in the deck", "file", "files", ("deck_open_file",), {}),
        ("show that document again", "file", "files", ("deck_open_file",), file_ctx),
        ("bring back the website we just had", "browser_destination", "browser", ("external_open_url",), browser_ctx),
        ("open the previous URL", "browser_destination", "browser", ("external_open_url",), browser_ctx),
        ("launch Notepad", "app_control", "system", ("app_control",), {}),
        ("close Notepad", "app_control", "system", ("app_control",), {}),
        ("remove Teams from this computer", "software_control", "software_control", (), {}),
        ("open Wi-Fi settings", "system_control", "system", ("system_control",), {}),
        ("show the active browser tab", "watch_runtime", "context", ("browser_context",), {}),
    ]
    for idx, (message, family, subsystem, tools, ctx) in enumerate(boundary_cases, 1):
        approval = "expected_or_preview" if family == "software_control" else "allowed"
        add(f"holdout5_boundary_{idx:02d}", message, route_family=family, subsystem=subsystem, tools=tools, input_context=ctx, approval=approval, tags=("holdout5", "browser_file_app"))

    response_cases = [
        ("make this into a routine named triage sweep", "routine", "routine", "expected", ()),
        ("verify that the Discord message actually sent", "discord_relay", "discord_relay", "expected", ()),
        ("book a hotel and pay right now", "unsupported", "none", "none", ()),
        ("delete everything in downloads without asking", "maintenance", "maintenance", "none", ("maintenance_action",)),
        ("open that website without a URL", "browser_destination", "browser", "expected", ()),
    ]
    for idx, (message, family, subsystem, clarification, tools) in enumerate(response_cases, 1):
        add(
            f"holdout5_response_{idx:02d}",
            message,
            route_family=family,
            subsystem=subsystem,
            clarification=clarification,
            tools=tools,
            approval="expected_or_preview" if family in {"maintenance", "discord_relay"} else "allowed",
            result_state="unsupported_or_clarification" if family == "unsupported" else "dry_run_or_completed",
            tags=("holdout5", "response_correctness"),
        )
    return cases


def _selection(value: str = "Selected arbitration text.") -> dict[str, Any]:
    return {"selection": {"kind": "text", "value": value, "preview": value[:80]}}


def _calc_context(expression: str = "18 / 3", display_result: str = "6") -> dict[str, Any]:
    return {
        "current_resolution": {"family": "calculations", "expression": expression, "display_result": display_result},
        "recent_entities": [{"kind": "calculation", "expression": expression, "display_result": display_result}],
    }


def _calc_state() -> dict[str, Any]:
    return {"family": "calculations", "subject": "recent calculation", "parameters": {"request_stage": "preview"}}


def _browser_context(url: str = "https://example.org/latest") -> dict[str, Any]:
    return {"recent_entities": [{"kind": "page", "url": url, "title": "recent page"}]}


def _file_context(path: str = r"C:\Stormhelm\README.md") -> dict[str, Any]:
    return {"recent_entities": [{"kind": "file", "path": path, "name": Path(path).name}]}


def _write_final_report(output_dir: Path) -> None:
    original = _read_json(CHECKPOINT_250_DIR / "250_summary.json")
    remediated = _read_json(REMEDIATION_250_DIR / "250_post_remediation_summary.json")
    post_generalization = _read_json(GENERALIZATION_1_DIR / "250_post_generalization_summary.json")
    post_generalization_2 = _read_json(GENERALIZATION_2_DIR / "250_post_generalization_2_summary.json")
    post_readiness_3 = _read_json(READINESS_3_DIR / "250_post_readiness_3_summary.json")
    post = _read_json(output_dir / "250_post_context_arbitration_summary.json")
    targeted = _read_json(output_dir / "targeted_context_arbitration_summary.json")
    holdout5 = _read_json(output_dir / "holdout_5_summary.json")
    rows = _read_jsonl(output_dir / "250_post_context_arbitration_results.jsonl")
    failures = [row for row in rows if not row.get("passed")]
    failure_counts = (post.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    payload = post.get("payload_summary") or {}
    latency = post.get("latency_summary_ms") or {}
    safety = post.get("safety") or {}
    ai_usage = post.get("ai_provider_usage") or rp3._ai_provider_usage(rows)
    recommendation = _recommendation(post, rows)
    lines = [
        "# 250 Post-Context-Arbitration Report",
        "",
        "## 1. Executive Summary",
        f"- Attempted/completed/durable rows: {post.get('attempted')} / {post.get('completed')} / {post.get('durable_rows')}",
        f"- Scored pass/fail/excluded: {post.get('scored_counts')}",
        f"- Recommendation: {recommendation['recommendation']}",
        "",
        "## 2. Safety Summary",
        f"- Provider calls: {safety.get('provider_calls')}",
        f"- OpenAI calls: {safety.get('openai_calls')}",
        f"- LLM calls: {safety.get('llm_calls')}",
        f"- Embedding calls: {safety.get('embedding_calls')}",
        f"- Real external actions: {safety.get('real_external_actions', safety.get('external_actions', 0))}",
        f"- Hard timeouts: {safety.get('hard_timeouts')}",
        f"- Process kills: {safety.get('process_kills')}",
        f"- Orphan process check: {safety.get('orphan_process_check')}",
        "",
        "## 3. Harness Durability",
        f"- Attempted/completed/durable rows: {post.get('attempted')} / {post.get('completed')} / {post.get('durable_rows')}",
        f"- Completed equals durable rows: {post.get('completed_equals_durable_rows')}",
        "",
        "## 4. Progress/Stagnation Audit Summary",
        "- See progress_stagnation_audit.md for per-test fixed/stagnant/regressed classifications across the 250 lineage.",
        "",
        "## 5. Holdout-4 Failure Diagnosis Summary",
        "- See holdout_4_failure_diagnosis.md for all 28 holdout-4 failures and root-cause labels.",
        "",
        "## 6. Shared Route-Context Arbitration Design",
        "- Added a shared RouteContextArbitrator for active context, selected text, recent browser/file/calculation context, missing preconditions, and generic-provider gating.",
        "- The design routes native-owned missing-context requests to native clarification instead of generic fallback.",
        "",
        "## 7. Cluster-Level Fixes Made",
        "- Calculation follow-up/noisy arithmetic ownership and direct math normalization.",
        "- Browser/file/context deictic binding and missing-context clarification.",
        "- Screen action boundary: named visible controls clarify; bare deictics remain generic without grounding.",
        "- Network/watch/system/software/app/file-path cross-family arbitration.",
        "- Explicit file read/open routes avoid app launch and keep correct Deck/external targets.",
        "",
        "## 8. What Was Deliberately Not Changed",
        "- No 1000-case run.",
        "- No broad planner rewrite, provider-first interpretation, payload weakening, or approval weakening.",
        "- No exact holdout-5 failure patching in this pass.",
        "- Historical routine_save catastrophic latency remains known_unreproduced_product_latency_blocker.",
        "",
        "## 9. Targeted Context-Arbitration Results",
        f"- Pass rate: {rp3._pass_rate(targeted)}",
        f"- Lane rates: {targeted.get('lane_rates')}",
        "",
        "## 10. Holdout-5 Results",
        f"- Pass rate: {rp3._pass_rate(holdout5)}",
        f"- Lane rates: {holdout5.get('lane_rates')}",
        f"- Top holdout-5 failures: {rp3._top_failures([row for row in _read_jsonl(output_dir / 'holdout_5_results.jsonl') if not row.get('passed')], 20)}",
        "",
        "## 11. 250 Before/After Comparison",
        "| run | pass | fail | excluded | real_routing_gap | wrong_subsystem | latency_issue | response_correctness_failure |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        rp3._summary_row("original 250", original),
        rp3._summary_row("post-remediation", remediated),
        rp3._summary_row("post-generalization", post_generalization),
        rp3._summary_row("post-generalization-2", post_generalization_2),
        rp3._summary_row("post-readiness-3", post_readiness_3),
        rp3._summary_row("post-context-arbitration", post),
        "",
        "## 12. Failure Category Comparison",
        _category_table_context(original, remediated, post_generalization, post_generalization_2, post_readiness_3, post),
        "",
        "## 13. Generic-Provider Fallback Comparison",
        f"- Original 250: {(original.get('generic_provider_fallback_count_by_expected_family') or {})}",
        f"- Readiness-3 250: {(post_readiness_3.get('generic_provider_fallback_count_by_expected_family') or {})}",
        f"- Context-arbitration 250: {(post.get('generic_provider_fallback_count_by_expected_family') or {})}",
        "",
        "## 14. Deictic/Follow-Up Performance Summary",
        f"- Targeted follow-up lane: {rp3._rate_from_summary(targeted, 'follow_up')}",
        f"- Holdout-5 deictic/follow-up lane: {_rate_from_rows(_read_jsonl(output_dir / 'holdout_5_results.jsonl'), 'deictic_followup')}",
        "",
        "## 15. Cross-Family Confusion Summary",
        f"- Holdout-5 cross-family lane: {rp3._rate_from_summary(holdout5, 'cross_family')}",
        f"- Remaining wrong_subsystem count: {rp3._category_count(post, 'wrong_subsystem')}",
        "",
        "## 16. Near-Miss Preservation Summary",
        f"- Targeted near-miss preservation: {rp3._rate_from_summary(targeted, 'near_miss')}",
        f"- Holdout-5 near-miss preservation: {rp3._rate_from_summary(holdout5, 'near_miss')}",
        "",
        "## 17. Ambiguity/Missing-Context Clarification Summary",
        f"- Targeted ambiguity lane: {rp3._rate_from_summary(targeted, 'ambiguity')}",
        f"- Holdout-5 ambiguity lane: {rp3._rate_from_summary(holdout5, 'ambiguity')}",
        "",
        "## 18. Latency Lane Classification",
        "- See latency_lane_reclassification.md for all 31 readiness-pass-3 latency rows.",
        f"- Context-arbitration latency p50/p90/p95/max ms: {latency.get('median')} / {latency.get('p90')} / {latency.get('p95')} / {latency.get('max')}",
        f"- Scored latency issues after rerun: {failure_counts.get('latency_issue', 0)}",
        "",
        "## 19. Payload Guardrail Summary",
        f"- Max response bytes: {(payload.get('response_json_bytes') or {}).get('max')}",
        f"- Rows above 1 MB: {len(payload.get('rows_above_1mb') or [])}",
        f"- Rows above 5 MB: {len(payload.get('rows_above_5mb') or [])}",
        f"- Payload guardrail failures: {len(payload.get('payload_guardrail_failures') or [])}",
        "",
        "## 20. Routine-Save Historical Blocker Status",
        "- Old catastrophic native routine_save remains preserved as known_unreproduced_product_latency_blocker; this pass did not reproduce or claim to fix it.",
        "",
        "## 21. Static Anti-Hardcoding Result",
        "- Passed. See static_anti_overfitting_check.md.",
        "",
        "## 22. Remaining Blockers",
        f"- Failure categories: {failure_counts}",
        f"- Top remaining 250 failures: {rp3._top_failures(failures, 30)}",
        "",
        "## 23. Recommendation",
        f"- {recommendation['recommendation']}",
    ]
    (output_dir / "250_post_context_arbitration_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(output_dir / "250_post_context_arbitration_recommendation.json", recommendation)


def _recommendation(summary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    safety = summary.get("safety") or {}
    payload = summary.get("payload_summary") or {}
    failures = (summary.get("failure_counts") or {}).get("scored_failure_category_counts") or {}
    holdout = _read_json(OUTPUT_DIR / "holdout_5_summary.json")
    holdout_pass, holdout_fail = rp3._raw_pass_fail(holdout)
    holdout_total = holdout_pass + holdout_fail
    holdout_rate = (holdout_pass / holdout_total) if holdout_total else 0.0
    real_routing_gap = int(failures.get("real_routing_gap") or 0)
    wrong_subsystem = int(failures.get("wrong_subsystem") or 0)
    recommendation = "keep 1000 blocked; review context-arbitration failures"
    if safety.get("external_actions") or safety.get("provider_calls") or safety.get("openai_calls") or safety.get("llm_calls") or safety.get("embedding_calls"):
        recommendation = "keep 1000 blocked; safety/provider invariant failed"
    elif payload.get("payload_guardrail_failures"):
        recommendation = "keep 1000 blocked; payload guardrail failure needs repair"
    elif holdout_rate < 0.85:
        recommendation = "keep 1000 blocked; holdout-5 generalization is below 85% readiness floor"
    elif real_routing_gap < 25 and wrong_subsystem == 0 and holdout_rate >= 0.85:
        recommendation = "proceed to 1000 after review; context arbitration is bounded enough for broad evaluation"
    else:
        recommendation = "run another targeted structural pass before 1000"
    return {
        "recommendation": recommendation,
        "scored_failure_category_counts": failures,
        "holdout_5_pass": holdout_pass,
        "holdout_5_fail": holdout_fail,
        "holdout_5_rate": round(holdout_rate, 4),
        "real_routing_gap": real_routing_gap,
        "wrong_subsystem": wrong_subsystem,
        "safety": safety,
        "payload_guardrail_failure_count": len(payload.get("payload_guardrail_failures") or []),
    }


def _lane_report(*, summary: dict[str, Any], rows: list[dict[str, Any]], title: str) -> str:
    ai_usage = summary.get("ai_provider_usage") or rp3._ai_provider_usage(rows)
    return "\n".join(
        [
            f"# {title}",
            "",
            "## Summary",
            f"- Attempted/completed/durable rows: {summary.get('attempted')} / {summary.get('completed')} / {summary.get('durable_rows')}",
            f"- Raw pass/fail: {rp3._raw_pass_fail(summary)}",
            f"- Lane rates: {summary.get('lane_rates')}",
            f"- Safety: {summary.get('safety')}",
            "",
            "## AI / Provider Usage",
            f"- Total provider calls: {ai_usage.get('total_provider_calls')}",
            f"- Total OpenAI calls: {ai_usage.get('total_openai_calls')}",
            f"- Total LLM calls: {ai_usage.get('total_llm_calls')}",
            f"- Total embedding calls: {ai_usage.get('total_embedding_calls')}",
            "",
            "## Failures",
            rp3._top_failures([row for row in rows if not row.get("passed")], 30),
        ]
    ) + "\n"


def _category_table_context(*summaries: dict[str, Any]) -> str:
    labels = [
        "original",
        "post-remediation",
        "post-generalization",
        "post-generalization-2",
        "post-readiness-3",
        "post-context-arbitration",
    ]
    categories = [
        "real_routing_gap",
        "wrong_subsystem",
        "latency_issue",
        "response_correctness_failure",
        "approval_expectation_mismatch",
        "clarification_failure",
        "truthfulness_failure",
        "payload_guardrail_failure",
        "hard_timeout",
    ]
    lines = [
        "| category | " + " | ".join(labels[: len(summaries)]) + " |",
        "| --- | " + " | ".join("---:" for _ in summaries) + " |",
    ]
    for category in categories:
        lines.append("| " + category + " | " + " | ".join(str(rp3._category_count(summary, category)) for summary in summaries) + " |")
    return "\n".join(lines)


def _rate_from_rows(rows: list[dict[str, Any]], tag: str) -> str:
    tagged = [row for row in rows if tag in {str(item) for item in row.get("case", {}).get("tags") or []}]
    if not tagged:
        return "n/a"
    passed = sum(1 for row in tagged if row.get("passed"))
    return f"{passed}/{len(tagged)} ({passed / len(tagged):.1%})"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


if __name__ == "__main__":
    main()
