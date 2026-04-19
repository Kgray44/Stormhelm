from __future__ import annotations

from stormhelm.app.logging import configure_application_logging, install_exception_logging
from stormhelm.config.loader import load_config
from stormhelm.core.service import run_core_service


def main() -> None:
    config = load_config()
    logger = configure_application_logging(config, "core")
    install_exception_logging(logger, "core")
    run_core_service(config)


if __name__ == "__main__":
    main()
