from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from stormhelm.core.orchestrator.command_eval import CommandEvalCase
from stormhelm.core.orchestrator.command_eval import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval import ProcessIsolatedCommandUsabilityHarness
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_report
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.orchestrator.command_eval.report import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Prove command evaluator hard process timeout behavior.")
    default_output = Path(".artifacts") / "command-usability-eval" / f"hard-timeout-proof-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--timeout-seconds", type=float, default=1.0)
    parser.add_argument("--block-seconds", type=float, default=5.0)
    args = parser.parse_args()

    case = CommandEvalCase(
        case_id="synthetic_blocking_core_handler_00",
        message="synthetic hard timeout proof",
        expected=ExpectedBehavior(
            route_family="hard_timeout",
            subsystem="harness",
            tools=(),
            latency_ms_max=int(max(1000, args.timeout_seconds * 1500)),
        ),
        tags=("harness", "hard_timeout", "synthetic"),
        notes="Monkeypatches the child Core handler to sleep synchronously longer than the parent hard cap.",
    )
    harness = ProcessIsolatedCommandUsabilityHarness(
        output_dir=args.output_dir,
        per_test_timeout_seconds=args.timeout_seconds,
        history_strategy="isolated_session",
        synthetic_block_seconds=args.block_seconds,
    )
    results = harness.run([case], results_name="hard_timeout_proof_results.jsonl")
    summary = build_checkpoint_summary(results)
    row = results[0].to_dict()
    summary.update(
        {
            "hard_timeout_proven": row.get("status") == "hard_timeout" and bool(row.get("process_killed")),
            "timeout_row": {
                "test_id": row.get("test_id"),
                "status": row.get("status"),
                "process_killed": row.get("process_killed"),
                "timeout_seconds": row.get("timeout_seconds"),
                "elapsed_ms": row.get("elapsed_ms"),
                "checkpoint_path": row.get("checkpoint_path"),
            },
        }
    )
    write_json(args.output_dir / "hard_timeout_proof_summary.json", summary)
    (args.output_dir / "hard_timeout_proof_report.md").write_text(
        build_checkpoint_report(
            title="Stormhelm Process-Isolated Hard Timeout Proof",
            results=results,
        ),
        encoding="utf-8",
    )
    print(f"results: {args.output_dir / 'hard_timeout_proof_results.jsonl'}")
    print(f"summary: {args.output_dir / 'hard_timeout_proof_summary.json'}")
    print(f"report: {args.output_dir / 'hard_timeout_proof_report.md'}")
    print(f"hard_timeout_proven: {summary['hard_timeout_proven']}")


if __name__ == "__main__":
    main()
