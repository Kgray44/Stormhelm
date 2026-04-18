from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from stormhelm.config.models import AppConfig


def configure_logging(config: AppConfig) -> logging.Logger:
    logger = logging.getLogger("stormhelm")
    logger.setLevel(getattr(logging, config.logging.level.upper(), logging.INFO))

    if getattr(logger, "_stormhelm_configured", False):
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        config.log_file_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    logger._stormhelm_configured = True  # type: ignore[attr-defined]
    return logger

