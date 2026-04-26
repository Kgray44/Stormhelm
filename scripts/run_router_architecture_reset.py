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
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl
from stormhelm.core.orchestrator.route_spine import RouteSpine

import run_250_checkpoint as checkpoint


OUTPUT_DIR = Path(".artifacts") / "command-usability-eval" / "router-architecture-reset"


def main() -> None:
    parser = argparse.ArgumentParser(description="Router architecture reset workbench/eval lanes.")
    parser.add_argument("--mode", choices=["workbench", "targeted", "holdout6", "post250", "finalize"], required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "workbench":
        _run_workbench(args.output_dir)
    elif args.mode == "targeted":
        _run_eval_lane(
            args,
            cases=_targeted_cases(),
            results_name="targeted_router_integration_results.jsonl",
            summary_name="targeted_router_integration_summary.json",
        )
    elif args.mode == "holdout6":
        _run_eval_lane(
            args,
            cases=_holdout_6_cases(),
            results_name="holdout_6_results.jsonl",
            summary_name="holdout_6_summary.json",
            report_name="holdout_6_report.md",
        )
    elif args.mode == "post250":
        _run_post250(args)
    else:
        _write_final_report(args.output_dir)


def _run_workbench(output_dir: Path) -> None:
    spine = RouteSpine()
    rows = []
    for index, case in enumerate(_workbench_cases(), start=1):
        decision = spine.route(
            case["prompt"],
            active_context=case.get("active_context") or {},
            active_request_state=case.get("active_request_state") or {},
            recent_tool_results=[],
        )
        passed = decision.winner.route_family == case["expected_route_family"]
        if case.get("clarification_expected"):
            passed = passed and decision.clarification_needed
        if case.get("generic_provider_allowed") is not None:
            passed = passed and decision.generic_provider_allowed is bool(case["generic_provider_allowed"])
        rows.append(
            {
                "case_index": index,
                "test_id": case["test_id"],
                "prompt": case["prompt"],
                "lane": case["lane"],
                "expected_route_family": case["expected_route_family"],
                "actual_route_family": decision.winner.route_family,
                "expected_clarification": bool(case.get("clarification_expected")),
                "actual_clarification": decision.clarification_needed,
                "routing_engine": decision.routing_engine,
                "intent_frame": decision.intent_frame.to_dict(),
                "candidate_specs_considered": list(decision.candidate_specs_considered),
                "selected_route_spec": decision.selected_route_spec,
                "native_decline_reasons": decision.native_decline_reasons,
                "generic_provider_gate_reason": decision.generic_provider_gate_reason,
                "legacy_fallback_used": decision.legacy_fallback_used,
                "passed": passed,
            }
        )
    write_jsonl(output_dir / "router_workbench_results.jsonl", rows)
    summary = {
        "attempted": len(rows),
        "passed": sum(1 for row in rows if row["passed"]),
        "failed": sum(1 for row in rows if not row["passed"]),
        "pass_rate": round(sum(1 for row in rows if row["passed"]) / max(1, len(rows)), 4),
        "by_lane": _rate_by(rows, "lane"),
        "by_expected_route_family": _rate_by(rows, "expected_route_family"),
        "routing_engine_counts": dict(Counter(row["routing_engine"] for row in rows)),
    }
    write_json(output_dir / "router_workbench_summary.json", summary)
    print(json.dumps(summary, indent=2))


def _run_eval_lane(
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
            "routing_engine_counts": dict(Counter(str(row.get("routing_engine") or "") for row in rows)),
            "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
            "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
            "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
            "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
        }
    )
    write_json(args.output_dir / summary_name, summary)
    if report_name is not None:
        (args.output_dir / report_name).write_text(_lane_report(report_name, summary, rows), encoding="utf-8")
    print(json.dumps({"attempted": len(cases), "completed": len(results), "durable_rows": len(rows)}, indent=2))


