from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from stormhelm.config.models import AppConfig


def configure_application_logging(config: AppConfig, process_name: str) -> logging.Logger:
    logger_name = f"stormhelm.{process_name}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, config.logging.level.upper(), logging.INFO))

    desired_log_path = _log_path_for_process(config, process_name)
    existing_path = getattr(logger, "_stormhelm_log_path", None)
    if existing_path == str(desired_log_path):
        return logger

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    desired_log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        desired_log_path,
        maxBytes=config.logging.max_file_bytes,
        backupCount=config.logging.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    logger._stormhelm_log_path = str(desired_log_path)  # type: ignore[attr-defined]
    return logger


def install_exception_logging(logger: logging.Logger, process_name: str) -> None:
    def _handle_exception(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: object) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.exception("Unhandled exception in Stormhelm %s.", process_name, exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = _handle_exception


def _log_path_for_process(config: AppConfig, process_name: str) -> Path:
    if process_name == "ui":
        return config.ui_log_file_path
    return config.core_log_file_path
