from __future__ import annotations

import argparse
import json
from collections import Counter
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_audit
from stormhelm.core.orchestrator.command_eval import build_feature_map
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl

import run_250_checkpoint as checkpoint


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "250-remediation"
ORIGINAL_DIR = Path(".artifacts") / "command-usability-eval" / "250-checkpoint"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run targeted 250-remediation evaluation slices.")
    parser.add_argument("--mode", choices=["targeted", "generalization", "latency", "holdout", "post250"], required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--original-dir", type=Path, default=ORIGINAL_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "targeted":
        run_targeted(args)
    elif args.mode == "generalization":
        run_generated_suite(args, mode="generalization", cases=_generalization_cases())
    elif args.mode == "latency":
        run_latency(args)
    elif args.mode == "holdout":
        run_generated_suite(args, mode="holdout", cases=_holdout_cases())
    else:
        run_post250(args)


def run_targeted(args: argparse.Namespace) -> None:
    corpus = {case.case_id: case for case in build_command_usability_corpus(min_cases=1000)}
    original_rows = _read_jsonl(args.original_dir / "250_results.jsonl")
    target_ids = _targeted_case_ids(original_rows)
    cases = [corpus[case_id] for case_id in target_ids if case_id in corpus]
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(cases, results_name="targeted_250_remediation_results.jsonl", resume=False)
    rows = _read_jsonl(args.output_dir / "targeted_250_remediation_results.jsonl")
    summary = build_checkpoint_summary(results, feature_audit=build_feature_audit(cases))
    summary.update(
        {
            "attempted": len(cases),
            "completed": len(results),
            "durable_rows": len(rows),
            "completed_equals_durable_rows": len(results) == len(rows),
            "safety": _safety(rows),
            "raw_failure_category_counts": dict(Counter(row.get("failure_category") for row in rows if not row.get("passed"))),
            "selected_case_ids": target_ids,
            "orphan_process_check": checkpoint._orphan_process_check_result(),
        }
    )
    write_json(args.output_dir / "targeted_250_remediation_summary.json", summary)
    print(json.dumps({"mode": "targeted", "attempted": len(cases), "summary": str(args.output_dir / "targeted_250_remediation_summary.json")}, indent=2))


def run_generated_suite(args: argparse.Namespace, *, mode: str, cases: list[CommandEvalCase]) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start {mode} suite with existing command-eval child process: {pre_orphan}")

    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results_name = f"{mode}_250_remediation_results.jsonl"
    summary_name = f"{mode}_250_remediation_summary.json"
    report_name = f"{mode}_250_remediation_report.md"
    write_jsonl(args.output_dir / f"{mode}_250_remediation_corpus.jsonl", [case.to_dict() for case in cases])
    results = harness.run(cases, results_name=results_name, resume=False)
    rows = _read_jsonl(args.output_dir / results_name)
    post_orphan = checkpoint._orphan_process_check_result()
    summary = build_checkpoint_summary(results, feature_audit=build_feature_audit(cases))
    summary.update(
        {
            "mode": mode,
            "attempted": len(cases),
            "completed": len(results),
            "durable_rows": len(rows),
            "completed_equals_durable_rows": len(results) == len(rows),
            "pre_orphan_process_check": pre_orphan,
            "post_orphan_process_check": post_orphan,
            "safety": _safety(rows),
            "anti_overfitting_rates": _anti_overfitting_rates(rows),
        }
    )
    write_json(args.output_dir / summary_name, summary)
    (args.output_dir / report_name).write_text(
        _generated_suite_report(mode=mode, rows=rows, summary=summary),
        encoding="utf-8",
    )
    print(json.dumps({"mode": mode, "attempted": len(cases), "summary": str(args.output_dir / summary_name)}, indent=2))


def run_latency(args: argparse.Namespace) -> None:
    original_rows = _read_jsonl(args.original_dir / "250_results.jsonl")
    latency_ids = [
        str(row.get("test_id") or "")
        for row in original_rows
        if row.get("failure_category") == "latency_issue"
    ]
    corpus = {case.case_id: case for case in build_command_usability_corpus(min_cases=1000)}
    cases = [corpus[case_id] for case_id in latency_ids if case_id in corpus]
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(cases, results_name="latency_250_remediation_results.jsonl", resume=False)
    rows = _read_jsonl(args.output_dir / "latency_250_remediation_results.jsonl")
    summary = build_checkpoint_summary(results, feature_audit=build_feature_audit(cases))
    summary.update(
        {
            "attempted": len(cases),
            "completed": len(results),
            "durable_rows": len(rows),
            "completed_equals_durable_rows": len(results) == len(rows),
            "safety": _safety(rows),
            "latency_summary": checkpoint._latency_summary(rows),
            "original_latency_case_ids": latency_ids,
            "orphan_process_check": checkpoint._orphan_process_check_result(),
        }
    )
    write_json(args.output_dir / "latency_250_remediation_summary.json", summary)
    (args.output_dir / "latency_250_remediation_report.md").write_text(
        _latency_suite_report(rows=rows, summary=summary),
        encoding="utf-8",
    )
    print(json.dumps({"mode": "latency", "attempted": len(cases), "summary": str(args.output_dir / "latency_250_remediation_summary.json")}, indent=2))


def run_post250(args: argparse.Namespace) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")

    corpus = build_command_usability_corpus(min_cases=1000)
    selected = checkpoint._select_250_cases(corpus)
    feature_map = build_feature_map()
    feature_audit = build_feature_audit(selected)
    write_json(args.output_dir / "feature_map.json", feature_map)
    write_json(args.output_dir / "feature_map_audit.json", feature_audit)
    write_jsonl(args.output_dir / "250_post_remediation_corpus.jsonl", [case.to_dict() for case in selected])

    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(selected, results_name="250_post_remediation_results.jsonl", resume=False)
    rows = _read_jsonl(args.output_dir / "250_post_remediation_results.jsonl")
    checkpoint_payload = _read_json(args.output_dir / "250_post_remediation_results.checkpoint.json")
    post_orphan = checkpoint._orphan_process_check_result()
    summary_args = SimpleNamespace(
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
    route_confusion = checkpoint._route_confusion_matrix(rows)
    latency_summary = checkpoint._latency_summary(rows)
    failure_census = checkpoint._failure_census(rows)
    known_lanes = checkpoint._known_lanes(rows)
    recommendation = _post_recommendation(summary)
    summary["recommendation"] = recommendation["recommendation"]
    summary["recommendation_detail"] = recommendation

    write_json(args.output_dir / "250_post_remediation_summary.json", summary)
    write_json(args.output_dir / "250_post_remediation_route_confusion_matrix.json", route_confusion)
    write_json(args.output_dir / "250_post_remediation_recommendation.json", recommendation)
    _write_post_report(
        args.output_dir / "250_post_remediation_report.md",
        original_summary=_read_json(args.original_dir / "250_summary.json"),
        post_summary=summary,
        failure_census=failure_census,
        latency_summary=latency_summary,
        known_lanes=known_lanes,
        anti_overfit=_combined_anti_overfit_summary(args.output_dir),
    )
    print(json.dumps({"mode": "post250", "attempted": len(selected), "summary": str(args.output_dir / "250_post_remediation_summary.json")}, indent=2))


def _targeted_case_ids(rows: list[dict[str, Any]]) -> list[str]:
    fixed_styles = {"canonical", "command_mode", "casual", "shorthand", "typo", "indirect", "noisy", "negative", "question", "slang", "unsupported_probe", "cross_family"}
    priority_families = {
        "app_control",
        "browser_destination",
        "calculations",
        "development",
        "discord_relay",
        "file",
        "machine",
        "network",
        "notes",
        "resources",
        "software_control",
        "system_control",
        "terminal",
        "unsupported",
        "watch_runtime",
        "window_control",
    }
    selected: list[str] = []
    for row in rows:
        if row.get("failure_category") == "wrong_subsystem":
            selected.append(str(row.get("test_id") or ""))
            continue
        if row.get("failure_category") != "real_routing_gap":
            continue
        if row.get("wording_style") in fixed_styles and row.get("expected_route_family") in priority_families:
            selected.append(str(row.get("test_id") or ""))
    return [case_id for case_id in dict.fromkeys(selected) if case_id]


def _case(
    case_id: str,
    message: str,
    *,
    route_family: str,
    subsystem: str,
    tools: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    workspace_context: dict[str, Any] | None = None,
    input_context: dict[str, Any] | None = None,
) -> CommandEvalCase:
    return CommandEvalCase(
        case_id=case_id,
        message=message,
        expected=ExpectedBehavior(
            route_family=route_family,
            subsystem=subsystem,
            tools=tools,
            approval="allowed",
            latency_ms_max=15_000,
        ),
        session_id=f"{case_id}-session",
        workspace_context=workspace_context or {},
        input_context=input_context or {},
        tags=tags,
    )


def _active_selection() -> dict[str, Any]:
    return {
        "selection": {
            "kind": "text",
            "value": "Selected context for anti-overfitting route validation.",
            "preview": "Selected context for anti-overfitting route validation.",
        }
    }


def _generalization_cases() -> list[CommandEvalCase]:
    active = _active_selection()
    cases = [
        # Positive unseen variants.
        _case("gen_operator_positive_calc_00", "please what is 84 / 12", route_family="calculations", subsystem="calculations", tags=("positive", "operator_wrapper")),
        _case("gen_operator_positive_browser_00", "could you open github in a browser", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), tags=("positive", "operator_wrapper")),
        _case("gen_operator_positive_software_00", "yo install VLC real quick", route_family="software_control", subsystem="software_control", tags=("positive", "operator_wrapper")),
        _case("gen_operator_positive_discord_00", "please send this to Baby on Discord", route_family="discord_relay", subsystem="discord_relay", tags=("positive", "operator_wrapper"), input_context=active),
        _case("gen_operator_positive_context_00", "could you show the selection", route_family="context_action", subsystem="context", tools=("context_action",), tags=("positive", "operator_wrapper"), input_context=active),
        _case("gen_status_positive_apps_00", "which applications are running", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("positive", "status_ownership")),
        _case("gen_status_positive_programs_00", "list active programs", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("positive", "status_ownership")),
        _case("gen_status_positive_network_00", "are we online", route_family="network", subsystem="system", tools=("network_status",), tags=("positive", "status_ownership")),
        _case("gen_status_positive_windows_00", "show active windows", route_family="window_control", subsystem="system", tools=("window_status",), tags=("positive", "status_ownership")),
        _case("gen_status_positive_resources_00", "what is my RAM and CPU usage", route_family="resources", subsystem="system", tools=("resource_status",), tags=("positive", "status_ownership")),
        _case("gen_system_positive_wifi_00", "please open wifi settings", route_family="system_control", subsystem="system", tools=("system_control",), tags=("positive", "system_control")),
        _case("gen_system_positive_sound_00", "could you open sound settings", route_family="system_control", subsystem="system", tools=("system_control",), tags=("positive", "system_control")),
        _case("gen_unsupported_positive_ticket_00", "buy me a real concert ticket and pay now", route_family="unsupported", subsystem="none", tags=("positive", "unsupported_commitment")),
        _case("gen_unsupported_positive_hotel_00", "order a hotel reservation and pay for it now", route_family="unsupported", subsystem="none", tags=("positive", "unsupported_commitment")),
        _case("gen_unsupported_positive_train_00", "purchase a real train ticket for me now", route_family="unsupported", subsystem="none", tags=("positive", "unsupported_commitment")),
        # Near-miss negatives should preserve generic fallback rather than overcapturing native routes.
        _case("gen_near_miss_browser_00", "please explain what a browser is", route_family="generic_provider", subsystem="provider", tags=("near_miss", "operator_wrapper")),
        _case("gen_near_miss_software_00", "could you describe how software installers work", route_family="generic_provider", subsystem="provider", tags=("near_miss", "operator_wrapper")),
        _case("gen_near_miss_discord_00", "yo Discord etiquette is confusing", route_family="generic_provider", subsystem="provider", tags=("near_miss", "operator_wrapper")),
        _case("gen_near_miss_window_code_00", "which application window pattern should I use in this code", route_family="generic_provider", subsystem="provider", tags=("near_miss", "status_ownership")),
        _case("gen_near_miss_online_00", "can you explain online payments", route_family="generic_provider", subsystem="provider", tags=("near_miss", "status_ownership")),
        _case("gen_near_miss_travel_00", "help me compare flight prices", route_family="comparison", subsystem="", tags=("near_miss", "unsupported_commitment")),
        # Ambiguous or missing-context prompts should stay bounded and unexecuted.
        _case("gen_ambiguous_settings_00", "could you open settings", route_family="generic_provider", subsystem="provider", tags=("ambiguous", "system_control")),
        _case("gen_ambiguous_open_00", "show open things", route_family="generic_provider", subsystem="provider", tags=("ambiguous", "status_ownership")),
        _case("gen_ambiguous_pay_00", "pay for it", route_family="generic_provider", subsystem="provider", tags=("ambiguous", "unsupported_commitment")),
        _case("gen_ambiguous_browser_00", "open the thing I mentioned", route_family="generic_provider", subsystem="provider", tags=("ambiguous", "operator_wrapper")),
    ]
    return cases


def _holdout_cases() -> list[CommandEvalCase]:
    active = _active_selection()
    return [
        _case("holdout_positive_calc_00", "can you compute 144 / 12", route_family="calculations", subsystem="calculations", tags=("positive", "holdout")),
        _case("holdout_positive_browser_00", "please bring up youtube in the browser", route_family="browser_destination", subsystem="browser", tools=("external_open_url",), tags=("positive", "holdout")),
        _case("holdout_positive_software_00", "could you uninstall Zoom", route_family="software_control", subsystem="software_control", tags=("positive", "holdout")),
        _case("holdout_positive_discord_00", "can you relay this to Baby in Discord", route_family="discord_relay", subsystem="discord_relay", tags=("positive", "holdout"), input_context=active),
        _case("holdout_positive_context_00", "please open the selected text", route_family="context_action", subsystem="context", tools=("context_action",), tags=("positive", "holdout"), input_context=active),
        _case("holdout_positive_apps_00", "tell me which apps are running", route_family="app_control", subsystem="system", tools=("active_apps",), tags=("positive", "holdout")),
        _case("holdout_positive_network_00", "is this machine connected right now", route_family="network", subsystem="system", tools=("network_status",), tags=("positive", "holdout")),
        _case("holdout_positive_windows_00", "list focused windows", route_family="window_control", subsystem="system", tools=("window_status",), tags=("positive", "holdout")),
        _case("holdout_positive_resources_00", "show current cpu memory load", route_family="resources", subsystem="system", tools=("resource_status",), tags=("positive", "holdout")),
        _case("holdout_positive_system_00", "open network settings please", route_family="system_control", subsystem="system", tools=("system_control",), tags=("positive", "holdout")),
        _case("holdout_positive_unsupported_00", "book a real hotel and pay now", route_family="unsupported", subsystem="none", tags=("positive", "holdout")),
        _case("holdout_near_miss_app_00", "what apps do developers usually build first", route_family="generic_provider", subsystem="provider", tags=("near_miss", "holdout")),
        _case("holdout_near_miss_window_00", "what is a window function in SQL", route_family="generic_provider", subsystem="provider", tags=("near_miss", "holdout")),
        _case("holdout_near_miss_network_00", "explain network effects in startups", route_family="generic_provider", subsystem="provider", tags=("near_miss", "holdout")),
        _case("holdout_near_miss_purchase_00", "make a checklist for buying a plane ticket", route_family="generic_provider", subsystem="provider", tags=("near_miss", "holdout")),
        _case("holdout_ambiguous_this_00", "open that", route_family="generic_provider", subsystem="provider", tags=("ambiguous", "holdout")),
        _case("holdout_ambiguous_pay_00", "can you buy it", route_family="generic_provider", subsystem="provider", tags=("ambiguous", "holdout")),
    ]


def _post_recommendation(summary: dict[str, Any]) -> dict[str, Any]:
    failures = summary.get("failure_counts", {}).get("scored_failure_category_counts", {})
    real_gaps = int(failures.get("real_routing_gap") or 0)
    wrong_subsystem = int(failures.get("wrong_subsystem") or 0)
    payload_failures = int(failures.get("payload_guardrail_failure") or 0)
    hard_timeouts = int(summary.get("safety", {}).get("hard_timeouts") or 0)
    recommendation = "proceed to targeted fixes before 1000"
    if real_gaps <= 35 and wrong_subsystem <= 3 and payload_failures == 0 and hard_timeouts == 0:
        recommendation = "consider 1000 after reviewing remaining clustered failures"
    if real_gaps > 60 or wrong_subsystem > 5:
        recommendation = "keep 1000 blocked; run another targeted routing pass"
    return {
        "recommendation": recommendation,
        "real_routing_gap": real_gaps,
        "wrong_subsystem": wrong_subsystem,
        "payload_guardrail_failure": payload_failures,
        "hard_timeouts": hard_timeouts,
    }


def _anti_overfitting_rates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_group: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "pass": 0})
    for row in rows:
        tags = set(row.get("case", {}).get("tags") or [])
        if "positive" in tags:
            group = "unseen_positive"
        elif "near_miss" in tags:
            group = "near_miss_preservation"
        elif "ambiguous" in tags:
            group = "ambiguity_or_missing_context"
        else:
            group = "other"
        by_group[group]["total"] += 1
        if row.get("passed"):
            by_group[group]["pass"] += 1
    return {
        group: {
            **counts,
            "rate": round((counts["pass"] / counts["total"]) if counts["total"] else 0.0, 4),
        }
        for group, counts in sorted(by_group.items())
    }