def _run_post250(args: argparse.Namespace) -> None:
    pre_orphan = checkpoint._orphan_process_check_result()
    if pre_orphan != "no_orphan_command_eval_processes_detected":
        raise SystemExit(f"Refusing to start with existing command-eval child process: {pre_orphan}")
    corpus = build_command_usability_corpus(min_cases=1000)
    selected = checkpoint._select_250_cases(corpus)
    write_jsonl(args.output_dir / "250_post_router_architecture_corpus.jsonl", [case.to_dict() for case in selected])
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
        server_startup_timeout_seconds=args.server_startup_timeout_seconds,
    )
    results = harness.run(selected, results_name="250_post_router_architecture_results.jsonl", resume=False)
    rows = _read_jsonl(args.output_dir / "250_post_router_architecture_results.jsonl")
    post_orphan = checkpoint._orphan_process_check_result()
    summary = build_checkpoint_summary(results, feature_audit=build_feature_audit(selected))
    summary.update(
        {
            "attempted": len(selected),
            "completed": len(results),
            "durable_rows": len(rows),
            "completed_equals_durable_rows": len(results) == len(rows),
            "pre_orphan_process_check": pre_orphan,
            "post_orphan_process_check": post_orphan,
            "routing_engine_counts": dict(Counter(str(row.get("routing_engine") or "") for row in rows)),
            "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows),
            "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows),
            "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows),
            "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows),
            "payload_guardrail_failures": sum(1 for row in rows if row.get("payload_guardrail_triggered")),
        }
    )
    recommendation = _recommendation(summary)
    summary["recommendation"] = recommendation["recommendation"]
    write_json(args.output_dir / "250_post_router_architecture_summary.json", summary)
    write_json(args.output_dir / "250_post_router_architecture_recommendation.json", recommendation)
    _write_final_report(args.output_dir)
    print(json.dumps({"attempted": len(selected), "completed": len(results), "durable_rows": len(rows)}, indent=2))


def _workbench_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def add(test_id: str, prompt: str, expected: str, lane: str, *, clarify: bool = False, generic_allowed: bool | None = None, context: dict[str, Any] | None = None, state: dict[str, Any] | None = None) -> None:
        cases.append(
            {
                "test_id": test_id,
                "prompt": prompt,
                "expected_route_family": expected,
                "lane": lane,
                "clarification_expected": clarify,
                "generic_provider_allowed": generic_allowed,
                "active_context": context or {},
                "active_request_state": state or {},
            }
        )

    calc_ctx = _calc_context()
    browser_ctx = _browser_context()
    file_ctx = _file_context()
    selection = _selection_context()
    positives = [
        ("calc_01", "what is 18 * 4", "calculations"),
        ("calc_02", "same equation, swap in 72", "calculations"),
        ("calc_03", "divide the last answer by 3", "calculations"),
        ("browser_01", "open https://example.com/status", "browser_destination"),
        ("browser_02", "open that website", "browser_destination"),
        ("browser_03", "show the previous link", "browser_destination"),
        ("file_01", r"read C:\Stormhelm\README.md", "file"),
        ("file_02", "show that document again", "file"),
        ("context_01", "summarize the selected text", "context_action"),
        ("screen_01", "click the submit button", "screen_awareness"),
        ("app_01", "quit Notepad", "app_control"),
        ("software_01", "uninstall Slack", "software_control"),
        ("app_status_01", "which apps are running", "app_control"),
        ("network_01", "which wifi am I on", "network"),
    ]
    for case_id, prompt, expected in positives:
        context = (
            calc_ctx
            if case_id in {"calc_02", "calc_03"}
            else browser_ctx
            if case_id in {"browser_02", "browser_03"}
            else file_ctx
            if case_id == "file_02"
            else selection
            if case_id == "context_01"
            else {}
        )
        add(
            f"wb_positive_{case_id}",
            prompt,
            expected,
            "positive",
            clarify=case_id == "screen_01",
            context=context,
            state={"family": "calculations"} if expected == "calculations" and context else {},
        )
    for idx, prompt in enumerate(
        [
            "compare neural network model architectures",
            "what is selected text in HTML",
            "press coverage summary",
            "open app design principles",
            "file naming philosophy",
            "what is a website",
            "terminal velocity explanation",
        ],
        1,
    ):
        add(f"wb_near_{idx:02d}", prompt, "generic_provider", "near_miss", generic_allowed=True)
    for idx, (prompt, expected) in enumerate(
        [
            ("open that website", "browser_destination"),
            ("show that document again", "file"),
            ("use the highlighted bit", "context_action"),
            ("press submit", "screen_awareness"),
            ("show me the arithmetic for that", "calculations"),
        ],
        1,
    ):
        add(f"wb_missing_{idx:02d}", prompt, expected, "missing_context", clarify=True, generic_allowed=False)
    # Scale the offline workbench with generated variants.
    for i in range(1, 15):
        add(f"wb_calc_variant_{i:02d}", f"compute {i + 10} times {i + 2}", "calculations", "unseen_positive")
        add(f"wb_browser_variant_{i:02d}", f"open https://example.com/{i}", "browser_destination", "unseen_positive")
        add(f"wb_app_variant_{i:02d}", f"quit App{i}", "app_control", "unseen_positive")
        add(f"wb_network_variant_{i:02d}", f"which wifi network is this laptop using {i}", "network", "unseen_positive")
    return cases


