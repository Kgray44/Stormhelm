from __future__ import annotations

import sys

from stormhelm.config.loader import load_config
from stormhelm.ui.app import run_ui


def main() -> None:
    config = load_config()
    raise SystemExit(run_ui(config))


if __name__ == "__main__":
    main()
