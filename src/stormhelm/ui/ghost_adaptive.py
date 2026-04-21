from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Iterable

from PySide6 import QtCore, QtGui


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _blend(current: float, target: float, factor: float) -> float:
    return current + (target - current) * factor


def default_ghost_style() -> dict[str, float | str]:
    return {
        "tone": 0.0,
        "surfaceOpacity": 0.72,
        "edgeOpacity": 0.22,
        "lineOpacity": 0.06,
        "textContrast": 0.08,
        "secondaryTextContrast": 0.05,
        "glowBoost": 0.06,
        "anchorGlowBoost": 0.08,
        "anchorStrokeBoost": 0.12,
        "anchorFillBoost": 0.04,
        "anchorBackdropOpacity": 0.05,
        "shadowOpacity": 0.1,
        "backdropOpacity": 0.04,
        "backgroundState": "balanced",
    }


def default_ghost_placement() -> dict[str, float | str]:
    return {
        "anchorKey": "center",
        "state": "holding",
        "offsetX": 0.0,
        "offsetY": 0.0,
        "currentScore": 0.0,
        "bestScore": 0.0,
    }


def default_ghost_diagnostics() -> dict[str, float | str | bool]:
    return {
        "supported": False,
        "backgroundState": "unknown",
        "brightness": 0.0,
        "contrast": 0.0,
        "motion": 0.0,
        "edgeDensity": 0.0,
        "variance": 0.0,
        "readabilityRisk": 0.0,
    }


@dataclass(frozen=True)
class GhostRegionMetrics:
    brightness: float
    contrast: float
    motion: float
    edge_density: float
    variance: float
    supported: bool = True

    def as_dict(self) -> dict[str, float | bool]:
        return {
            "supported": self.supported,
            "brightness": _clamp(self.brightness),
            "contrast": _clamp(self.contrast),
            "motion": _clamp(self.motion),
            "edgeDensity": _clamp(self.edge_density),
            "variance": _clamp(self.variance),
        }


@dataclass(frozen=True)
class GhostCandidateEvaluation:
    key: str
    offset_x: float
    offset_y: float
    score: float
    metrics: GhostRegionMetrics
    core_metrics: GhostRegionMetrics | None = None


class GhostBackgroundSampler:
    def __init__(self, sample_width: int = 30, sample_height: int = 18) -> None:
        self.sample_width = max(8, int(sample_width))
        self.sample_height = max(6, int(sample_height))
        self._previous_frames: dict[str, list[float]] = {}

    def capture(self, screen: QtGui.QScreen | None, rect: QtCore.QRectF) -> QtGui.QImage | None:
        if screen is None or rect.width() < 4 or rect.height() < 4:
            return None

        pixmap = screen.grabWindow(
            0,
            int(rect.x()),
            int(rect.y()),
            max(1, int(rect.width())),
            max(1, int(rect.height())),
        )
        if pixmap.isNull():
            return None
        return pixmap.toImage().convertToFormat(QtGui.QImage.Format.Format_RGBA8888)

    def sample(self, screen: QtGui.QScreen | None, rect: QtCore.QRectF, *, key: str) -> GhostRegionMetrics:
        image = self.capture(screen, rect)
        if image is None:
            return GhostRegionMetrics(0.5, 0.0, 0.0, 0.0, 0.0, supported=False)
        return self._metrics_from_image(image, key=key)

    def sample_from_capture(
        self,
        image: QtGui.QImage | None,
        *,
        capture_rect: QtCore.QRectF,
        rect: QtCore.QRectF,
        key: str,
    ) -> GhostRegionMetrics:
        if image is None or rect.width() < 4 or rect.height() < 4:
            return GhostRegionMetrics(0.5, 0.0, 0.0, 0.0, 0.0, supported=False)

        source_rect = QtCore.QRect(
            int(round(rect.x() - capture_rect.x())),
            int(round(rect.y() - capture_rect.y())),
            max(1, int(round(rect.width()))),
            max(1, int(round(rect.height()))),
        ).intersected(QtCore.QRect(0, 0, image.width(), image.height()))
        if source_rect.width() < 4 or source_rect.height() < 4:
            return GhostRegionMetrics(0.5, 0.0, 0.0, 0.0, 0.0, supported=False)

        return self._metrics_from_image(image.copy(source_rect), key=key)

    def _metrics_from_image(self, image: QtGui.QImage, *, key: str) -> GhostRegionMetrics:
        scaled = image.scaled(
            self.sample_width,
            self.sample_height,
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.FastTransformation,
        )
        luminance_values = self._luminance_grid(scaled)
        if not luminance_values:
            return GhostRegionMetrics(0.5, 0.0, 0.0, 0.0, 0.0, supported=False)

        brightness = sum(luminance_values) / len(luminance_values)
        variance = sum((value - brightness) ** 2 for value in luminance_values) / len(luminance_values)
        contrast = _clamp(math.sqrt(variance) * 2.6)
        edge_density = self._edge_density(luminance_values, scaled.width(), scaled.height())

        previous = self._previous_frames.get(key)
        motion = 0.0
        if previous is not None and len(previous) == len(luminance_values):
            motion = _clamp(sum(abs(a - b) for a, b in zip(luminance_values, previous, strict=False)) / len(luminance_values) * 2.4)
        self._previous_frames[key] = luminance_values

        return GhostRegionMetrics(
            brightness=_clamp(brightness),
            contrast=contrast,
            motion=motion,
            edge_density=edge_density,
            variance=_clamp(variance * 4.0),
            supported=True,
        )

    def _luminance_grid(self, image: QtGui.QImage) -> list[float]:
        values: list[float] = []
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                values.append(
                    _clamp(
                        0.2126 * color.redF()
                        + 0.7152 * color.greenF()
                        + 0.0722 * color.blueF()
                    )
                )
        return values

    def _edge_density(self, values: list[float], width: int, height: int) -> float:
        edges = 0.0
        samples = 0
        for y in range(height):
            row_index = y * width
            for x in range(width):
                current = values[row_index + x]
                if x + 1 < width:
                    edges += abs(current - values[row_index + x + 1])
                    samples += 1
                if y + 1 < height:
                    edges += abs(current - values[row_index + width + x])
                    samples += 1
        if samples <= 0:
            return 0.0
        return _clamp(edges / samples * 3.2)