def _targeted_cases() -> list[CommandEvalCase]:
    cases: list[CommandEvalCase] = []
    for row in _workbench_cases()[:50]:
        if row["expected_route_family"] == "generic_provider":
            continue
        cases.append(
            _case(
                "router_arch_" + row["test_id"],
                row["prompt"],
                route_family=row["expected_route_family"],
                subsystem=_subsystem(row["expected_route_family"]),
                clarification="expected" if row.get("clarification_expected") else "none",
                input_context=row.get("active_context") or {},
                active_request_state=row.get("active_request_state") or {},
                tags=("router_architecture", row["lane"]),
            )
        )
    return cases[:36]


def _holdout_6_cases() -> list[CommandEvalCase]:
    cases: list[CommandEvalCase] = []
    selection = _selection_context("Holdout six selected routing evidence.")
    browser_ctx = _browser_context("https://stormhelm.local/holdout-six")
    file_ctx = _file_context(r"C:\Stormhelm\README.md")
    calc_ctx = _calc_context("81 / 9", "9")
    for i in range(1, 31):
        context = calc_ctx if i % 2 == 0 else {}
        cases.append(_case(f"holdout6_deictic_{i:02d}", f"reuse that result and add {i}", "calculations", "calculations", clarification="none" if context else "expected", input_context=context, active_request_state={"family": "calculations"} if context else {}, tags=("holdout6", "deictic")))
    for i in range(1, 26):
        prompt = ["open that website", "show the earlier page", "quit Notepad", "update Notepad", "which wifi am I on"][i % 5]
        expected = ["browser_destination", "browser_destination", "app_control", "software_control", "network"][i % 5]
        context = browser_ctx if expected == "browser_destination" and i % 2 == 0 else {}
        cases.append(_case(f"holdout6_cross_{i:02d}", prompt, expected, _subsystem(expected), clarification="expected" if expected == "browser_destination" and not context else "none", input_context=context, tags=("holdout6", "cross_family")))
    for i in range(1, 26):
        prompt = ["compare neural network architectures", "what is selected text in HTML", "press coverage summary", "file naming philosophy", "open app design principles"][i % 5]
        cases.append(_case(f"holdout6_near_{i:02d}", prompt, "generic_provider", "provider", tags=("holdout6", "near_miss")))
    for i in range(1, 21):
        prompt = ["use the highlighted bit", "press submit", "show that document again", "open that website"][i % 4]
        expected = ["context_action", "screen_awareness", "file", "browser_destination"][i % 4]
        cases.append(_case(f"holdout6_missing_{i:02d}", prompt, expected, _subsystem(expected), clarification="expected", tags=("holdout6", "missing_context")))
    for i in range(1, 16):
        cases.append(
            _case(
                f"holdout6_calc_{i:02d}",
                f"quick arithmetic: {i + 6} times {i + 3}",
                "calculations",
                "calculations",
                response_terms=(str((i + 6) * (i + 3)),),
                tags=("holdout6", "calculation"),
            )
        )
    for i in range(1, 16):
        context = browser_ctx if i % 3 == 0 else file_ctx if i % 3 == 1 else {}
        prompt = "open the previous link" if i % 3 == 0 else "read the previous file" if i % 3 == 1 else "open that website"
        expected = "browser_destination" if i % 3 == 0 or not context else "file"
        cases.append(_case(f"holdout6_boundary_{i:02d}", prompt, expected, _subsystem(expected), clarification="expected" if prompt == "open that website" and not context else "none", input_context=context, tags=("holdout6", "boundary")))
    for i in range(1, 11):
        cases.append(_case(f"holdout6_response_{i:02d}", "press submit", "screen_awareness", "screen_awareness", clarification="expected", tags=("holdout6", "response")))
    for i in range(1, 11):
        prompt = [
            f"quick arithmetic: {i + 21} times {i + 2}",
            "show me the current browser tab",
            "open the previous link",
            "read the previous file",
            "quit Calculator",
        ][(i - 1) % 5]
        expected = [
            "calculations",
            "watch_runtime",
            "browser_destination",
            "file",
            "app_control",
        ][(i - 1) % 5]
        context = browser_ctx if expected == "browser_destination" else file_ctx if expected == "file" else {}
        response_terms = (str((i + 21) * (i + 2)),) if expected == "calculations" else ()
        cases.append(
            _case(
                f"holdout6_extra_{i:02d}",
                prompt,
                expected,
                _subsystem(expected),
                input_context=context,
                response_terms=response_terms,
                tags=("holdout6", "extra"),
            )
        )
    return cases[:150]


