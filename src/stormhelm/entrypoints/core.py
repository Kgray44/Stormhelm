from __future__ import annotations

from stormhelm.config.loader import load_config
from stormhelm.core.service import run_core_service


def main() -> None:
    config = load_config()
    run_core_service(config)


if __name__ == "__main__":
    main()
