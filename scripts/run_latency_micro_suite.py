from __future__ import annotations

import argparse
import math
from collections import Counter
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from stormhelm.core.orchestrator.command_eval import CommandEvalCase
from stormhelm.core.orchestrator.command_eval import CommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_audit
from stormhelm.core.orchestrator.command_eval import build_feature_map
from stormhelm.core.orchestrator.command_eval.models import STAGE_LATENCY_FIELDS
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_report
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl


SLOW_CASE_IDS = (
    "workspace_assemble_canonical_00",
    "workspace_assemble_command_mode_00",
    "workspace_rename_canonical_00",
    "workspace_rename_command_mode_00",
    "workspace_tag_canonical_00",
    "workspace_tag_command_mode_00",
    "workspace_save_canonical_00",
    "workspace_save_command_mode_00",
    "maintenance_canonical_00",
    "maintenance_command_mode_00",
    "routine_execute_canonical_00",
    "routine_execute_command_mode_00",
    "routine_save_canonical_00",
    "routine_save_command_mode_00",
)

FAST_CONTROL_CASE_IDS = (
    "calculations_canonical_00",
    "browser_destination_canonical_00",
    "software_control_install_canonical_00",
    "desktop_search_canonical_00",
    "file_reader_canonical_00",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Stormhelm command latency micro-suite.")
    default_output = Path(".artifacts") / "command-usability-eval" / f"latency-micro-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--per-test-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--in-process", action="store_true", help="Use the legacy in-process ASGI harness for unit/smoke use only.")
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()

    corpus = build_command_usability_corpus(min_cases=1000)
    case_lookup = {case.case_id: case for case in corpus}
    micro_cases = build_latency_micro_cases(case_lookup, repeats=max(1, args.repeats))
    feature_map = build_feature_map()
    feature_audit = build_feature_audit(micro_cases)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "feature_map.json", feature_map)
    write_json(args.output_dir / "feature_map_audit.json", feature_audit)
    write_jsonl(args.output_dir / "latency_micro_corpus.jsonl", [case.to_dict() for case in micro_cases])

    harness_cls = CommandUsabilityHarness if args.in_process else ProcessIsolatedCommandUsabilityHarness
    harness_kwargs = {
        "output_dir": args.output_dir,
        "per_test_timeout_seconds": args.per_test_timeout_seconds,
        "history_strategy": "isolated_session",
    }
    if not args.in_process:
        harness_kwargs["server_startup_timeout_seconds"] = args.server_startup_timeout_seconds
        harness_kwargs["process_scope"] = args.process_scope
    harness = harness_cls(**harness_kwargs)
    results = harness.run(micro_cases, results_name="latency_micro_results.jsonl", resume=args.resume)

    checkpoint_summary = build_checkpoint_summary(results, feature_audit=feature_audit)
    write_json(args.output_dir / "latency_micro_checkpoint_summary.json", checkpoint_summary)
    (args.output_dir / "latency_micro_checkpoint_report.md").write_text(
        build_checkpoint_report(
            title="Stormhelm Latency Micro-Suite Checkpoint",
            results=results,
            feature_audit=feature_audit,
        ),
        encoding="utf-8",
    )

    triage_summary = build_latency_triage_summary(results)
    write_json(args.output_dir / "latency_triage_summary.json", triage_summary)
    (args.output_dir / "latency_triage_report.md").write_text(
        build_latency_triage_report(triage_summary),
        encoding="utf-8",
    )

    for name in (
        "latency_micro_results.jsonl",
        "latency_micro_checkpoint_summary.json",
        "latency_micro_checkpoint_report.md",
        "latency_triage_summary.json",
        "latency_triage_report.md",
    ):
        print(f"{name}: {args.output_dir / name}")


def build_latency_micro_cases(case_lookup: dict[str, CommandEvalCase], *, repeats: int) -> list[CommandEvalCase]:
    cases: list[CommandEvalCase] = []
    for source_id in (*SLOW_CASE_IDS, *FAST_CONTROL_CASE_IDS):
        source = case_lookup[source_id]
        kind_tag = "slow_family" if source_id in SLOW_CASE_IDS else "fast_control"
        for repeat_index in range(1, repeats + 1):
            cases.append(
                replace(
                    source,
                    case_id=f"{source.case_id}_rep{repeat_index:02d}",
                    session_id=f"latency-{source.case_id}-{repeat_index:02d}",
                    tags=tuple(dict.fromkeys((*source.tags, "latency_micro", kind_tag))),
                    notes=f"Latency micro-suite repeat {repeat_index} from {source.case_id}.",
                )
            )
    return cases