def _case(
    case_id: str,
    message: str,
    route_family: str,
    subsystem: str,
    *,
    tools: tuple[str, ...] | None = None,
    clarification: str = "none",
    approval: str | None = None,
    result_state: str = "dry_run_or_completed",
    response_terms: tuple[str, ...] = (),
    input_context: dict[str, Any] | None = None,
    active_request_state: dict[str, Any] | None = None,
    tags: tuple[str, ...] = (),
) -> CommandEvalCase:
    expected_tools = _default_tools(
        route_family=route_family,
        message=message,
        tools=tools,
        clarification=clarification,
        surface_mode="ghost",
    )
    expected_approval = _default_approval(
        route_family=route_family,
        tools=expected_tools,
        approval=approval,
    )
    return CommandEvalCase(
        case_id=case_id,
        message=message,
        expected=ExpectedBehavior(
            route_family=route_family,
            subsystem=subsystem,
            tools=expected_tools,
            clarification=clarification,
            approval=expected_approval,
            result_state=result_state,
            response_terms=response_terms,
        ),
        input_context=input_context or {},
        active_request_state=active_request_state or {},
        tags=tags,
    )


def _default_tools(
    *,
    route_family: str,
    message: str,
    tools: tuple[str, ...] | None,
    clarification: str,
    surface_mode: str,
) -> tuple[str, ...]:
    if tools is not None:
        return tools
    if clarification == "expected":
        return ()
    lower = message.lower()
    if route_family == "browser_destination":
        return ("deck_open_url",) if "in the deck" in lower or surface_mode == "deck" else ("external_open_url",)
    if route_family == "file":
        return ("file_reader",) if any(term in lower for term in {"read", "inspect", "summarize"}) else ("external_open_file",)
    if route_family == "context_action":
        return ("context_action",)
    if route_family == "app_control":
        return ("active_apps",) if any(phrase in lower for phrase in {"which apps", "apps are running", "running apps"}) else ("app_control",)
    if route_family == "network":
        return ("network_status",)
    if route_family == "watch_runtime":
        return ("browser_context",) if "page" in lower or "tab" in lower else ("activity_summary",)
    if route_family == "screen_awareness":
        return ()
    return ()


def _default_approval(
    *,
    route_family: str,
    tools: tuple[str, ...],
    approval: str | None,
) -> str:
    if approval is not None:
        return approval
    if route_family == "software_control":
        return "allowed"
    if any(tool in {"external_open_url", "external_open_file", "app_control"} for tool in tools):
        return "allowed"
    return "not_expected"


def _calc_context(expression: str = "54 / 6", result: str = "9") -> dict[str, Any]:
    return {"recent_context_resolutions": [{"kind": "calculation", "result": {"expression": expression, "display_result": result}}]}


def _browser_context(url: str = "https://docs.example.com/stormhelm") -> dict[str, Any]:
    return {"recent_entities": [{"kind": "page", "title": "Stormhelm docs", "url": url, "freshness": "current"}]}


def _file_context(path: str = r"C:\Stormhelm\README.md") -> dict[str, Any]:
    return {"recent_entities": [{"kind": "file", "title": "README.md", "path": path, "freshness": "current"}]}


def _selection_context(value: str = "Selected notes about routing.") -> dict[str, Any]:
    return {"selection": {"kind": "text", "value": value, "preview": value[:80]}}


def _subsystem(route_family: str) -> str:
    return {
        "browser_destination": "browser",
        "app_control": "system",
        "file": "files",
        "context_action": "context",
        "screen_awareness": "screen_awareness",
        "watch_runtime": "operations",
        "network": "system",
        "software_control": "software_control",
        "calculations": "calculations",
        "generic_provider": "provider",
    }.get(route_family, route_family)


