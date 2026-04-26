from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_latency_micro_suite import build_latency_triage_report
from scripts.run_latency_micro_suite import build_latency_triage_summary
from stormhelm.core.orchestrator.command_eval import CommandEvalCase
from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_audit
from stormhelm.core.orchestrator.command_eval import build_feature_map
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_report
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl


TINY_ATTRIBUTION_CASE_IDS = (
    "routine_save_canonical_00",
    "routine_save_command_mode_00",
    "routine_execute_canonical_00",
    "workspace_save_canonical_00",
    "calculations_canonical_00",
    "browser_destination_canonical_00",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the tiny process-isolated latency attribution suite.")
    default_output = Path(".artifacts") / "command-usability-eval" / f"latency-attribution-tiny-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--per-test-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_run")
    args = parser.parse_args()

    corpus = build_command_usability_corpus(min_cases=1000)
    case_lookup = {case.case_id: case for case in corpus}
    cases = _build_cases(case_lookup, repeats=max(1, args.repeats))
    feature_map = build_feature_map()
    feature_audit = build_feature_audit(cases)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "feature_map.json", feature_map)
    write_json(args.output_dir / "feature_map_audit.json", feature_audit)
    write_jsonl(args.output_dir / "latency_attribution_tiny_corpus.jsonl", [case.to_dict() for case in cases])

    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.per_test_timeout_seconds,
        history_strategy="isolated_session",
        process_scope=args.process_scope,
    )
    results = harness.run(cases, results_name="latency_attribution_tiny_results.jsonl", resume=args.resume)

    checkpoint_summary = build_checkpoint_summary(results, feature_audit=feature_audit)
    write_json(args.output_dir / "latency_attribution_tiny_checkpoint_summary.json", checkpoint_summary)
    (args.output_dir / "latency_attribution_tiny_checkpoint_report.md").write_text(
        build_checkpoint_report(
            title="Stormhelm Tiny Latency Attribution Checkpoint",
            results=results,
            feature_audit=feature_audit,
        ),
        encoding="utf-8",
    )
    triage_summary = build_latency_triage_summary(results)
    write_json(args.output_dir / "latency_attribution_tiny_summary.json", triage_summary)
    (args.output_dir / "latency_attribution_tiny_report.md").write_text(
        build_latency_triage_report(triage_summary),
        encoding="utf-8",
    )

    for name in (
        "latency_attribution_tiny_results.jsonl",
        "latency_attribution_tiny_checkpoint_summary.json",
        "latency_attribution_tiny_checkpoint_report.md",
        "latency_attribution_tiny_summary.json",
        "latency_attribution_tiny_report.md",
    ):
        print(f"{name}: {args.output_dir / name}")


def _build_cases(case_lookup: dict[str, CommandEvalCase], *, repeats: int) -> list[CommandEvalCase]:
    cases: list[CommandEvalCase] = []
    for source_id in TINY_ATTRIBUTION_CASE_IDS:
        source = case_lookup[source_id]
        kind_tag = "fast_control" if source.expected.route_family in {"calculations", "browser_destination"} else "slow_family"
        for repeat_index in range(1, repeats + 1):
            cases.append(
                replace(
                    source,
                    case_id=f"{source.case_id}_rep{repeat_index:02d}",
                    session_id=f"tiny-latency-{source.case_id}-{repeat_index:02d}",
                    tags=tuple(dict.fromkeys((*source.tags, "latency_attribution_tiny", kind_tag))),
                    notes=f"Tiny latency attribution repeat {repeat_index} from {source.case_id}.",
                )
            )
    return cases


if __name__ == "__main__":
    main()