class GhostReadabilityScorer:
    def background_state_for_metrics(self, metrics: GhostRegionMetrics) -> str:
        busy = self._busyness(metrics)
        if metrics.motion > 0.34 or busy > 0.56:
            return "high-motion"
        if metrics.brightness >= 0.72:
            return "bright"
        if metrics.brightness <= 0.28:
            return "dark"
        return "balanced"

    def readability_risk(self, metrics: GhostRegionMetrics) -> float:
        busy = self._busyness(metrics)
        washout_risk = _clamp(metrics.brightness * 0.82 + busy * 0.18)
        low_signal_risk = _clamp((1.0 - metrics.contrast) * 0.55 + busy * 0.2)
        return _clamp(
            washout_risk * 0.46
            + metrics.motion * 0.24
            + busy * 0.2
            + low_signal_risk * 0.1
        )

    def score_metrics(self, metrics: GhostRegionMetrics, *, distance_ratio: float = 0.0) -> float:
        if not metrics.supported:
            return 0.5
        busy = self._busyness(metrics)
        readability = 1.0 - self.readability_risk(metrics)
        brightness_fit = 1.0 - _clamp(abs(metrics.brightness - 0.46) * 1.55)
        calmness = 1.0 - _clamp(metrics.motion * 0.9 + busy * 0.45)
        score = readability * 0.46 + brightness_fit * 0.22 + calmness * 0.22 + metrics.contrast * 0.1
        score -= _clamp(distance_ratio) * 0.08
        return _clamp(score)

    def style_for_metrics(self, metrics: GhostRegionMetrics) -> dict[str, float | str]:
        return self.style_for_regions(metrics, core_metrics=metrics)

    def style_for_regions(
        self,
        shell_metrics: GhostRegionMetrics,
        *,
        core_metrics: GhostRegionMetrics | None = None,
    ) -> dict[str, float | str]:
        core = core_metrics or shell_metrics
        busy = self._busyness(shell_metrics)
        core_busy = self._busyness(core)
        tone = _clamp((shell_metrics.brightness - 0.52) * 1.9 + shell_metrics.motion * 0.2 + busy * 0.18, -0.24, 0.56)
        surface_opacity = _clamp(0.68 + max(0.0, tone) * 0.44 - max(0.0, -tone) * 0.1 + shell_metrics.motion * 0.08 + busy * 0.06, 0.58, 0.96)
        edge_opacity = _clamp(0.2 + max(0.0, tone) * 0.3 + busy * 0.08, 0.14, 0.5)
        line_opacity = _clamp(0.05 + max(0.0, tone) * 0.1 + busy * 0.04, 0.04, 0.2)
        text_contrast = _clamp(0.06 + max(0.0, tone) * 0.32 + shell_metrics.motion * 0.06 + busy * 0.05, 0.03, 0.42)
        secondary_contrast = _clamp(text_contrast * 0.72, 0.02, 0.28)
        glow_boost = _clamp(0.04 + max(0.0, tone) * 0.18 + shell_metrics.motion * 0.04, 0.02, 0.32)
        shadow_opacity = _clamp(0.08 + busy * 0.16 + shell_metrics.motion * 0.12 + max(0.0, tone) * 0.1, 0.06, 0.38)
        backdrop_opacity = _clamp(0.03 + busy * 0.2 + shell_metrics.motion * 0.12 + max(0.0, tone) * 0.18, 0.02, 0.38)
        core_washout = _clamp((core.brightness - 0.56) * 1.95)
        core_low_contrast = _clamp((0.24 - core.contrast) * 3.2)
        anchor_emphasis = _clamp(core_washout * 0.72 + core_low_contrast * 0.28)
        anchor_glow_boost = _clamp(0.06 + anchor_emphasis * 0.34 + core_busy * 0.05 + core.motion * 0.04, 0.04, 0.5)
        anchor_stroke_boost = _clamp(0.08 + anchor_emphasis * 0.44 + core_busy * 0.08 + core.motion * 0.05, 0.04, 0.58)
        anchor_fill_boost = _clamp(0.03 + anchor_emphasis * 0.24 + core_busy * 0.04 + (1.0 - core.contrast) * 0.02, 0.02, 0.32)
        anchor_backdrop_opacity = _clamp(0.04 + anchor_emphasis * 0.24 + core_busy * 0.06 + (1.0 - core.contrast) * 0.04, 0.03, 0.28)
        return {
            "tone": tone,
            "surfaceOpacity": surface_opacity,
            "edgeOpacity": edge_opacity,
            "lineOpacity": line_opacity,
            "textContrast": text_contrast,
            "secondaryTextContrast": secondary_contrast,
            "glowBoost": glow_boost,
            "anchorGlowBoost": anchor_glow_boost,
            "anchorStrokeBoost": anchor_stroke_boost,
            "anchorFillBoost": anchor_fill_boost,
            "anchorBackdropOpacity": anchor_backdrop_opacity,
            "shadowOpacity": shadow_opacity,
            "backdropOpacity": backdrop_opacity,
            "backgroundState": self.background_state_for_metrics(shell_metrics),
        }

    def _busyness(self, metrics: GhostRegionMetrics) -> float:
        return _clamp(metrics.edge_density * 0.55 + metrics.variance * 0.45)


