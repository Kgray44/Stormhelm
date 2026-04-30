from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from stormhelm.core.latency_gates import (
    build_latency_gate_report,
    load_jsonl_rows,
    mock_provider_rows,
    mock_voice_rows,
    write_latency_gate_report,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stormhelm L10 latency gate reporting on existing or mock profile rows.")
    parser.add_argument("--profile", default="focused_hot_path_profile")
    parser.add_argument("--results-jsonl", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path(".artifacts") / "latency-profiles" / "latest")
    parser.add_argument("--mock-provider-samples", type=int, default=0)
    parser.add_argument("--mock-voice-samples", type=int, default=0)
    parser.add_argument("--live-provider-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    rows = []
    if args.results_jsonl is not None:
        rows.extend(load_jsonl_rows(args.results_jsonl))
    if args.profile == "provider_mock" and args.mock_provider_samples <= 0:
        args.mock_provider_samples = 25
    if args.profile == "voice_mock" and args.mock_voice_samples <= 0:
        args.mock_voice_samples = 25
    if args.mock_provider_samples:
        rows.extend(mock_provider_rows(args.mock_provider_samples))
    if args.mock_voice_samples:
        rows.extend(mock_voice_rows(args.mock_voice_samples))
    report = build_latency_gate_report(
        rows,
        profile=args.profile,
        live_provider_run=bool(args.live_provider_run),
        run_mode="mock" if args.mock_provider_samples or args.mock_voice_samples else "headless",
    )
    paths = write_latency_gate_report(args.output_dir, report)
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
