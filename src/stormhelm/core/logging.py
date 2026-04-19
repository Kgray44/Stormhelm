from __future__ import annotations

import logging

from stormhelm.app.logging import configure_application_logging
from stormhelm.config.models import AppConfig


def configure_logging(config: AppConfig) -> logging.Logger:
    return configure_application_logging(config, "core")