def build_latency_triage_summary(results: list[Any]) -> dict[str, Any]:
    rows = [result.to_dict() for result in results]
    slow_rows = [row for row in rows if _latency_row_kind(row) == "slow"]
    fast_rows = [row for row in rows if _latency_row_kind(row) == "fast"]
    return {
        "completed_requests": len(rows),
        "provider_calls": sum(1 for row in rows if row.get("provider_called")),
        "external_actions": sum(1 for row in rows if row.get("external_action_performed")),
        "timeouts": sum(1 for row in rows if row.get("result_state") == "timed_out"),
        "route_family_latency_summary": _route_family_summary(rows),
        "per_stage_timing_table": _stage_summary(rows),
        "slow_vs_fast_stage_delta": _slow_fast_stage_delta(slow_rows, fast_rows),
        "unattributed_latency": {
            "top_20": sorted(
                (_compact_latency_row(row) for row in rows),
                key=lambda row: float(row.get("unattributed_latency_ms") or 0.0),
                reverse=True,
            )[:20],
            "by_route_family": _route_family_unattributed_summary(rows),
            "repeated_case_variance": _repeat_variance(rows, field="unattributed_latency_ms"),
        },
        "repeated_case_variance": _repeat_variance(rows),
        "slowest_20_individual_runs": sorted(
            (_compact_latency_row(row) for row in rows),
            key=lambda row: float(row["total_latency_ms"]),
            reverse=True,
        )[:20],
        "root_cause_hypothesis": _root_cause_hypothesis(slow_rows, fast_rows),
        "observed_triage_ceiling": _observed_triage_ceiling(rows),
    }


def build_latency_triage_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Stormhelm Latency Micro-Suite Triage",
        "",
        "## Run Safety",
        f"- completed requests: {summary['completed_requests']}",
        f"- provider calls: {summary['provider_calls']}",
        f"- external actions: {summary['external_actions']}",
        f"- timeouts: {summary['timeouts']}",
        "",
        "## Per-Stage Timing Table",
        _format_nested(summary["per_stage_timing_table"]),
        "",
        "## Route-Family Latency Summary",
        _format_nested(summary["route_family_latency_summary"]),
        "",
        "## Slowest 20 Individual Runs",
        _format_slowest(summary["slowest_20_individual_runs"]),
        "",
        "## Repeated-Case Variance",
        _format_nested(summary["repeated_case_variance"]),
        "",
        "## Unattributed Latency",
        "Top 20 by unattributed latency:",
        _format_slowest(summary["unattributed_latency"]["top_20"]),
        "",
        "Route-family unattributed summary:",
        _format_nested(summary["unattributed_latency"]["by_route_family"]),
        "",
        "Repeated-case unattributed variance:",
        _format_nested(summary["unattributed_latency"]["repeated_case_variance"]),
        "",
        "## Slow Vs Fast Stage Delta",
        _format_nested(summary["slow_vs_fast_stage_delta"]),
        "",
        "## Root-Cause Hypothesis",
        f"- {summary['root_cause_hypothesis']}",
        "",
        "## Observed Triage Ceiling",
        _format_nested(summary["observed_triage_ceiling"]),
    ]
    return "\n".join(lines).strip() + "\n"


def _latency_row_kind(row: dict[str, Any]) -> str:
    tags = set(row.get("case", {}).get("tags", []) if isinstance(row.get("case"), dict) else [])
    if "slow_family" in tags:
        return "slow"
    if "fast_control" in tags:
        return "fast"
    family = str(row.get("expected_route_family") or "")
    if family in {"routine", "workspace_operations", "maintenance"}:
        return "slow"
    if family in {"calculations", "browser_destination", "software_control", "file", "desktop_search"}:
        return "fast"
    return ""


def _route_family_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("expected_route_family") or "<none>")].append(float(row.get("total_latency_ms") or 0.0))
    return {family: _stats(values) for family, values in sorted(grouped.items())}


def _route_family_unattributed_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("expected_route_family") or "<none>")].append(float(row.get("unattributed_latency_ms") or 0.0))
    return {family: _stats(values) for family, values in sorted(grouped.items())}


def _stage_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {field: _stats([float(row.get(field) or 0.0) for row in rows]) for field in STAGE_LATENCY_FIELDS}


