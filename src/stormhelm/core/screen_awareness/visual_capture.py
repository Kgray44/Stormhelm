from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.screen_awareness.models import ScreenObservation
from stormhelm.core.screen_awareness.models import ScreenObservationScope
from stormhelm.core.screen_awareness.models import ScreenSensitivityLevel
from stormhelm.core.screen_awareness.models import ScreenSourceType


_SOURCE_PRIORITY: dict[ScreenSourceType, int] = {
    ScreenSourceType.SCREEN_CAPTURE: 10,
    ScreenSourceType.LOCAL_OCR: 20,
    ScreenSourceType.PROVIDER_VISION: 21,
    ScreenSourceType.SELECTION: 22,
    ScreenSourceType.ACCESSIBILITY: 30,
    ScreenSourceType.APP_ADAPTER: 40,
    ScreenSourceType.BROWSER_DOM: 41,
    ScreenSourceType.FOCUS_STATE: 50,
    ScreenSourceType.WORKSPACE_CONTEXT: 60,
    ScreenSourceType.CLIPBOARD: 80,
    ScreenSourceType.PLACEHOLDER: 90,
}

_SENSITIVE_MARKERS = {
    "account",
    "bank",
    "banking",
    "billing",
    "checkout",
    "credit card",
    "login",
    "password",
    "payment",
    "secret",
    "token",
    "vault",
}


@dataclass(slots=True)
class ScreenCaptureResult:
    captured: bool
    captured_at: str = ""
    scope: str = ScreenObservationScope.ACTIVE_WINDOW.value
    capture_reference: str | None = None
    text: str | None = None
    text_source: str | None = None
    confidence_score: float = 0.0
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    provider_vision: dict[str, Any] = field(default_factory=dict)


def source_labels_for_observation(observation: ScreenObservation | None) -> list[str]:
    if observation is None:
        return []
    ordered = sorted(
        observation.source_types_used,
        key=lambda source: (_SOURCE_PRIORITY.get(source, 100), source.value),
    )
    return [source.value for source in ordered]


def sensitive_window_level(focused_window: dict[str, Any]) -> ScreenSensitivityLevel:
    title = str(focused_window.get("window_title") or "").strip().lower()
    process_name = str(focused_window.get("process_name") or "").strip().lower()
    combined = f"{title} {process_name}"
    if any(marker in combined for marker in _SENSITIVE_MARKERS):
        if any(marker in combined for marker in {"bank", "banking", "password", "secret", "token", "vault"}):
            return ScreenSensitivityLevel.RESTRICTED
        return ScreenSensitivityLevel.SENSITIVE
    return ScreenSensitivityLevel.NORMAL


def _hidden_console_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    kwargs: dict[str, Any] = {}
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is not None:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0) or 0)
        startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0) or 0)
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _clean_text(value: object) -> str | None:
    cleaned = " ".join(str(value or "").split()).strip()
    return cleaned or None


