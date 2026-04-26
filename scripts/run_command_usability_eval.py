from __future__ import annotations

import argparse
from pathlib import Path

from stormhelm.core.orchestrator.command_eval import CommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval import build_feature_audit
from stormhelm.core.orchestrator.command_eval import build_feature_map
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_report
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_artifacts
from stormhelm.core.orchestrator.command_eval.report import write_json
from stormhelm.core.orchestrator.command_eval.report import write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stormhelm command usability and routing evaluation.")
    parser.add_argument("--output-dir", type=Path, default=Path(".artifacts") / "command-usability-eval" / "latest")
    parser.add_argument("--focused-limit", type=int, default=80)
    parser.add_argument("--full-limit", type=int, default=1000)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--resume", action="store_true", help="Skip case IDs already present in the result JSONL files.")
    parser.add_argument("--per-test-timeout-seconds", type=float, default=60.0, help="Per-request timeout, capped at 60 seconds.")
    parser.add_argument("--history-strategy", choices=["isolated_session", "shared_session"], default="isolated_session")
    parser.add_argument("--in-process", action="store_true", help="Use the legacy in-process ASGI harness for unit/smoke use only.")
    parser.add_argument("--server-startup-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--process-scope", choices=["per_case", "per_run"], default="per_case")
    parser.add_argument("--skip-focused", action="store_true")
    parser.add_argument("--skip-full", action="store_true")
    args = parser.parse_args()

    corpus = build_command_usability_corpus(min_cases=max(1000, args.full_limit))
    if args.case_id:
        requested = set(args.case_id)
        corpus = [case for case in corpus if case.case_id in requested]
    full_corpus = corpus[: args.full_limit] if not args.case_id else corpus
    focused_corpus = _focused_subset(full_corpus, limit=args.focused_limit)

    feature_map = build_feature_map()
    feature_audit = build_feature_audit(full_corpus)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "feature_map.json", feature_map)
    write_json(args.output_dir / "feature_map_audit.json", feature_audit)
    write_jsonl(args.output_dir / "corpus.jsonl", [case.to_dict() for case in full_corpus])
    harness_cls = CommandUsabilityHarness if args.in_process else ProcessIsolatedCommandUsabilityHarness
    harness_kwargs = {
        "output_dir": args.output_dir,
        "per_test_timeout_seconds": args.per_test_timeout_seconds,
        "history_strategy": args.history_strategy,
    }
    if not args.in_process:
        harness_kwargs["server_startup_timeout_seconds"] = args.server_startup_timeout_seconds
        harness_kwargs["process_scope"] = args.process_scope
    harness = harness_cls(**harness_kwargs)
    focused_results = []
    full_results = []
    if not args.skip_focused:
        focused_results = harness.run(focused_corpus, results_name="focused_results.jsonl", resume=args.resume)
        write_json(args.output_dir / "focused_checkpoint_summary.json", build_checkpoint_summary(focused_results, feature_audit=feature_audit))
        (args.output_dir / "focused_checkpoint_report.md").write_text(
            build_checkpoint_report(
                title="Stormhelm Focused Command Evaluation Checkpoint",
                results=focused_results,
                feature_audit=feature_audit,
            ),
            encoding="utf-8",
        )
    if not args.skip_full:
        full_results = harness.run(full_corpus, results_name="full_results.jsonl", resume=args.resume)
        write_json(args.output_dir / "full_checkpoint_summary.json", build_checkpoint_summary(full_results, feature_audit=feature_audit))
        (args.output_dir / "full_checkpoint_report.md").write_text(
            build_checkpoint_report(
                title="Stormhelm Command Evaluation Checkpoint",
                results=full_results,
                feature_audit=feature_audit,
            ),
            encoding="utf-8",
        )
    if args.skip_focused or args.skip_full:
        paths = {
            "feature_map": args.output_dir / "feature_map.json",
            "feature_audit": args.output_dir / "feature_map_audit.json",
            "corpus": args.output_dir / "corpus.jsonl",
        }
        if focused_results:
            paths["focused_results"] = args.output_dir / "focused_results.jsonl"
            paths["focused_checkpoint_summary"] = args.output_dir / "focused_checkpoint_summary.json"
            paths["focused_checkpoint_report"] = args.output_dir / "focused_checkpoint_report.md"
        if full_results:
            paths["full_results"] = args.output_dir / "full_results.jsonl"
            paths["full_checkpoint_summary"] = args.output_dir / "full_checkpoint_summary.json"
            paths["full_checkpoint_report"] = args.output_dir / "full_checkpoint_report.md"
    else:
        paths = write_artifacts(
            output_dir=args.output_dir,
            feature_map=feature_map,
            feature_audit=feature_audit,
            corpus=full_corpus,
            focused_results=focused_results,
            full_results=full_results,
        )
    for name, path in paths.items():
        print(f"{name}: {path}")


def _focused_subset(corpus, *, limit: int):
    if len(corpus) <= limit:
        return list(corpus)
    canonical = [case for case in corpus if "canonical" in case.tags]
    fuzzy = [case for case in corpus if {"typo", "ambiguous", "deictic", "follow_up"} & set(case.tags)]
    selected = []
    seen = set()
    for case in [*canonical, *fuzzy, *corpus]:
        if case.case_id in seen:
            continue
        selected.append(case)
        seen.add(case.case_id)
        if len(selected) >= limit:
            break
    return selected


if __name__ == "__main__":
    main()
