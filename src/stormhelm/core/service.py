from __future__ import annotations

import uvicorn

from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.core.api.app import create_app


def run_core_service(config: AppConfig | None = None) -> None:
    app_config = config or load_config()
    app = create_app(app_config)
    uvicorn.run(
        app,
        host=app_config.network.host,
        port=app_config.network.port,
        log_level=app_config.logging.level.lower(),
    )

