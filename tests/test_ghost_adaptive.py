from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from stormhelm.ui.ghost_adaptive import (
    GhostAdaptiveManager,
    GhostCandidateEvaluation,
    GhostPlacementController,
    GhostReadabilityScorer,
    GhostRegionMetrics,
)


def _ensure_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _CountingScreen:
    def __init__(self) -> None:
        image = QtGui.QImage(1600, 900, QtGui.QImage.Format.Format_RGBA8888)
        image.fill(QtGui.QColor("#6baec7"))
        self._pixmap = QtGui.QPixmap.fromImage(image)
        self.calls = 0

    def grabWindow(self, window: int, x: int, y: int, width: int, height: int) -> QtGui.QPixmap:
        del window
        self.calls += 1
        source = QtCore.QRect(x, y, max(1, width), max(1, height))
        return self._pixmap.copy(source)


class _FakeWindow:
    def __init__(self, screen: _CountingScreen) -> None:
        self._screen = screen

    def screen(self) -> _CountingScreen:
        return self._screen

    def geometry(self) -> QtCore.QRect:
        return QtCore.QRect(0, 0, 1280, 720)


def test_ghost_readability_scorer_strengthens_ghost_on_bright_busy_background() -> None:
    scorer = GhostReadabilityScorer()

    bright_busy = GhostRegionMetrics(
        brightness=0.88,
        contrast=0.18,
        motion=0.24,
        edge_density=0.41,
        variance=0.33,
    )
    dark_calm = GhostRegionMetrics(
        brightness=0.16,
        contrast=0.14,
        motion=0.05,
        edge_density=0.12,
        variance=0.11,
    )

    bright_style = scorer.style_for_metrics(bright_busy)
    dark_style = scorer.style_for_metrics(dark_calm)

    assert bright_style["tone"] > 0.0
    assert dark_style["tone"] < bright_style["tone"]
    assert bright_style["surfaceOpacity"] > dark_style["surfaceOpacity"]
    assert bright_style["edgeOpacity"] >= dark_style["edgeOpacity"]
    assert bright_style["textContrast"] > dark_style["textContrast"]
    assert bright_style["backdropOpacity"] > dark_style["backdropOpacity"]
    assert bright_style["surfaceOpacity"] >= 0.82
    assert bright_style["textContrast"] >= 0.18
    assert bright_style["anchorStrokeBoost"] >= 0.22
    assert bright_style["anchorFillBoost"] >= 0.16
    assert bright_style["anchorBackdropOpacity"] >= 0.12


def test_ghost_readability_scorer_uses_core_region_to_strengthen_anchor_on_light_surfaces() -> None:
    scorer = GhostReadabilityScorer()

    balanced_shell = GhostRegionMetrics(
        brightness=0.46,
        contrast=0.2,
        motion=0.08,
        edge_density=0.16,
        variance=0.14,
    )
    bright_core = GhostRegionMetrics(
        brightness=0.95,
        contrast=0.1,
        motion=0.05,
        edge_density=0.12,
        variance=0.1,
    )
    dark_core = GhostRegionMetrics(
        brightness=0.12,
        contrast=0.16,
        motion=0.05,
        edge_density=0.12,
        variance=0.1,
    )

    bright_core_style = scorer.style_for_regions(balanced_shell, core_metrics=bright_core)
    dark_core_style = scorer.style_for_regions(balanced_shell, core_metrics=dark_core)

    assert bright_core_style["surfaceOpacity"] == dark_core_style["surfaceOpacity"]
    assert bright_core_style["anchorStrokeBoost"] > dark_core_style["anchorStrokeBoost"]
    assert bright_core_style["anchorGlowBoost"] > dark_core_style["anchorGlowBoost"]
    assert bright_core_style["anchorFillBoost"] > dark_core_style["anchorFillBoost"]
    assert bright_core_style["anchorBackdropOpacity"] > dark_core_style["anchorBackdropOpacity"]
    assert bright_core_style["anchorGlowBoost"] >= 0.28
    assert bright_core_style["anchorStrokeBoost"] >= 0.38
    assert bright_core_style["anchorFillBoost"] >= 0.18