def _ps_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _safe_int(payload: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(payload.get(key) or default)
    except (TypeError, ValueError):
        return default


def _pil_imagegrab_available() -> bool:
    try:
        from PIL import ImageGrab  # noqa: F401
    except Exception:
        return False
    return True


def _capture_with_pil(bounds: tuple[int, int, int, int], output_path: Path | None) -> None:
    from PIL import ImageGrab

    x, y, width, height = bounds
    bbox = (x, y, x + width, y + height)
    try:
        image = ImageGrab.grab(bbox=bbox, all_screens=True)
    except TypeError:
        image = ImageGrab.grab(bbox=bbox)
    try:
        if output_path is not None:
            image.save(output_path, "PNG")
    finally:
        close = getattr(image, "close", None)
        if callable(close):
            close()


def _bounds_for_capture(
    *,
    scope: str,
    focused_window: dict[str, Any],
    monitor_metadata: dict[str, Any],
) -> tuple[tuple[int, int, int, int], str] | None:
    if scope == ScreenObservationScope.MONITOR.value:
        width = _safe_int(monitor_metadata, "bounds_width")
        height = _safe_int(monitor_metadata, "bounds_height")
        if width > 0 and height > 0:
            return (
                (
                    _safe_int(monitor_metadata, "bounds_x"),
                    _safe_int(monitor_metadata, "bounds_y"),
                    width,
                    height,
                ),
                ScreenObservationScope.MONITOR.value,
            )
    width = _safe_int(focused_window, "width")
    height = _safe_int(focused_window, "height")
    if width > 0 and height > 0:
        return (
            (
                _safe_int(focused_window, "x"),
                _safe_int(focused_window, "y"),
                width,
                height,
            ),
            ScreenObservationScope.ACTIVE_WINDOW.value,
        )
    width = _safe_int(monitor_metadata, "bounds_width")
    height = _safe_int(monitor_metadata, "bounds_height")
    if width > 0 and height > 0:
        return (
            (
                _safe_int(monitor_metadata, "bounds_x"),
                _safe_int(monitor_metadata, "bounds_y"),
                width,
                height,
            ),
            ScreenObservationScope.MONITOR.value,
        )
    system_bounds = _system_virtual_screen_bounds()
    if system_bounds is not None:
        return system_bounds, ScreenObservationScope.FULL_SCREEN.value
    return None


def _system_virtual_screen_bounds() -> tuple[int, int, int, int] | None:
    if platform.system().strip().lower() != "windows":
        return None
    try:
        user32 = ctypes.windll.user32
        x = int(user32.GetSystemMetrics(76))
        y = int(user32.GetSystemMetrics(77))
        width = int(user32.GetSystemMetrics(78))
        height = int(user32.GetSystemMetrics(79))
        if width <= 0 or height <= 0:
            width = int(user32.GetSystemMetrics(0))
            height = int(user32.GetSystemMetrics(1))
            x = 0
            y = 0
        if width > 0 and height > 0:
            return (x, y, width, height)
    except Exception:
        return None
    return None


@dataclass(slots=True)
class WindowsScreenCaptureProvider:
    ocr_timeout_seconds: float = 8.0
    capture_timeout_seconds: float = 8.0

    def capability_status(self) -> dict[str, Any]:
        is_windows = platform.system().strip().lower() == "windows"
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        pil_available = _pil_imagegrab_available()
        return {
            "available": bool(is_windows and (pil_available or powershell)),
            "platform": platform.system(),
            "backend": "pil_imagegrab" if is_windows and pil_available else "windows_gdi" if is_windows and powershell else "unavailable",
            "pil_imagegrab_available": bool(pil_available),
            "powershell_available": bool(powershell),
            "local_ocr_available": bool(shutil.which("tesseract")),
            "provider_vision_available": False,
        }

    def capture(
        self,
        *,
        scope: str,
        focused_window: dict[str, Any],
        monitor_metadata: dict[str, Any],
        ocr_enabled: bool,
        provider_vision_enabled: bool,
        provider: Any | None = None,
        retain_image: bool = False,
    ) -> ScreenCaptureResult:
        captured_at = datetime.now(timezone.utc).isoformat()
        status = self.capability_status()
        if not status.get("available"):
            return ScreenCaptureResult(captured=False, captured_at=captured_at, scope=scope, reason="screen_capture_unavailable", metadata=status)

        bounds_result = _bounds_for_capture(scope=scope, focused_window=focused_window, monitor_metadata=monitor_metadata)
        if bounds_result is None:
            return ScreenCaptureResult(captured=False, captured_at=captured_at, scope=scope, reason="capture_bounds_unavailable", metadata=status)

        bounds, actual_scope = bounds_result
        x, y, width, height = bounds
        temp_path = Path(tempfile.gettempdir()) / f"stormhelm-screen-{uuid4().hex}.png"
        metadata: dict[str, Any] = {
            **status,
            "requested_scope": scope,
            "bounds": {"x": x, "y": y, "width": width, "height": height},
            "raw_screenshot_logged": False,
            "image_retained": bool(retain_image),
        }
        warnings: list[str] = []
        provider_vision = {"attempted": False, "used": False, "reason": "provider_vision_disabled"}

        try:
            image_file_needed = bool(
                retain_image
                or provider_vision_enabled
                or (ocr_enabled and bool(shutil.which("tesseract")))
            )
            temp_path_created = False
            if status.get("pil_imagegrab_available"):
                try:
                    _capture_with_pil(bounds, temp_path if image_file_needed else None)
                    temp_path_created = image_file_needed
                    metadata["backend"] = "pil_imagegrab"
                except Exception as exc:
                    metadata["pil_capture_error"] = str(exc)[:240]

            if not status.get("pil_imagegrab_available") or ("pil_capture_error" in metadata and not temp_path_created):
                script = f"""
                Add-Type -AssemblyName System.Drawing
                $path = {_ps_string(str(temp_path))}
                $bitmap = New-Object System.Drawing.Bitmap({width}, {height})
                $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
                try {{
                    $graphics.CopyFromScreen({x}, {y}, 0, 0, $bitmap.Size)
                    $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
                    [pscustomobject]@{{ captured = $true; path = $path }} | ConvertTo-Json -Compress
                }} finally {{
                    $graphics.Dispose()
                    $bitmap.Dispose()
                }}
                """
                powershell = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
                completed = subprocess.run(
                    [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                    capture_output=True,
                    text=True,
                    timeout=self.capture_timeout_seconds,
                    **_hidden_console_subprocess_kwargs(),
                )
                if completed.returncode != 0 or not temp_path.exists():
                    reason = "screen_capture_failed"
                    if completed.stderr.strip():
                        metadata["capture_error"] = completed.stderr.strip()[:240]
                    return ScreenCaptureResult(captured=False, captured_at=captured_at, scope=scope, reason=reason, metadata=metadata)
                metadata["backend"] = "windows_gdi"
                temp_path_created = True

            text: str | None = None
            text_source: str | None = None
            confidence_score = 0.0
            if ocr_enabled and temp_path_created:
                tesseract = shutil.which("tesseract")
                if tesseract:
                    ocr = subprocess.run(
                        [tesseract, str(temp_path), "stdout", "--psm", "6"],
                        capture_output=True,
                        text=True,
                        timeout=self.ocr_timeout_seconds,
                        **_hidden_console_subprocess_kwargs(),
                    )
                    if ocr.returncode == 0:
                        text = _clean_text(ocr.stdout)
                        text_source = "local_ocr" if text else None
                        confidence_score = 0.72 if text else 0.0
                    else:
                        warnings.append("Local OCR was available but did not return usable text.")
                        metadata["ocr_error"] = ocr.stderr.strip()[:240]
                else:
                    warnings.append("Local OCR is not available.")
            elif ocr_enabled:
                warnings.append("Local OCR is not available.")

            provider_vision = self._provider_vision(
                provider=provider,
                enabled=provider_vision_enabled,
                image_path=temp_path,
                scope=actual_scope,
                metadata=metadata,
            )
            if provider_vision.get("used") and provider_vision.get("text"):
                text = _clean_text(provider_vision.get("text"))
                text_source = "provider_vision"
                confidence_score = float(provider_vision.get("confidence_score") or 0.65)

            return ScreenCaptureResult(
                captured=True,
                captured_at=captured_at,
                scope=actual_scope,
                capture_reference=f"screen-capture:{uuid4().hex}",
                text=text,
                text_source=text_source,
                confidence_score=confidence_score,
                metadata=metadata,
                warnings=warnings,
                provider_vision=provider_vision,
            )
        except subprocess.TimeoutExpired:
            return ScreenCaptureResult(captured=False, captured_at=captured_at, scope=scope, reason="screen_capture_timeout", metadata=metadata)
        finally:
            if not retain_image:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _provider_vision(
        self,
        *,
        provider: Any | None,
        enabled: bool,
        image_path: Path,
        scope: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not enabled:
            return {"attempted": False, "used": False, "reason": "provider_vision_disabled"}
        if provider is None:
            return {"attempted": False, "used": False, "reason": "provider_unavailable"}
        analyzer = getattr(provider, "describe_screen_capture", None) or getattr(provider, "analyze_screen_capture", None)
        if not callable(analyzer):
            return {"attempted": False, "used": False, "reason": "provider_vision_not_supported"}
        try:
            result = analyzer(image_path=str(image_path), scope=scope, metadata=dict(metadata))
        except Exception as exc:
            return {"attempted": True, "used": False, "reason": "provider_vision_failed", "error": str(exc)[:160]}
        if not isinstance(result, dict):
            return {"attempted": True, "used": False, "reason": "provider_vision_empty"}
        text = _clean_text(result.get("text") or result.get("summary") or result.get("description"))
        return {
            "attempted": True,
            "used": bool(text),
            "reason": "provider_vision_used" if text else "provider_vision_empty",
            "text": text,
            "confidence_score": float(result.get("confidence_score") or result.get("confidence") or 0.65),
        }


@dataclass(slots=True)
class ScreenVisualGrounder:
    config: ScreenAwarenessConfig
    provider: Any | None = None
    capture_provider: Any | None = None

    def __post_init__(self) -> None:
        if self.capture_provider is None:
            self.capture_provider = WindowsScreenCaptureProvider()

    def status_snapshot(self) -> dict[str, Any]:
        capability = self._capability_status()
        capture_enabled = bool(self.config.capability_flags().get("screen_capture_enabled", False))
        return {
            "screen_capture": {
                **capability,
                "enabled": capture_enabled,
                "scope": self.config.screen_capture_scope,
                "ocr_enabled": bool(self.config.screen_capture_ocr_enabled),
                "provider_vision_enabled": bool(self.config.screen_capture_provider_vision_enabled),
                "raw_image_retention_enabled": bool(self.config.screen_capture_store_raw_images),
            }
        }

    def augment(
        self,
        *,
        observation: ScreenObservation,
        intent: Any,
        operator_text: str,
    ) -> ScreenObservation:
        del intent, operator_text
        screen_capture = self._empty_capture_status()
        if not self.config.capability_flags().get("screen_capture_enabled", False):
            screen_capture["reason"] = "screen_capture_disabled"
            observation.visual_metadata["screen_capture"] = screen_capture
            observation.warnings.append("Real screen capture is disabled by policy.")
            return observation

        if observation.sensitivity in {ScreenSensitivityLevel.SENSITIVE, ScreenSensitivityLevel.RESTRICTED}:
            screen_capture["reason"] = "sensitive_window_blocked"
            screen_capture["blocked"] = True
            screen_capture["sensitivity"] = observation.sensitivity.value
            observation.visual_metadata["screen_capture"] = screen_capture
            observation.warnings.append("Screen capture was blocked because the focused surface may contain sensitive content.")
            return observation

        capability = self._capability_status()
        if not capability.get("available"):
            screen_capture.update(capability)
            screen_capture["reason"] = "screen_capture_unavailable"
            observation.visual_metadata["screen_capture"] = screen_capture
            observation.warnings.append("Real screen capture is unavailable on this machine.")
            return observation

        focused_window = dict(observation.window_metadata.get("focused_window") or {})
        monitor_metadata = dict(observation.monitor_metadata or {})
        result = self.capture_provider.capture(
            scope=str(self.config.screen_capture_scope or ScreenObservationScope.ACTIVE_WINDOW.value),
            focused_window=focused_window,
            monitor_metadata=monitor_metadata,
            ocr_enabled=bool(self.config.screen_capture_ocr_enabled),
            provider_vision_enabled=bool(self.config.screen_capture_provider_vision_enabled),
            provider=self.provider,
            retain_image=bool(self.config.screen_capture_store_raw_images),
        )
        screen_capture.update(
            {
                **capability,
                "attempted": True,
                "captured": bool(result.captured),
                "captured_at": result.captured_at,
                "scope": result.scope,
                "capture_reference": result.capture_reference,
                "reason": result.reason,
                "ocr": {
                    "enabled": bool(self.config.screen_capture_ocr_enabled),
                    "used": result.text_source == "local_ocr" and bool(result.text),
                    "available": bool(capability.get("local_ocr_available")),
                    "confidence_score": result.confidence_score if result.text_source == "local_ocr" else 0.0,
                },
                "provider_vision": result.provider_vision or {
                    "attempted": False,
                    "used": False,
                    "reason": "provider_vision_disabled",
                },
                "raw_screenshot_logged": bool(result.metadata.get("raw_screenshot_logged", False)),
                "image_retained": bool(result.metadata.get("image_retained", False)),
            }
        )
        if result.reason:
            screen_capture["reason"] = result.reason
        observation.visual_metadata["screen_capture"] = screen_capture
        observation.capture_reference = result.capture_reference
        if result.captured:
            self._append_source(observation, ScreenSourceType.SCREEN_CAPTURE)
            observation.quality_notes.append(
                f"Screenshot captured from {result.scope} at {result.captured_at}; raw image retention is {'enabled' if self.config.screen_capture_store_raw_images else 'disabled'}."
            )
        else:
            observation.warnings.append(result.reason or "Screen capture did not return an image.")
        if result.text:
            observation.visual_text = result.text
            observation.visual_metadata["visual_text_source"] = result.text_source
            observation.visual_metadata["visual_confidence_score"] = result.confidence_score
            if result.text_source == "local_ocr":
                self._append_source(observation, ScreenSourceType.LOCAL_OCR)
                observation.quality_notes.append("Local OCR provided visible screen text from the screenshot.")
            elif result.text_source == "provider_vision":
                self._append_source(observation, ScreenSourceType.PROVIDER_VISION)
                observation.quality_notes.append("Provider vision provided visible screen text from the screenshot.")
        for warning in result.warnings:
            observation.warnings.append(warning)
        return observation

    def _capability_status(self) -> dict[str, Any]:
        reader = getattr(self.capture_provider, "capability_status", None)
        if callable(reader):
            status = reader()
            if isinstance(status, dict):
                return dict(status)
        return {"available": False, "backend": "unavailable", "local_ocr_available": False, "provider_vision_available": False}

    def _empty_capture_status(self) -> dict[str, Any]:
        capture_enabled = bool(self.config.capability_flags().get("screen_capture_enabled", False))
        return {
            "enabled": capture_enabled,
            "attempted": False,
            "captured": False,
            "scope": str(self.config.screen_capture_scope or ScreenObservationScope.ACTIVE_WINDOW.value),
            "capture_reference": None,
            "raw_screenshot_logged": False,
            "image_retained": False,
            "reason": None,
            "ocr": {
                "enabled": bool(self.config.screen_capture_ocr_enabled),
                "used": False,
                "available": False,
                "confidence_score": 0.0,
            },
            "provider_vision": {
                "attempted": False,
                "used": False,
                "reason": "provider_vision_disabled",
            },
        }

    def _append_source(self, observation: ScreenObservation, source: ScreenSourceType) -> None:
        if source not in observation.source_types_used:
            observation.source_types_used.append(source)