def _slow_fast_stage_delta(slow_rows: list[dict[str, Any]], fast_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    deltas: dict[str, dict[str, Any]] = {}
    for field in STAGE_LATENCY_FIELDS:
        slow_values = [float(row.get(field) or 0.0) for row in slow_rows]
        fast_values = [float(row.get(field) or 0.0) for row in fast_rows]
        slow_median = median(slow_values) if slow_values else 0.0
        fast_median = median(fast_values) if fast_values else 0.0
        deltas[field] = {
            "slow_median_ms": round(slow_median, 3),
            "fast_median_ms": round(fast_median, 3),
            "delta_ms": round(slow_median - fast_median, 3),
        }
    return dict(sorted(deltas.items(), key=lambda item: float(item[1]["delta_ms"]), reverse=True))


def _repeat_variance(rows: list[dict[str, Any]], *, field: str = "total_latency_ms") -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        case_id = str(row.get("test_id") or "")
        source_id = case_id.rsplit("_rep", 1)[0]
        grouped[source_id].append(float(row.get(field) or 0.0))
    return {case_id: _stats(values, include_stdev=True) for case_id, values in sorted(grouped.items())}


def _root_cause_hypothesis(slow_rows: list[dict[str, Any]], fast_rows: list[dict[str, Any]]) -> str:
    deltas = _slow_fast_stage_delta(slow_rows, fast_rows)
    top = next(iter(deltas.items()), ("", {"delta_ms": 0.0}))
    top_field, top_data = top
    family_counts = Counter(row.get("expected_route_family") for row in slow_rows if float(row.get("total_latency_ms") or 0.0) > 2500)
    dominant_family = family_counts.most_common(1)[0][0] if family_counts else "slow targeted families"
    if top_field in {"route_handler_ms", "http_boundary_ms", "total_latency_ms"}:
        return (
            f"Slow targeted requests are dominated by {dominant_family}; the largest median delta is {top_field} "
            f"at {top_data['delta_ms']} ms. Because planner_route_ms, dry_run_executor_ms, event_collection_ms, "
            "and artifact_flush_ms are much smaller, the likely cause is work inside the selected route handler "
            "or direct subsystem service path rather than provider calls, external execution, or result writing."
        )
    if top_field == "planner_route_ms":
        return "Planner route scoring is the leading latency contributor; prioritize route-candidate pruning or cached scoring inputs."
    if top_field == "job_collection_ms":
        return "Job submit/wait collection is the leading latency contributor; inspect job-manager polling and dry-run executor dispatch."
    if top_field == "event_collection_ms":
        return "Event replay/collection is the leading latency contributor; inspect event-buffer replay filters and cursor handling."
    if top_field == "artifact_flush_ms":
        return "Artifact writing is the leading latency contributor; batch final rewrites and keep incremental rows compact."
    return f"The largest observed median delta is {top_field} at {top_data['delta_ms']} ms; inspect that stage first."


def _observed_triage_ceiling(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ceilings: dict[str, dict[str, Any]] = {}
    for family, stats in _route_family_summary(rows).items():
        p95 = float(stats.get("p95") or 0.0)
        guardrail_ms = max(2500.0, math.ceil(p95 / 500.0) * 500.0)
        target_budget_ms = 2500.0
        ship_budget_ms = 5000.0 if family in {"workspace_operations", "routine", "maintenance"} else 3000.0
        ceilings[family] = {
            "observed_p95_ms": round(p95, 3),
            "triage_guardrail_ms": round(guardrail_ms, 3),
            "target_budget_ms": round(target_budget_ms, 3),
            "ship_budget_ms": round(ship_budget_ms, 3),
            "acceptance_note": "Observed p95 is a triage ceiling, not an acceptable product budget.",
        }
    return ceilings


def _stats(values: list[float], *, include_stdev: bool = False) -> dict[str, Any]:
    values = sorted(values)
    if not values:
        return {"count": 0, "min": None, "median": None, "p90": None, "p95": None, "max": None}
    payload: dict[str, Any] = {
        "count": len(values),
        "min": round(values[0], 3),
        "median": round(_percentile(values, 0.5), 3),
        "p90": round(_percentile(values, 0.9), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "max": round(values[-1], 3),
    }
    if include_stdev:
        avg = sum(values) / len(values)
        payload["stdev_ms"] = round(math.sqrt(sum((value - avg) ** 2 for value in values) / len(values)), 3)
    return payload


def _percentile(values: list[float], p: float) -> float:
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def _compact_latency_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": row.get("test_id"),
        "expected_route_family": row.get("expected_route_family"),
        "actual_route_family": row.get("actual_route_family"),
        "actual_tool": row.get("actual_tool"),
        "total_latency_ms": row.get("total_latency_ms"),
        "http_boundary_ms": row.get("http_boundary_ms"),
        "planner_route_ms": row.get("planner_route_ms"),
        "route_handler_ms": row.get("route_handler_ms"),
        "job_collection_ms": row.get("job_collection_ms"),
        "dry_run_executor_ms": row.get("dry_run_executor_ms"),
        "event_collection_ms": row.get("event_collection_ms"),
        "artifact_flush_ms": row.get("artifact_flush_ms"),
        "unattributed_latency_ms": row.get("unattributed_latency_ms"),
        "failure_category": row.get("failure_category"),
    }


def _format_nested(rows: dict[str, dict[str, Any]]) -> str:
    if not rows:
        return "- No data."
    return "\n".join(f"- {key}: {dict(value)}" for key, value in rows.items())


def _format_slowest(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "- None."
    return "\n".join(
        "- `{test_id}` {total_latency_ms} ms | {expected_route_family}->{actual_route_family} | route_handler={route_handler_ms} ms | planner={planner_route_ms} ms | jobs={job_collection_ms} ms | tool={actual_tool}".format(**row)
        for row in rows
    )


if __name__ == "__main__":
    main()