def _combined_anti_overfit_summary(output_dir: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for mode in ("targeted", "generalization", "holdout"):
        path = output_dir / f"{mode}_250_remediation_summary.json"
        if path.exists():
            payload = _read_json(path)
            summary[mode] = {
                "attempted": payload.get("attempted"),
                "completed": payload.get("completed"),
                "durable_rows": payload.get("durable_rows"),
                "raw_counts": payload.get("raw_counts"),
                "scored_counts": payload.get("scored_counts"),
                "anti_overfitting_rates": payload.get("anti_overfitting_rates"),
                "safety": payload.get("safety"),
            }
    return summary


def _generated_suite_report(*, mode: str, rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    rates = summary.get("anti_overfitting_rates") or {}
    safety = summary.get("safety") or {}
    failures = [row for row in rows if not row.get("passed")]
    lines = [
        f"# {mode.title()} 250-Remediation Suite",
        "",
        "## Summary",
        f"- Attempted/completed/durable rows: {summary.get('attempted')} / {summary.get('completed')} / {summary.get('durable_rows')}",
        f"- Provider calls: {safety.get('provider_calls')}",
        f"- Real external actions: {safety.get('real_external_actions')}",
        f"- Hard timeouts: {safety.get('hard_timeouts')}",
        f"- Process kills: {safety.get('process_kills')}",
        f"- Orphan process check: {summary.get('post_orphan_process_check') or summary.get('orphan_process_check')}",
        "",
        "## Anti-Overfitting Rates",
        "| group | pass | total | rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for group, payload in rates.items():
        lines.append(f"| {group} | {payload.get('pass')} | {payload.get('total')} | {payload.get('rate')} |")
    lines.extend(["", "## Failures", "| test_id | category | expected | actual | reason |", "| --- | --- | --- | --- | --- |"])
    for row in failures[:30]:
        lines.append(
            f"| {row.get('test_id')} | {row.get('failure_category')} | "
            f"{row.get('expected_route_family')}/{row.get('expected_subsystem')}/{row.get('expected_tool')} | "
            f"{row.get('actual_route_family')}/{row.get('actual_subsystem')}/{row.get('actual_tool')} | "
            f"{str(row.get('failure_reason') or '').replace('|', '/')} |"
        )
    if not failures:
        lines.append("| none | passed | - | - | - |")
    return "\n".join(lines) + "\n"


def _latency_suite_report(*, rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    latency = summary.get("latency_summary") or {}
    slowest = sorted(rows, key=lambda row: float(row.get("total_latency_ms") or row.get("latency_ms") or 0), reverse=True)[:20]
    lines = [
        "# Latency 250-Remediation Mini-Suite",
        "",
        f"- Attempted/completed/durable rows: {summary.get('attempted')} / {summary.get('completed')} / {summary.get('durable_rows')}",
        f"- Safety: {summary.get('safety')}",
        f"- Latency summary: {latency.get('min')} / {latency.get('median')} / {latency.get('p90')} / {latency.get('p95')} / {latency.get('max')}",
        "",
        "## Slowest Rows",
        "| test_id | family | total ms | route handler ms | memory ms | unattributed ms | payload bytes | lane labels |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in slowest:
        lines.append(
            f"| {row.get('test_id')} | {row.get('actual_route_family')} | {row.get('total_latency_ms')} | "
            f"{row.get('route_handler_ms')} | {row.get('memory_context_ms')} | {row.get('unattributed_latency_ms')} | "
            f"{row.get('response_json_bytes')} | {row.get('known_lane_labels')} |"
        )
    return "\n".join(lines) + "\n"


def _write_post_report(
    path: Path,
    *,
    original_summary: dict[str, Any],
    post_summary: dict[str, Any],
    failure_census: dict[str, Any],
    latency_summary: dict[str, Any],
    known_lanes: dict[str, Any],
    anti_overfit: dict[str, Any],
) -> None:
    original_failures = original_summary.get("failure_counts", {}).get("scored_failure_category_counts", {})
    post_failures = post_summary.get("failure_counts", {}).get("scored_failure_category_counts", {})
    payload = post_summary.get("payload_summary") or {}
    latency = post_summary.get("latency_summary_ms") or {}
    safety = post_summary.get("safety") or {}
    raw = post_summary.get("raw_counts") or {}
    scored = post_summary.get("scored_counts") or {}
    lines = [
        "# 250 Post-Remediation Checkpoint Report",
        "",
        "## Executive Summary",
        f"- Attempted/completed/durable rows: {post_summary.get('attempted')} / {post_summary.get('completed')} / {post_summary.get('durable_rows')}",
        f"- Raw pass/fail/excluded: {raw.get('pass')} / {raw.get('fail')} / {raw.get('excluded')}",
        f"- Scored pass/fail/excluded: {scored.get('pass')} / {scored.get('fail')} / {scored.get('excluded')}",
        f"- Recommendation: {post_summary.get('recommendation')}",
        f"- Exact 250 repro pass rate: {_pass_rate_text((anti_overfit.get('targeted') or {}).get('raw_counts'))}",
        f"- Unseen variant pass rate: {_rate_text(anti_overfit, 'generalization', 'unseen_positive')}",
        f"- Near-miss preservation rate: {_rate_text(anti_overfit, 'generalization', 'near_miss_preservation')}",
        f"- Ambiguity/clarification correctness: {_rate_text(anti_overfit, 'generalization', 'ambiguity_or_missing_context')}",
        f"- Holdout pass rate: {_pass_rate_text((anti_overfit.get('holdout') or {}).get('raw_counts'))}",
        "",
        "## Safety Summary",
        f"- Provider calls: {safety.get('provider_calls')}",
        f"- Real external actions: {safety.get('real_external_actions')}",
        f"- Hard timeouts: {safety.get('hard_timeouts')}",
        f"- Process kills: {safety.get('process_kills')}",
        f"- Orphan process check: {safety.get('orphan_process_check')}",
        "",
        "## Before/After Failure Categories",
        "| category | original 250 | post remediation |",
        "| --- | ---: | ---: |",
    ]
    categories = sorted(set(original_failures) | set(post_failures))
    for category in categories:
        lines.append(f"| {category} | {original_failures.get(category, 0)} | {post_failures.get(category, 0)} |")
    lines.extend(
        [
            "",
            "## Pass/Fail Comparison",
            f"- Original 250: {original_summary.get('raw_counts', {}).get('pass')} pass / {original_summary.get('raw_counts', {}).get('fail')} fail / {original_summary.get('raw_counts', {}).get('excluded')} excluded",
            f"- Post remediation: {raw.get('pass')} pass / {raw.get('fail')} fail / {raw.get('excluded')} excluded",
            "",
            "## Latency Lane Summary",
            f"- p50/p90/p95/max ms: {latency.get('median')} / {latency.get('p90')} / {latency.get('p95')} / {latency.get('max')}",
            f"- Known lane counts: {post_summary.get('failure_counts', {}).get('known_lane_counts')}",
            f"- Known lane detail rows: {len(known_lanes.get('rows') or []) if isinstance(known_lanes, dict) else 0}",
            "",
            "## Payload Guardrail Summary",
            f"- Max response bytes: {(payload.get('response_json_bytes') or {}).get('max')}",
            f"- Rows above 1 MB: {len(payload.get('rows_above_1mb') or [])}",
            f"- Rows above 5 MB: {len(payload.get('rows_above_5mb') or [])}",
            f"- Max workspace item count: {payload.get('max_workspace_item_count')}",
            f"- Payload guardrail failures: {len(payload.get('payload_guardrail_failures') or [])}",
            "",
            "## Top Remaining Failure Families",
            "| expected family | failures |",
            "| --- | ---: |",
        ]
    )
    for family, count in (failure_census.get("failures_by_expected_family") or [])[:20]:
        lines.append(f"| {family} | {count} |")
    lines.extend(
        [
            "",
            "## Routine Save Summary",
            "- Historical catastrophic routine_save remains preserved as known_unreproduced_product_latency_blocker unless reproduced and fixed elsewhere.",
            "",
            "## Tests Added",
            "- tests/test_command_routing_250_remediation.py covers exact 250 wrapper/status/unsupported/subsystem prompts plus near-misses.",
            "- Process-isolated generalization and holdout suites separate exact repro improvement from unseen behavior.",
            "",
            "## Anti-Overfitting Protocol",
            "- Original 250 failed prompts were treated as repro examples only.",
            "- Repaired clusters require exact repros, unseen positives, near-miss negatives, and ambiguous/missing-context cases.",
            "- Holdout failures are not patched in this pass.",
            "- Static source-diff prompt hardcoding checks are recorded separately.",
            "",
            "## What Was Deliberately Not Changed",
            "- No 1000-case run.",
            "- No broad planner redesign.",
            "- No payload guardrail weakening.",
            "- No approval/trust weakening.",
            "- No routine_save historical blocker relabeling.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pass_rate_text(raw_counts: dict[str, Any] | None) -> str:
    if not raw_counts:
        return "not_run"
    passed = int(raw_counts.get("pass") or 0)
    failed = int(raw_counts.get("fail") or 0)
    total = passed + failed
    return f"{passed}/{total} ({round((passed / total) * 100, 1) if total else 0.0}%)"


def _rate_text(anti_overfit: dict[str, Any], mode: str, group: str) -> str:
    payload = ((anti_overfit.get(mode) or {}).get("anti_overfitting_rates") or {}).get(group)
    if not payload:
        return "not_run"
    return f"{payload.get('pass')}/{payload.get('total')} ({round(float(payload.get('rate') or 0) * 100, 1)}%)"


def _safety(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "provider_calls": sum(1 for row in rows if row.get("provider_called")),
        "real_external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout" or row.get("failure_category") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
    }


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