class GhostPlacementController:
    def __init__(
        self,
        *,
        move_threshold: float = 0.44,
        improvement_margin: float = 0.14,
        min_dwell_ms: int = 6_000,
        cooldown_ms: int = 10_000,
    ) -> None:
        self.move_threshold = float(move_threshold)
        self.improvement_margin = float(improvement_margin)
        self.min_dwell_ms = int(min_dwell_ms)
        self.cooldown_ms = int(cooldown_ms)
        self._current_key = "center"
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._anchor_since_ms: int | None = None
        self._last_move_ms: int | None = None

    def consider(self, candidates: Iterable[GhostCandidateEvaluation], *, now_ms: int | None = None) -> dict[str, float | str]:
        candidate_list = list(candidates)
        if not candidate_list:
            return default_ghost_placement()

        now = int(time.monotonic() * 1000) if now_ms is None else int(now_ms)
        candidate_map = {candidate.key: candidate for candidate in candidate_list}

        if self._anchor_since_ms is None:
            self._anchor_since_ms = now

        current = candidate_map.get(self._current_key) or candidate_map.get("center") or candidate_list[0]
        if current.key != self._current_key:
            self._current_key = current.key
            self._offset_x = current.offset_x
            self._offset_y = current.offset_y
            self._anchor_since_ms = now

        best = max(candidate_list, key=lambda candidate: candidate.score)
        anchor_since = self._anchor_since_ms if self._anchor_since_ms is not None else now
        time_in_anchor = now - anchor_since
        time_since_move = now - self._last_move_ms if self._last_move_ms is not None else self.cooldown_ms + 1

        state = "holding"
        should_move = (
            current.score < self.move_threshold
            and best.key != current.key
            and best.score >= current.score + self.improvement_margin
            and best.score >= self.move_threshold + 0.08
        )

        if should_move and time_since_move < self.cooldown_ms:
            state = "cooldown"
        elif should_move and time_in_anchor < self.min_dwell_ms:
            state = "evaluating"
        elif should_move:
            self._current_key = best.key
            self._offset_x = best.offset_x
            self._offset_y = best.offset_y
            self._anchor_since_ms = now
            self._last_move_ms = now
            current = best
            state = "repositioning"
        elif current.score < self.move_threshold and best.key == current.key:
            state = "no-better-space-found"

        return {
            "anchorKey": self._current_key,
            "state": state,
            "offsetX": self._offset_x,
            "offsetY": self._offset_y,
            "currentScore": round(_clamp(current.score), 3),
            "bestScore": round(_clamp(best.score), 3),
        }