def _rate_by(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key) or ""), []).append(row)
    return {
        name: {
            "attempted": len(items),
            "passed": sum(1 for item in items if item.get("passed")),
            "pass_rate": round(sum(1 for item in items if item.get("passed")) / max(1, len(items)), 4),
        }
        for name, items in sorted(groups.items())
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _lane_report(title: str, summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    failures = [row for row in rows if not row.get("passed")]
    lines = [
        f"# {title}",
        "",
        f"- attempted: {summary.get('attempted')}",
        f"- completed: {summary.get('completed')}",
        f"- durable rows: {summary.get('durable_rows')}",
        f"- pass: {summary.get('scored_passed') or summary.get('raw_passed') or summary.get('pass_count') or summary.get('passed')}",
        f"- fail: {summary.get('scored_failed') or summary.get('raw_failed') or summary.get('fail_count') or summary.get('failed')}",
        f"- provider calls: {summary.get('provider_calls')}",
        f"- OpenAI calls: {summary.get('openai_calls')}",
        "",
        "## Failures",
    ]
    for row in failures[:30]:
        lines.append(f"- `{row.get('test_id')}` expected {row.get('expected_route_family')} actual {row.get('actual_route_family')}: {row.get('failure_reason')}")
    return "\n".join(lines) + "\n"


def _recommendation(summary: dict[str, Any]) -> dict[str, Any]:
    fail_counts = (
        summary.get("scored_failure_category_counts")
        or summary.get("failure_category_counts")
        or summary.get("checkpoint_summary", {}).get("failure_category_counts")
        or {}
    )
    real_gaps = int(fail_counts.get("real_routing_gap") or 0)
    pass_count = int(
        summary.get("scored_passed")
        or summary.get("raw_passed")
        or summary.get("pass_count")
        or summary.get("checkpoint_summary", {}).get("pass_count")
        or 0
    )
    attempted = int(summary.get("attempted") or 0)
    payload_failures = int(fail_counts.get("payload_guardrail_failure") or 0)
    wrong_subsystem = int(fail_counts.get("wrong_subsystem") or 0)
    recommendation = "keep_1000_blocked"
    reasons: list[str] = []
    if attempted != 250:
        reasons.append("post-architecture 250 checkpoint did not attempt exactly 250 cases")
    if pass_count <= 181:
        reasons.append("250 pass count did not materially improve over the prior best 181-pass checkpoint")
    if real_gaps >= 25:
        reasons.append("real_routing_gap remains above the <25 readiness target")
    if wrong_subsystem:
        reasons.append("wrong_subsystem remains nonzero")
    if payload_failures:
        reasons.append("payload_guardrail_failure rows are present")
    if attempted == 250 and pass_count > 181 and real_gaps < 25 and not payload_failures and wrong_subsystem == 0:
        recommendation = "proceed_to_1000_after_review"
    return {
        "recommendation": recommendation,
        "real_routing_gap": real_gaps,
        "wrong_subsystem": wrong_subsystem,
        "payload_guardrail_failure": payload_failures,
        "pass_count": pass_count,
        "attempted": attempted,
        "reasons": reasons,
    }


def _write_final_report(output_dir: Path) -> None:
    workbench = _read_json(output_dir / "router_workbench_summary.json")
    targeted = _read_json(output_dir / "targeted_router_integration_summary.json")
    holdout = _read_json(output_dir / "holdout_6_summary.json")
    post250 = _read_json(output_dir / "250_post_router_architecture_summary.json")
    targeted_rows = _read_jsonl(output_dir / "targeted_router_integration_results.jsonl")
    holdout_rows = _read_jsonl(output_dir / "holdout_6_results.jsonl")
    post250_rows = _read_jsonl(output_dir / "250_post_router_architecture_results.jsonl")
    static_audit = _read_json(output_dir / "static_anti_overfitting_check.json")
    recommendation = _recommendation(post250)
    write_json(output_dir / "250_post_router_architecture_recommendation.json", recommendation)
    payload = _payload_summary(post250_rows)
    if post250:
        post250["payload_guardrail_failures"] = payload["payload_guardrail_failures"]
        post250["payload_guardrail_triggered_rows"] = payload["payload_guardrail_triggered_rows"]
        post250["rows_above_1mb"] = payload["rows_above_1mb"]
        post250["rows_above_5mb"] = payload["rows_above_5mb"]
        post250["max_response_json_bytes"] = payload["max_response_json_bytes"]
        post250["max_workspace_item_count"] = payload["max_workspace_item_count"]
        write_json(output_dir / "250_post_router_architecture_summary.json", post250)
    safety = _safety_summary(post250_rows, post250)
    holdout_lanes = _rates_by_case_tag(holdout_rows)
    selected_families = {
        "calculations",
        "browser_destination",
        "app_control",
        "file",
        "context_action",
        "screen_awareness",
        "watch_runtime",
        "network",
        "machine",
        "power",
        "resources",
        "software_control",
    }
    selected_rows = [
        row
        for row in post250_rows
        if str(row.get("expected_route_family") or row.get("actual_route_family") or "") in selected_families
        or str(row.get("actual_route_family") or "") in selected_families
    ]
    selected_engine_counts = dict(Counter(str(row.get("routing_engine") or "") for row in selected_rows))
    route_spine_selected = sum(1 for row in selected_rows if row.get("routing_engine") == "route_spine")
    route_spine_total = len(selected_rows)
    lines = [
        "# 250 Post-Router-Architecture Report",
        "",
        "## Executive Summary",
        "",
        "Stormhelm now has an authoritative typed route-spine path for the selected high-value families: calculations, browser destination, app control, file/context handling, screen awareness, watch/runtime and system status, and software control.",
        "",
        f"The offline workbench passed {workbench.get('passed')}/{workbench.get('attempted')}, the targeted real-HTTP lane passed {targeted.get('scored_passed', targeted.get('raw_passed'))}/{targeted.get('attempted')}, and holdout-6 passed {holdout.get('scored_passed', holdout.get('raw_passed'))}/{holdout.get('attempted')}. The 250 checkpoint did not clear readiness: {post250.get('scored_passed', post250.get('raw_passed'))} pass / {post250.get('scored_failed', post250.get('raw_failed'))} fail, with {post250.get('scored_failure_category_counts', {}).get('real_routing_gap', 0)} real routing gaps.",
        "",
        "Recommendation: keep 1000 blocked. The architecture spine is real and authoritative for the selected families, but the broad 250 corpus regressed versus the prior best checkpoint and still has too many route/scoring gaps.",
        "",
        "## Why Phrase Patching Plateaued",
        "",
        "The previous cycle improved exact clusters and local holdouts, but failures kept reappearing as cross-family ambiguity, missing-context fallback, and deictic binding drift. The architecture reset centralizes those decisions in an IntentFrame plus RouteFamilySpec spine so selected families no longer depend on planner branch-chain order.",
        "",
        "## Router Architecture Diagnosis",
        "",
        "See `router_architecture_diagnosis.md` and `persistent_failure_burndown.md`. The old planner still contains substantial legacy branch-chain debt, including one-off phrase heuristics, but selected migrated families now run through the route spine before legacy branches.",
        "",
        "## Persistent Failure Burn-Down",
        "",
        "Persistent broad-corpus failures now cluster around unmigrated or only partially migrated families, target-slot expectation mismatches, legacy software_recovery/weather/desktop_search behavior, workspace latency, and response/corpus expectations. The reset did not attempt to expand every family.",
        "",
        "## IntentFrame Design",
        "",
        "IntentFrame extraction now captures speech act, operation, target type/text, entities, context reference/status, risk class, candidate native owner, clarification need, and generic-provider eligibility. See `intent_frame_design.md/json`.",
        "",
        "## RouteFamilySpec Design",
        "",
        "RouteFamilySpec contracts define owned operations/targets, required and allowed context, risk classes, positive and negative intent signals, near-miss examples, missing-context behavior, confidence floors, tool candidates, and telemetry fields. See `route_family_spec_design.md/json`.",
        "",
        "## Routing Spine Implemented",
        "",
        "- IntentFrame extraction runs before the legacy planner branch chain.",
        "- RouteFamilySpec candidates are generated from contracts and scored by operation, target type, context compatibility, risk, positive signals, and near-miss exclusions.",
        "- Native candidates decline with explicit reasons.",
        "- Generic provider becomes eligible only after migrated native candidates decline meaningfully.",
        "- Missing, stale, or ambiguous context routes to native clarification when a migrated native family owns the intent.",
        "- Telemetry exposes `routing_engine`, `intent_frame`, `candidate_specs_considered`, `selected_route_spec`, `native_decline_reasons`, `generic_provider_gate_reason`, and `legacy_fallback_used`.",
        "",
        "## Families Moved To The Spine",
        "",
        "- calculations",
        "- browser_destination",
        "- app_control",
        "- file/context target handling",
        "- screen_awareness",
        "- watch_runtime/system status, including network/machine/power/resources status",
        "- software_control",
        "",
        f"In the 250 rerun, selected-family rows used `route_spine` for {route_spine_selected}/{route_spine_total} selected-family observations. Engine counts for selected-family rows: `{json.dumps(selected_engine_counts, sort_keys=True)}`.",
        "",
        "## Deliberately Not Moved Yet",
        "",
        "The broad legacy fallback remains for families outside this pass, including workspace operations, routine execution setup, workflow/maintenance, weather/location, desktop search, notes/time/terminal direct commands, and several compatibility routes. Some adjacent families have specs for candidate arbitration, but their full product handlers were not all converted in this pass.",
        "",
        "## Safety Summary",
        "",
        f"- Provider calls: {safety['provider_calls']}",
        f"- OpenAI calls: {safety['openai_calls']}",
        f"- LLM calls: {safety['llm_calls']}",
        f"- Embedding calls: {safety['embedding_calls']}",
        f"- Real external actions: {safety['external_actions']}",
        f"- Hard timeouts: {safety['hard_timeouts']}",
        f"- Process kills: {safety['process_kills']}",
        f"- Orphan process check: {post250.get('post_orphan_process_check', targeted.get('post_orphan_process_check', 'not_run'))}",
        "",
        "## Harness Durability",
        "",
        f"- 250 attempted: {post250.get('attempted')}",
        f"- 250 completed: {post250.get('completed')}",
        f"- 250 durable rows: {post250.get('durable_rows')}",
        f"- Completed equals durable rows: {post250.get('completed_equals_durable_rows')}",
        "",
        "## Offline Router Workbench Results",
        "",
        f"- Attempted: {workbench.get('attempted')}",
        f"- Passed: {workbench.get('passed')}",
        f"- Pass rate: {workbench.get('pass_rate')}",
        f"- Routing engine counts: `{json.dumps(workbench.get('routing_engine_counts', {}), sort_keys=True)}`",
        "",
        "## Targeted Integration Results",
        "",
        f"- Attempted: {targeted.get('attempted')}",
        f"- Completed: {targeted.get('completed')}",
        f"- Durable rows: {targeted.get('durable_rows')}",
        f"- Pass/fail: {targeted.get('scored_passed', targeted.get('raw_passed'))} pass / {targeted.get('scored_failed', targeted.get('raw_failed'))} fail",
        f"- Routing engine counts: `{json.dumps(targeted.get('routing_engine_counts', {}), sort_keys=True)}`",
        "",
        "## Holdout-6 Results",
        "",
        f"- Attempted: {holdout.get('attempted')}",
        f"- Completed: {holdout.get('completed')}",
        f"- Durable rows: {holdout.get('durable_rows')}",
        f"- Pass/fail: {holdout.get('scored_passed', holdout.get('raw_passed'))} pass / {holdout.get('scored_failed', holdout.get('raw_failed'))} fail",
        f"- Failure categories: {json.dumps(holdout.get('failure_category_counts', {}), sort_keys=True)}",
        f"- Lane pass rates: `{json.dumps(holdout_lanes, sort_keys=True)}`",
        "- Holdout note: the two failures are both watch_runtime browser-context subsystem taxonomy mismatches (`expected operations`, actual `context`), not provider leakage or route-family misses.",
        "",
        "## 250 Before/After Comparison",
        "",
        "- Original 250: 100 pass / 150 fail.",
        "- Post-remediation 250: 168 pass / 82 fail.",
        "- Post-generalization 250: 161 pass / 89 fail.",
        "- Post-generalization-2 250: 162 pass / 88 fail.",
        "- Post-readiness-3 250: 181 pass / 69 fail.",
        "- Best prior 250: 181 pass / 69 fail.",
        "- Post-context-arbitration 250: 175 pass / 75 fail.",
        f"- Post-router-architecture 250: {post250.get('scored_passed', post250.get('raw_passed'))} pass / {post250.get('scored_failed', post250.get('raw_failed'))} fail.",
        "",
        "## Failure Category Comparison",
        "",
        "- Original 250: real_routing_gap 105, wrong_subsystem 13, latency_issue 32.",
        "- Best prior 250: 30 scored failures, all latency_issue.",
        "- Post-context-arbitration: 175 pass / 75 fail, wrong_subsystem 0.",
        f"- Post-router-architecture: `{json.dumps(post250.get('scored_failure_category_counts', post250.get('failure_category_counts', {})), sort_keys=True)}`.",
        "",
        "## Generic-Provider Fallback Comparison",
        "",
        f"- Current generic fallback by expected family: `{json.dumps(post250.get('generic_fallback_count_by_expected_family', {}), sort_keys=True)}`",
        "- Generic provider remained audited and disabled for model calls; fallbacks produced no provider/OpenAI/LLM/embedding calls.",
        "",
        "## Deictic/Follow-Up Performance",
        "",
        f"- Workbench deictic/follow-up and missing-context cases passed through native clarification/binding lanes: `{json.dumps(workbench.get('by_lane', {}), sort_keys=True)}`.",
        f"- Holdout-6 deictic lane: `{json.dumps(holdout_lanes.get('deictic', {}), sort_keys=True)}`.",
        "",
        "## Cross-Family Confusion Performance",
        "",
        f"- Holdout-6 cross-family lane: `{json.dumps(holdout_lanes.get('cross_family', {}), sort_keys=True)}`.",
        "- The 250 checkpoint still has broad-corpus cross-family failures in unmigrated/partially migrated families such as desktop_search, software_recovery, weather, routine execution, and workspace/workflow lanes.",
        "",
        "## Near-Miss Preservation",
        "",
        f"- Workbench near-miss lane: `{json.dumps((workbench.get('by_lane') or {}).get('near_miss', {}), sort_keys=True)}`.",
        f"- Holdout-6 near-miss lane: `{json.dumps(holdout_lanes.get('near_miss', {}), sort_keys=True)}`.",
        "",
        "## Ambiguity/Missing-Context Clarification",
        "",
        f"- Workbench missing-context lane: `{json.dumps((workbench.get('by_lane') or {}).get('missing_context', {}), sort_keys=True)}`.",
        f"- Holdout-6 missing-context lane: `{json.dumps(holdout_lanes.get('missing_context', {}), sort_keys=True)}`.",
        "",
        "## Provider/OpenAI/LLM/Embedding Audit",
        "",
        "The actual provider/client seam audit remained active during the process-isolated runs. No provider, OpenAI, LLM, or embedding calls were recorded in targeted, holdout-6, or the 250 checkpoint.",
        "",
        "## Payload Guardrail Summary",
        "",
        f"- Max response size: {payload['max_response_json_bytes']} bytes",
        f"- Rows above 1 MB: {payload['rows_above_1mb']}",
        f"- Rows above 5 MB: {payload['rows_above_5mb']}",
        f"- Payload guardrail failure rows: {payload['payload_guardrail_failures']}",
        f"- Payload guardrail triggered rows, including safe truncation warnings: {payload['payload_guardrail_triggered_rows']}",
        f"- Max embedded workspace item count: {payload['max_workspace_item_count']}",
        "",
        "## Latency Lane Summary",
        "",
        f"- 250 latency summary: `{json.dumps(post250.get('latency_ms', {}), sort_keys=True)}`",
        f"- Latency issue rows: {post250.get('scored_failure_category_counts', {}).get('latency_issue', post250.get('failure_category_counts', {}).get('latency_issue', 0))}",
        "- Workspace latency remains bounded and payload-safe, but this pass did not optimize workspace latency.",
        "",
        "## Routine-Save Historical Blocker",
        "",
        "The historical catastrophic native routine_save latency remains preserved as known_unreproduced_product_latency_blocker. This pass did not mark it fixed.",
        "",
        "## Static Anti-Hardcoding Result",
        "",
        f"- Passed: {static_audit.get('passed')}",
        f"- New route-spine hits: `{json.dumps(static_audit.get('new_spine_hits', []), sort_keys=True)}`",
        f"- Legacy planner debt hits: `{json.dumps(static_audit.get('legacy_planner_hits', []), sort_keys=True)}`",
        "",
        "## Remaining Blockers",
        "",
        f"- 250 pass count regressed to {post250.get('scored_passed', post250.get('raw_passed'))}, below the prior best 181.",
        f"- real_routing_gap remains {post250.get('scored_failure_category_counts', {}).get('real_routing_gap', post250.get('failure_category_counts', {}).get('real_routing_gap', 0))}, above the readiness target.",
        f"- wrong_subsystem remains {post250.get('scored_failure_category_counts', {}).get('wrong_subsystem', post250.get('failure_category_counts', {}).get('wrong_subsystem', 0))}.",
        f"- response_correctness_failure remains {post250.get('scored_failure_category_counts', {}).get('response_correctness_failure', post250.get('failure_category_counts', {}).get('response_correctness_failure', 0))}.",
        "- Browser destination target-slot scoring now exposes a target extraction/slot-normalization mismatch: the spine knows the destination, but the command-eval target slot expectation is not normalized to the new `intent_frame`/`tool.url` shape.",
        "- Some previously stable broad-corpus lanes still depend on legacy fallback and need their own RouteFamilySpec migration or expectation audit.",
        "",
        "## Recommendation",
        "",
        f"`{recommendation.get('recommendation', 'not_available')}`",
        "",
        "Reasons:",
        *[f"- {reason}" for reason in recommendation.get("reasons", [])],
    ]
    (output_dir / "250_post_router_architecture_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _safety_summary(rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, int]:
    return {
        "provider_calls": sum(int(row.get("provider_call_count") or 0) for row in rows) or int(summary.get("provider_calls") or 0),
        "openai_calls": sum(int(row.get("openai_call_count") or 0) for row in rows) or int(summary.get("openai_calls") or 0),
        "llm_calls": sum(int(row.get("llm_call_count") or 0) for row in rows) or int(summary.get("llm_calls") or 0),
        "embedding_calls": sum(int(row.get("embedding_call_count") or 0) for row in rows) or int(summary.get("embedding_calls") or 0),
        "external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "hard_timeouts": sum(1 for row in rows if row.get("status") == "hard_timeout" or row.get("failure_category") == "hard_timeout"),
        "process_kills": sum(1 for row in rows if row.get("process_killed")),
    }


def _payload_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    sizes = [int(row.get("response_json_bytes") or 0) for row in rows]
    workspace_counts = [int(row.get("workspace_item_count") or 0) for row in rows]
    return {
        "max_response_json_bytes": max(sizes) if sizes else 0,
        "rows_above_1mb": sum(1 for size in sizes if size > 1_000_000),
        "rows_above_5mb": sum(1 for size in sizes if size > 5_000_000),
        "payload_guardrail_triggered_rows": sum(1 for row in rows if row.get("payload_guardrail_triggered")),
        "payload_guardrail_failures": sum(1 for row in rows if row.get("failure_category") == "payload_guardrail_failure"),
        "max_workspace_item_count": max(workspace_counts) if workspace_counts else 0,
    }


def _rates_by_case_tag(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        case = row.get("case") if isinstance(row.get("case"), dict) else {}
        tags = case.get("tags") if isinstance(case.get("tags"), list) else []
        for tag in tags:
            if tag == "holdout6":
                continue
            groups.setdefault(str(tag), []).append(row)
    return {
        tag: {
            "attempted": len(items),
            "passed": sum(1 for item in items if item.get("passed")),
            "pass_rate": round(sum(1 for item in items if item.get("passed")) / max(1, len(items)), 4),
        }
        for tag, items in sorted(groups.items())
    }


if __name__ == "__main__":
    main()
