from __future__ import annotations

import argparse
import json
from pathlib import Path

from stormhelm.config.loader import load_config
from stormhelm.core.system.hardware_telemetry import collect_helper_snapshot


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stormhelm hardware telemetry helper")
    parser.add_argument("--tier", default="active", choices=["idle", "active", "burst"])
    parser.add_argument("--project-root", default="", help="Optional explicit project root for source-mode launches.")
    parser.add_argument("--config-path", default="", help="Optional explicit config override path.")
    parser.add_argument("--output-path", default="", help="Optional path to write the JSON payload instead of stdout.")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    project_root = Path(args.project_root).resolve() if args.project_root else None
    config_path = Path(args.config_path).resolve() if args.config_path else None
    config = load_config(project_root=project_root, config_path=config_path)
    payload = collect_helper_snapshot(config, sampling_tier=args.tier)
    payload_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if args.output_path:
        output_path = Path(args.output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload_text, encoding="utf-8")
        return
    print(payload_text)


if __name__ == "__main__":
    main()
