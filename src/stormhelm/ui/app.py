from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets

from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.ui.client import CoreApiClient
from stormhelm.ui.controllers.main_controller import MainController
from stormhelm.ui.main_window import MainWindow
from stormhelm.ui.tray import create_tray_icon


def run_ui(config: AppConfig | None = None) -> int:
    app_config = config or load_config()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setApplicationName(app_config.app_name)
    app.setOrganizationName("Stormhelm")

    stylesheet_path = Path(app_config.project_root) / "assets" / "styles" / "stormhelm.qss"
    if stylesheet_path.exists():
        app.setStyleSheet(stylesheet_path.read_text(encoding="utf-8"))

    window = MainWindow()
    tray_icon = create_tray_icon(window, app_config)
    window.set_tray_icon(tray_icon)

    client = CoreApiClient(app_config.api_base_url, parent=window)
    controller = MainController(config=app_config, window=window, client=client)
    controller.start()

    window.show()
    return app.exec()

