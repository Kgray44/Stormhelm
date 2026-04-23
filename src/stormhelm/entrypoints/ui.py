from __future__ import annotations

import argparse

from stormhelm.config.loader import load_config
from stormhelm.ui.app import run_ui


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stormhelm UI shell")
    parser.add_argument("--start-hidden", action="store_true", help="Start the shell hidden in its dormant tray posture.")
    parser.add_argument(
        "--startup-mode",
        choices=("ghost", "deck"),
        default="",
        help="Preferred presentation mode when the shell starts visibly.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    config = load_config()
    startup_mode = args.startup_mode or None
    raise SystemExit(run_ui(config, start_hidden=args.start_hidden, startup_mode=startup_mode))


if __name__ == "__main__":
    main()