def test_ghost_placement_controller_requires_bad_current_score_and_clear_upgrade() -> None:
    controller = GhostPlacementController(
        move_threshold=0.45,
        improvement_margin=0.14,
        min_dwell_ms=4_000,
        cooldown_ms=9_000,
    )

    initial = controller.consider(
        [
            GhostCandidateEvaluation(
                key="center",
                offset_x=0.0,
                offset_y=0.0,
                score=0.66,
                metrics=GhostRegionMetrics(brightness=0.48, contrast=0.22, motion=0.08, edge_density=0.16, variance=0.14),
            ),
            GhostCandidateEvaluation(
                key="left",
                offset_x=-120.0,
                offset_y=0.0,
                score=0.73,
                metrics=GhostRegionMetrics(brightness=0.44, contrast=0.24, motion=0.06, edge_density=0.14, variance=0.12),
            ),
        ],
        now_ms=0,
    )

    assert initial["anchorKey"] == "center"
    assert initial["state"] == "holding"

    before_dwell = controller.consider(
        [
            GhostCandidateEvaluation(
                key="center",
                offset_x=0.0,
                offset_y=0.0,
                score=0.31,
                metrics=GhostRegionMetrics(brightness=0.91, contrast=0.12, motion=0.46, edge_density=0.52, variance=0.38),
            ),
            GhostCandidateEvaluation(
                key="left",
                offset_x=-120.0,
                offset_y=-24.0,
                score=0.63,
                metrics=GhostRegionMetrics(brightness=0.42, contrast=0.20, motion=0.11, edge_density=0.18, variance=0.15),
            ),
        ],
        now_ms=2_500,
    )

    assert before_dwell["anchorKey"] == "center"
    assert before_dwell["state"] == "evaluating"

    moved = controller.consider(
        [
            GhostCandidateEvaluation(
                key="center",
                offset_x=0.0,
                offset_y=0.0,
                score=0.28,
                metrics=GhostRegionMetrics(brightness=0.94, contrast=0.10, motion=0.51, edge_density=0.58, variance=0.41),
            ),
            GhostCandidateEvaluation(
                key="left",
                offset_x=-120.0,
                offset_y=-24.0,
                score=0.66,
                metrics=GhostRegionMetrics(brightness=0.40, contrast=0.20, motion=0.09, edge_density=0.16, variance=0.14),
            ),
        ],
        now_ms=5_200,
    )

    assert moved["anchorKey"] == "left"
    assert moved["state"] == "repositioning"
    assert moved["offsetX"] == -120.0
    assert moved["offsetY"] == -24.0

    in_cooldown = controller.consider(
        [
            GhostCandidateEvaluation(
                key="left",
                offset_x=-120.0,
                offset_y=-24.0,
                score=0.37,
                metrics=GhostRegionMetrics(brightness=0.79, contrast=0.16, motion=0.27, edge_density=0.33, variance=0.24),
            ),
            GhostCandidateEvaluation(
                key="right",
                offset_x=136.0,
                offset_y=-18.0,
                score=0.72,
                metrics=GhostRegionMetrics(brightness=0.39, contrast=0.18, motion=0.10, edge_density=0.14, variance=0.11),
            ),
        ],
        now_ms=8_000,
    )

    assert in_cooldown["anchorKey"] == "left"
    assert in_cooldown["state"] == "cooldown"


def test_ghost_adaptive_manager_smooths_anchor_reposition_updates() -> None:
    manager = GhostAdaptiveManager()

    manager._placement = {
        "anchorKey": "center",
        "state": "holding",
        "offsetX": 0.0,
        "offsetY": 0.0,
        "currentScore": 0.48,
        "bestScore": 0.48,
    }

    smoothed = manager._smooth_placement(
        {
            "anchorKey": "right",
            "state": "repositioning",
            "offsetX": 96.0,
            "offsetY": -18.0,
            "currentScore": 0.34,
            "bestScore": 0.63,
        }
    )

    assert smoothed["anchorKey"] == "right"
    assert smoothed["state"] == "repositioning"
    assert 0.0 < smoothed["offsetX"] < 96.0
    assert -18.0 < smoothed["offsetY"] < 0.0


def test_ghost_adaptive_manager_captures_background_once_per_refresh() -> None:
    _ensure_app()
    screen = _CountingScreen()
    manager = GhostAdaptiveManager()
    manager.attach_window(_FakeWindow(screen))
    manager._enabled = True

    manager.refresh()

    assert screen.calls == 1