class GhostAdaptiveManager(QtCore.QObject):
    updated = QtCore.Signal(object, object, object)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._window: QtGui.QWindow | None = None
        self._enabled = False
        self._sampler = GhostBackgroundSampler()
        self._scorer = GhostReadabilityScorer()
        self._placement_controller = GhostPlacementController()
        self._style = default_ghost_style()
        self._placement = default_ghost_placement()
        self._diagnostics = default_ghost_diagnostics()

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1_250)
        self._timer.timeout.connect(self.refresh)

    def attach_window(self, window: QtGui.QWindow | None) -> None:
        self._window = window

    def set_enabled(self, enabled: bool) -> None:
        normalized = bool(enabled)
        if normalized == self._enabled:
            if normalized and not self._timer.isActive():
                self._timer.start()
            return
        self._enabled = normalized
        if self._enabled:
            self._timer.start()
            self.refresh()
        else:
            self._timer.stop()

    @QtCore.Slot()
    def refresh(self) -> None:
        if not self._enabled or self._window is None:
            return
        screen = self._window.screen() or QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return

        window_rect = QtCore.QRectF(self._window.geometry())
        if window_rect.width() <= 0 or window_rect.height() <= 0:
            return

        window_capture = self._sampler.capture(screen, window_rect)
        candidates = self._evaluate_candidates(window_rect, window_capture)
        if not candidates:
            return

        placement = self._placement_controller.consider(candidates)
        active = next((candidate for candidate in candidates if candidate.key == placement["anchorKey"]), candidates[0])
        target_style = self._scorer.style_for_regions(active.metrics, core_metrics=active.core_metrics)
        self._style = self._smooth_style(target_style)
        self._placement = self._smooth_placement(placement)
        self._diagnostics = self._build_diagnostics(active.metrics)
        self.updated.emit(dict(self._style), dict(self._placement), dict(self._diagnostics))

    def _evaluate_candidates(
        self,
        window_rect: QtCore.QRectF,
        window_capture: QtGui.QImage | None,
    ) -> list[GhostCandidateEvaluation]:
        candidates: list[GhostCandidateEvaluation] = []
        width = window_rect.width()
        height = window_rect.height()
        base_offsets = [
            ("center", 0.0, 0.0),
            ("left", -width * 0.11, -height * 0.02),
            ("right", width * 0.11, -height * 0.02),
            ("upper-left", -width * 0.08, -height * 0.08),
            ("upper-right", width * 0.08, -height * 0.08),
            ("lower-left", -width * 0.07, height * 0.05),
            ("lower-right", width * 0.07, height * 0.05),
        ]

        max_distance = math.hypot(width * 0.11, height * 0.08) or 1.0
        for key, offset_x, offset_y in base_offsets:
            core_rect, strip_rect, info_rect = self._ghost_sample_rects(window_rect, offset_x, offset_y)
            core_metrics = self._sampler.sample_from_capture(
                window_capture,
                capture_rect=window_rect,
                rect=core_rect,
                key=f"{key}:core",
            )
            metrics = self._combine_metrics(
                [
                    core_metrics,
                    self._sampler.sample_from_capture(
                        window_capture,
                        capture_rect=window_rect,
                        rect=strip_rect,
                        key=f"{key}:strip",
                    ),
                    self._sampler.sample_from_capture(
                        window_capture,
                        capture_rect=window_rect,
                        rect=info_rect,
                        key=f"{key}:info",
                    ),
                ],
                weights=(0.42, 0.36, 0.22),
            )
            distance_ratio = math.hypot(offset_x, offset_y) / max_distance
            score = self._scorer.score_metrics(metrics, distance_ratio=distance_ratio)
            candidates.append(
                GhostCandidateEvaluation(
                    key=key,
                    offset_x=round(offset_x, 2),
                    offset_y=round(offset_y, 2),
                    score=score,
                    metrics=metrics,
                    core_metrics=core_metrics,
                )
            )
        return candidates

    def _ghost_sample_rects(
        self,
        window_rect: QtCore.QRectF,
        offset_x: float,
        offset_y: float,
    ) -> tuple[QtCore.QRectF, QtCore.QRectF, QtCore.QRectF]:
        width = window_rect.width()
        height = window_rect.height()
        core_size = min(width * 0.18, 238.0)
        core_left = window_rect.x() + width * 0.5 - core_size * 0.5 + offset_x
        core_top = window_rect.y() + height * 0.42 - core_size * 0.5 + offset_y
        strip_width = min(width * 0.62, 640.0)
        strip_left = window_rect.x() + width * 0.5 - strip_width * 0.5 + offset_x
        strip_top = core_top + core_size + 14.0
        info_width = min(width * 0.7, 760.0)
        info_left = window_rect.x() + width * 0.5 - info_width * 0.5 + offset_x
        info_top = strip_top + 78.0
        info_height = 178.0

        core_rect = QtCore.QRectF(core_left - 18.0, core_top - 18.0, core_size + 36.0, core_size + 36.0)
        strip_rect = QtCore.QRectF(strip_left - 10.0, strip_top - 8.0, strip_width + 20.0, 84.0)
        info_rect = QtCore.QRectF(info_left - 16.0, info_top - 10.0, info_width + 32.0, info_height)
        return tuple(self._clamp_rect(rect, window_rect) for rect in (core_rect, strip_rect, info_rect))

    def _clamp_rect(self, rect: QtCore.QRectF, bounds: QtCore.QRectF) -> QtCore.QRectF:
        width = min(rect.width(), bounds.width())
        height = min(rect.height(), bounds.height())
        x = min(max(rect.x(), bounds.x()), bounds.x() + bounds.width() - width)
        y = min(max(rect.y(), bounds.y()), bounds.y() + bounds.height() - height)
        return QtCore.QRectF(x, y, width, height)

    def _combine_metrics(self, metrics_list: Iterable[GhostRegionMetrics], *, weights: Iterable[float]) -> GhostRegionMetrics:
        metric_items = list(metrics_list)
        weight_items = list(weights)
        if not metric_items or len(metric_items) != len(weight_items):
            return GhostRegionMetrics(0.5, 0.0, 0.0, 0.0, 0.0, supported=False)

        total_weight = sum(weight_items) or 1.0
        supported = any(metrics.supported for metrics in metric_items)
        brightness = sum(metrics.brightness * weight for metrics, weight in zip(metric_items, weight_items, strict=False)) / total_weight
        contrast = sum(metrics.contrast * weight for metrics, weight in zip(metric_items, weight_items, strict=False)) / total_weight
        motion = sum(metrics.motion * weight for metrics, weight in zip(metric_items, weight_items, strict=False)) / total_weight
        edge_density = sum(metrics.edge_density * weight for metrics, weight in zip(metric_items, weight_items, strict=False)) / total_weight
        variance = sum(metrics.variance * weight for metrics, weight in zip(metric_items, weight_items, strict=False)) / total_weight
        return GhostRegionMetrics(
            brightness=_clamp(brightness),
            contrast=_clamp(contrast),
            motion=_clamp(motion),
            edge_density=_clamp(edge_density),
            variance=_clamp(variance),
            supported=supported,
        )

    def _smooth_style(self, target_style: dict[str, float | str]) -> dict[str, float | str]:
        smoothed: dict[str, float | str] = {}
        for key, value in target_style.items():
            current = self._style.get(key)
            if isinstance(value, (int, float)) and isinstance(current, (int, float)):
                factor = 0.18 if key in {"tone", "surfaceOpacity", "textContrast", "secondaryTextContrast"} else 0.24
                smoothed[key] = round(_blend(float(current), float(value), factor), 4)
            else:
                smoothed[key] = value
        return smoothed

    def _smooth_placement(self, target_placement: dict[str, float | str]) -> dict[str, float | str]:
        smoothed: dict[str, float | str] = dict(target_placement)
        current = dict(self._placement)
        for key in ("offsetX", "offsetY", "currentScore", "bestScore"):
            target_value = target_placement.get(key)
            current_value = current.get(key)
            if isinstance(target_value, (int, float)) and isinstance(current_value, (int, float)):
                factor = 0.22 if key in {"offsetX", "offsetY"} else 0.3
                smoothed[key] = round(_blend(float(current_value), float(target_value), factor), 4)
        if target_placement.get("anchorKey"):
            smoothed["anchorKey"] = target_placement["anchorKey"]
        if target_placement.get("state"):
            smoothed["state"] = target_placement["state"]
        return smoothed

    def _build_diagnostics(self, metrics: GhostRegionMetrics) -> dict[str, float | str | bool]:
        diagnostics = metrics.as_dict()
        diagnostics["backgroundState"] = self._scorer.background_state_for_metrics(metrics) if metrics.supported else "unknown"
        diagnostics["readabilityRisk"] = round(self._scorer.readability_risk(metrics), 4) if metrics.supported else 0.0
        return diagnostics
