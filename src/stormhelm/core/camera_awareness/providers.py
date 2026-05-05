from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Protocol

from stormhelm.config.models import CameraAwarenessConfig, OpenAIConfig
from stormhelm.core.camera_awareness.models import (
    CAMERA_SOURCE_PROVENANCE_LOCAL,
    CAMERA_SOURCE_PROVENANCE_MOCK,
    CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
    CameraAnalysisMode,
    CameraAwarenessResultState,
    CameraCaptureRequest,
    CameraCaptureResult,
    CameraCaptureStatus,
    CameraConfidenceLevel,
    CameraDeviceStatus,
    CameraFrameArtifact,
    CameraPermissionState,
    CameraStorageMode,
    CameraVisionAnswer,
    CameraVisionQuestion,
    camera_id,
    utc_now,
)
from stormhelm.core.camera_awareness.prompts import build_camera_vision_prompt
from stormhelm.core.providers.base import AssistantProvider, ProviderTurnResult


_REDACTED_IMAGE_PAYLOAD = "[redacted-camera-image-payload]"
_VISUAL_EVIDENCE_ONLY_NOTE = "Visual analysis only; not command authority."
_RAW_PROVIDER_TEXT_FIELDS = (
    "image_url",
    "image_bytes",
    "image_base64",
    "raw_image",
    "provider_request_body",
    "provider_request",
)


@dataclass(slots=True)
class LocalStillCaptureBackendResult:
    success: bool
    error_code: str | None = None
    error_message: str | None = None
    device_id: str | None = None
    width: int = 0
    height: int = 0
    image_format: str = "jpg"
    file_path: Path | None = None


class LocalStillCaptureBackend(Protocol):
    backend_kind: str

    def is_available(self) -> bool:
        ...

    def get_devices(self, *, timeout_seconds: float) -> list[CameraDeviceStatus]:
        ...

    def capture_still(
        self,
        *,
        device_id: str,
        output_path: Path,
        timeout_seconds: float,
        requested_resolution: str,
    ) -> LocalStillCaptureBackendResult:
        ...


class CameraCaptureProvider(Protocol):
    hardware_access_attempted: bool
    capture_attempted: bool
    provider_kind: str

    def get_devices(self) -> list[CameraDeviceStatus]:
        ...

    def capture_still(
        self,
        request: CameraCaptureRequest,
    ) -> tuple[CameraCaptureResult, CameraFrameArtifact | None]:
        ...

    def release_device(self, device_id: str | None = None) -> None:
        ...


class VisionAnalysisProvider(Protocol):
    network_access_attempted: bool

    provider_kind: str

    def analyze_image(
        self,
        question: CameraVisionQuestion,
        artifact: CameraFrameArtifact | None,
    ) -> CameraVisionAnswer:
        ...


@dataclass(slots=True)
class CameraVisionProviderAvailability:
    provider_kind: str
    available: bool
    reason: str | None = None
    model: str = ""
    cloud_provider: bool = False


@dataclass(slots=True)
class CameraVisionImagePreparation:
    image_artifact_id: str
    artifact_format: str
    artifact_size_bytes: int
    mime_type: str
    detail: str
    source_provenance: str
    storage_mode: str
    raw_image_included: bool = False
    cloud_upload_performed: bool = False

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "image_artifact_id": self.image_artifact_id,
            "artifact_format": self.artifact_format,
            "artifact_size_bytes": self.artifact_size_bytes,
            "mime_type": self.mime_type,
            "detail": self.detail,
            "source_provenance": self.source_provenance,
            "storage_mode": self.storage_mode,
            "raw_image_included": False,
            "cloud_upload_performed": False,
        }


class MockCameraCaptureProvider:
    provider_kind = "mock"

    def __init__(self, config: CameraAwarenessConfig) -> None:
        self.config = config
        self.hardware_access_attempted = False
        self.capture_attempted = False
        self.active = False
        self.release_count = 0

    def get_devices(self) -> list[CameraDeviceStatus]:
        return [
            CameraDeviceStatus(
                device_id="mock_camera_0",
                display_name="Stormhelm Mock Camera",
                provider="mock",
                available=True,
                permission_state=CameraPermissionState.GRANTED,
                active=False,
                mock_device=True,
                source_provenance=CAMERA_SOURCE_PROVENANCE_MOCK,
            )
        ]

    def capture_still(
        self,
        request: CameraCaptureRequest,
    ) -> tuple[CameraCaptureResult, CameraFrameArtifact | None]:
        self.capture_attempted = True
        created_at = utc_now()
        width, height = _parse_resolution(
            request.requested_resolution or self.config.capture.requested_resolution
        )
        artifact = CameraFrameArtifact(
            capture_result_id="",
            storage_mode=CameraStorageMode(self.config.default_storage_mode),
            created_at=created_at,
            expires_at=created_at
            + timedelta(seconds=int(self.config.auto_discard_after_seconds)),
            width=width,
            height=height,
            image_format="mock",
            hash_hint=f"mock:{self.config.dev.mock_image_fixture}:{width}x{height}",
            mock_artifact=True,
            fixture_name=self.config.dev.mock_image_fixture,
            source_provenance=CAMERA_SOURCE_PROVENANCE_MOCK,
        )
        result = CameraCaptureResult(
            request_id=request.capture_request_id,
            status=CameraCaptureStatus.CAPTURED,
            image_artifact_id=artifact.image_artifact_id,
            captured_at=created_at,
            device_id=request.device_id or self.config.capture.default_device_id or "mock_camera_0",
            width=width,
            height=height,
            image_format="mock",
            quality_warnings=[],
            raw_image_persisted=False,
            cloud_upload_allowed=False,
            cloud_upload_performed=False,
            mock_capture=True,
            real_camera_used=False,
            source_provenance=CAMERA_SOURCE_PROVENANCE_MOCK,
        )
        artifact.capture_result_id = result.capture_result_id
        return result, artifact

    def release_device(self, device_id: str | None = None) -> None:
        del device_id
        self.active = False


class UnavailableCameraCaptureProvider:
    provider_kind = "unavailable"

    def __init__(
        self,
        *,
        reason: str = "camera_capture_provider_unavailable",
        configured_provider: str = "unavailable",
    ) -> None:
        self.reason = reason
        self.configured_provider = configured_provider
        self.hardware_access_attempted = False
        self.capture_attempted = False
        self.active = False
        self.release_count = 0

    def get_devices(self) -> list[CameraDeviceStatus]:
        return [
            CameraDeviceStatus(
                device_id="unavailable",
                display_name=f"Camera capture unavailable: {self.reason}",
                provider=self.configured_provider or "unavailable",
                available=False,
                permission_state=CameraPermissionState.UNAVAILABLE,
                mock_device=False,
                source_provenance=CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
            )
        ]

    def capture_still(
        self,
        request: CameraCaptureRequest,
    ) -> tuple[CameraCaptureResult, CameraFrameArtifact | None]:
        self.capture_attempted = True
        return (
            CameraCaptureResult(
                request_id=request.capture_request_id,
                status=CameraCaptureStatus.BLOCKED,
                error_code=self.reason,
                error_message=f"Camera capture provider unavailable: {self.reason}",
                raw_image_persisted=False,
                cloud_upload_performed=False,
                mock_capture=False,
                real_camera_used=False,
                source_provenance=CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
            ),
            None,
        )

    def release_device(self, device_id: str | None = None) -> None:
        del device_id
        self.active = False


class LocalCameraCaptureProvider:
    provider_kind = "local"

    def __init__(
        self,
        config: CameraAwarenessConfig,
        *,
        backend: LocalStillCaptureBackend | None = None,
    ) -> None:
        self.config = config
        self.backend = backend or default_local_still_backend()
        self.backend_kind = getattr(self.backend, "backend_kind", "unknown_local_backend")
        self.backend_available = bool(self.backend.is_available())
        self.backend_unavailable_reason = (
            None if self.backend_available else "local_capture_backend_unavailable"
        )
        self.hardware_access_attempted = False
        self.capture_attempted = False
        self.active = False
        self.release_count = 0
        self.last_device_id: str | None = None
        self.last_error_code: str | None = None

    def get_devices(self) -> list[CameraDeviceStatus]:
        if not self.backend_available:
            return [
                CameraDeviceStatus(
                    device_id=self.config.capture.default_device_id or "local-default",
                    display_name="Local camera backend unavailable",
                    provider=self.backend_kind,
                    available=False,
                    permission_state=CameraPermissionState.UNAVAILABLE,
                    active=False,
                    mock_device=False,
                    source_provenance=CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
                    error_code="local_capture_backend_unavailable",
                    error_message="Local camera backend is unavailable.",
                )
            ]
        devices = self.backend.get_devices(timeout_seconds=float(self.config.capture.timeout_seconds))
        if not devices:
            return [
                CameraDeviceStatus(
                    device_id="local-default",
                    display_name="No local camera device detected",
                    provider=self.backend_kind,
                    available=False,
                    permission_state=CameraPermissionState.UNAVAILABLE,
                    active=False,
                    mock_device=False,
                    source_provenance=CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
                    error_code="camera_no_device",
                    error_message="No local camera device was reported by the backend.",
                )
            ]
        return devices

    def get_default_device(self) -> CameraDeviceStatus | None:
        configured = str(self.config.capture.default_device_id or "").strip()
        devices = self.get_devices()
        available = [device for device in devices if device.available]
        if configured:
            for device in available:
                if device.device_id == configured:
                    return device
        return available[0] if available else None

    def get_status(self, device_id: str | None = None) -> CameraDeviceStatus:
        if device_id:
            for device in self.get_devices():
                if device.device_id == device_id:
                    return device
        device = self.get_default_device()
        if device is not None:
            return device
        return self.get_devices()[0]

    def capture_still(
        self,
        request: CameraCaptureRequest,
    ) -> tuple[CameraCaptureResult, CameraFrameArtifact | None]:
        self.capture_attempted = True
        created_at = utc_now()
        selected_device = request.device_id or self.config.capture.default_device_id
        if not self.backend_available:
            self.last_error_code = "local_capture_backend_unavailable"
            try:
                return self._blocked_result(
                    request,
                    "local_capture_backend_unavailable",
                    "Local camera backend is unavailable.",
                    created_at=created_at,
                    device_id=selected_device,
                )
            finally:
                self.release_device(selected_device)
        if not selected_device:
            device = self.get_default_device()
            if device is None or not device.available:
                self.last_error_code = "camera_no_device"
                return self._blocked_result(
                    request,
                    "camera_no_device",
                    "No available local camera device was found.",
                    created_at=created_at,
                )
            selected_device = device.device_id
        self.last_device_id = selected_device

        self.active = True
        self.hardware_access_attempted = True
        image_artifact_id = camera_id("camera-frame")
        output_path = _local_capture_temp_path(image_artifact_id)
        try:
            backend_result = self.backend.capture_still(
                device_id=selected_device,
                output_path=output_path,
                timeout_seconds=float(self.config.capture.timeout_seconds),
                requested_resolution=request.requested_resolution
                or self.config.capture.requested_resolution,
            )
            if not backend_result.success or backend_result.file_path is None:
                code = backend_result.error_code or "camera_capture_failed"
                self.last_error_code = code
                return self._blocked_result(
                    request,
                    code,
                    backend_result.error_message or "Local camera capture failed.",
                    created_at=created_at,
                    device_id=selected_device,
                )

            width = backend_result.width or _parse_resolution(
                request.requested_resolution or self.config.capture.requested_resolution
            )[0]
            height = backend_result.height or _parse_resolution(
                request.requested_resolution or self.config.capture.requested_resolution
            )[1]
            artifact = CameraFrameArtifact(
                capture_result_id="",
                storage_mode=CameraStorageMode(self.config.default_storage_mode),
                created_at=created_at,
                expires_at=created_at
                + timedelta(seconds=int(self.config.auto_discard_after_seconds)),
                image_artifact_id=image_artifact_id,
                file_path=str(backend_result.file_path),
                width=width,
                height=height,
                image_format=backend_result.image_format or "jpg",
                hash_hint=_local_hash_hint(backend_result.file_path),
                mock_artifact=False,
                fixture_name="local_capture",
                source_provenance=CAMERA_SOURCE_PROVENANCE_LOCAL,
            )
            result = CameraCaptureResult(
                request_id=request.capture_request_id,
                status=CameraCaptureStatus.CAPTURED,
                image_artifact_id=artifact.image_artifact_id,
                captured_at=created_at,
                device_id=backend_result.device_id or selected_device,
                width=artifact.width,
                height=artifact.height,
                image_format=artifact.image_format,
                quality_warnings=[],
                raw_image_persisted=False,
                cloud_upload_allowed=False,
                cloud_upload_performed=False,
                mock_capture=False,
                real_camera_used=True,
                source_provenance=CAMERA_SOURCE_PROVENANCE_LOCAL,
            )
            artifact.capture_result_id = result.capture_result_id
            self.last_error_code = None
            return result, artifact
        finally:
            self.release_device(selected_device)

    def release_device(self, device_id: str | None = None) -> None:
        self.last_device_id = device_id or self.last_device_id
        self.active = False
        self.release_count += 1

    def _blocked_result(
        self,
        request: CameraCaptureRequest,
        error_code: str,
        error_message: str,
        *,
        created_at,
        device_id: str | None = None,
    ) -> tuple[CameraCaptureResult, None]:
        status = _capture_status_for_error(error_code)
        return (
            CameraCaptureResult(
                request_id=request.capture_request_id,
                status=status,
                captured_at=created_at,
                device_id=device_id,
                error_code=error_code,
                error_message=error_message,
                raw_image_persisted=False,
                cloud_upload_allowed=False,
                cloud_upload_performed=False,
                mock_capture=False,
                real_camera_used=False,
                source_provenance=CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
            ),
            None,
        )


class FfmpegDirectShowStillBackend:
    backend_kind = "ffmpeg_dshow"

    def __init__(self, *, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("ffmpeg")

    def is_available(self) -> bool:
        return bool(sys.platform.startswith("win") and self.executable)

    def get_devices(self, *, timeout_seconds: float) -> list[CameraDeviceStatus]:
        if not sys.platform.startswith("win"):
            return [_unavailable_device("unsupported_platform", self.backend_kind)]
        if not self.executable:
            return [_unavailable_device("local_capture_backend_unavailable", self.backend_kind)]
        try:
            result = subprocess.run(
                [
                    self.executable,
                    "-hide_banner",
                    "-list_devices",
                    "true",
                    "-f",
                    "dshow",
                    "-i",
                    "dummy",
                ],
                capture_output=True,
                text=True,
                timeout=max(1.0, float(timeout_seconds)),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return [_unavailable_device("camera_device_probe_timeout", self.backend_kind)]
        except OSError as error:
            return [
                _unavailable_device(
                    "local_capture_backend_unavailable",
                    self.backend_kind,
                    message=str(error),
                )
            ]
        devices = _parse_ffmpeg_dshow_devices(result.stderr or result.stdout or "")
        if not devices:
            return [_unavailable_device("camera_no_device", self.backend_kind)]
        return [
            CameraDeviceStatus(
                device_id=device,
                display_name=device,
                provider=self.backend_kind,
                available=True,
                permission_state=CameraPermissionState.UNKNOWN,
                active=False,
                mock_device=False,
                source_provenance=CAMERA_SOURCE_PROVENANCE_LOCAL,
            )
            for device in devices
        ]

    def capture_still(
        self,
        *,
        device_id: str,
        output_path: Path,
        timeout_seconds: float,
        requested_resolution: str,
    ) -> LocalStillCaptureBackendResult:
        if not sys.platform.startswith("win"):
            return LocalStillCaptureBackendResult(
                success=False,
                error_code="unsupported_platform",
                error_message="FFmpeg DirectShow capture is only available on Windows.",
                device_id=device_id,
            )
        if not self.executable:
            return LocalStillCaptureBackendResult(
                success=False,
                error_code="local_capture_backend_unavailable",
                error_message="ffmpeg executable was not found on PATH.",
                device_id=device_id,
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "dshow",
            "-video_size",
            requested_resolution,
            "-i",
            f"video={device_id}",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(1.0, float(timeout_seconds)),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return LocalStillCaptureBackendResult(
                success=False,
                error_code="camera_capture_timeout",
                error_message="Local camera still capture timed out.",
                device_id=device_id,
            )
        except OSError as error:
            return LocalStillCaptureBackendResult(
                success=False,
                error_code="camera_capture_failed",
                error_message=str(error),
                device_id=device_id,
            )
        if result.returncode != 0 or not output_path.exists():
            code = _ffmpeg_error_code(result.stderr or result.stdout or "")
            return LocalStillCaptureBackendResult(
                success=False,
                error_code=code,
                error_message=(result.stderr or result.stdout or "Local camera capture failed.").strip(),
                device_id=device_id,
            )
        width, height = _parse_resolution(requested_resolution)
        return LocalStillCaptureBackendResult(
            success=True,
            device_id=device_id,
            width=width,
            height=height,
            image_format="jpg",
            file_path=output_path,
        )


class WindowsMediaCaptureStillBackend:
    backend_kind = "windows_media_capture"

    def __init__(self, *, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("powershell") or shutil.which("pwsh")

    def is_available(self) -> bool:
        return bool(sys.platform.startswith("win") and self.executable)

    def get_devices(self, *, timeout_seconds: float) -> list[CameraDeviceStatus]:
        if not sys.platform.startswith("win"):
            return [_unavailable_device("unsupported_platform", self.backend_kind)]
        if not self.executable:
            return [_unavailable_device("local_capture_backend_unavailable", self.backend_kind)]
        payload = _run_powershell_json(
            self.executable,
            _WINRT_LIST_DEVICES_SCRIPT,
            timeout_seconds=timeout_seconds,
        )
        if str(payload.get("status") or "").lower() != "ok":
            return [
                _unavailable_device(
                    _winrt_error_code(payload),
                    self.backend_kind,
                    message=str(payload.get("error_message") or "Windows camera probe failed."),
                )
            ]
        devices = payload.get("devices") if isinstance(payload.get("devices"), list) else []
        if not devices:
            return [_unavailable_device("camera_no_device", self.backend_kind)]
        results: list[CameraDeviceStatus] = []
        for index, device in enumerate(devices):
            if not isinstance(device, dict):
                continue
            name = str(device.get("name") or f"Camera {index}").strip()
            device_id = str(device.get("id") or str(index)).strip() or str(index)
            results.append(
                CameraDeviceStatus(
                    device_id=device_id,
                    display_name=name,
                    provider=self.backend_kind,
                    available=bool(device.get("is_enabled", True)),
                    permission_state=CameraPermissionState.UNKNOWN,
                    active=False,
                    mock_device=False,
                    source_provenance=CAMERA_SOURCE_PROVENANCE_LOCAL,
                )
            )
        return results or [_unavailable_device("camera_no_device", self.backend_kind)]

    def capture_still(
        self,
        *,
        device_id: str,
        output_path: Path,
        timeout_seconds: float,
        requested_resolution: str,
    ) -> LocalStillCaptureBackendResult:
        if not sys.platform.startswith("win"):
            return LocalStillCaptureBackendResult(
                success=False,
                error_code="unsupported_platform",
                error_message="Windows MediaCapture is only available on Windows.",
                device_id=device_id,
            )
        if not self.executable:
            return LocalStillCaptureBackendResult(
                success=False,
                error_code="local_capture_backend_unavailable",
                error_message="PowerShell executable was not found.",
                device_id=device_id,
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        env = {
            "STORMHELM_CAMERA_OUTPUT_PATH": str(output_path),
            "STORMHELM_CAMERA_DEVICE_ID": str(device_id or ""),
        }
        payload = _run_powershell_json(
            self.executable,
            _WINRT_CAPTURE_SCRIPT,
            timeout_seconds=timeout_seconds,
            extra_env=env,
        )
        if str(payload.get("status") or "").lower() != "ok" or not output_path.exists():
            code = _winrt_error_code(payload)
            return LocalStillCaptureBackendResult(
                success=False,
                error_code=code,
                error_message=str(
                    payload.get("error_message")
                    or payload.get("message")
                    or "Windows camera capture failed."
                ),
                device_id=str(payload.get("device_id") or device_id),
            )
        width, height = _image_dimensions(output_path, fallback=requested_resolution)
        return LocalStillCaptureBackendResult(
            success=True,
            device_id=str(payload.get("device_id") or device_id),
            width=width,
            height=height,
            image_format="jpg",
            file_path=output_path,
        )


def default_local_still_backend() -> LocalStillCaptureBackend:
    if sys.platform.startswith("win"):
        winrt = WindowsMediaCaptureStillBackend()
        if winrt.is_available():
            return winrt
    return FfmpegDirectShowStillBackend()


class MockVisionAnalysisProvider:
    provider_kind = "mock"

    def __init__(self, config: CameraAwarenessConfig) -> None:
        self.config = config
        self.network_access_attempted = False

    def analyze_image(
        self,
        question: CameraVisionQuestion,
        artifact: CameraFrameArtifact | None,
    ) -> CameraVisionAnswer:
        if artifact is not None and artifact.source_provenance == CAMERA_SOURCE_PROVENANCE_LOCAL:
            return CameraVisionAnswer(
                vision_question_id=question.vision_question_id,
                image_artifact_id=question.image_artifact_id,
                answer_text=(
                    "Mock camera analysis accepted a fresh local still artifact. "
                    "This is a deterministic mock answer; no cloud vision or C2 "
                    "provider validation was used."
                ),
                concise_answer="Mock analysis of a fresh local still.",
                confidence=CameraConfidenceLevel.LOW,
                result_state=CameraAwarenessResultState.CAMERA_ANSWER_READY,
                provider="mock",
                model=self.config.vision.model,
                analysis_mode=question.analysis_mode,
                mock_answer=True,
                provider_kind="mock",
                cloud_analysis_performed=False,
                raw_image_included=False,
                evidence_summary="Deterministic mock local-still handoff.",
                uncertainty_reasons=["No real vision provider was used."],
                safety_notes=["Mock analysis only; not command authority."],
                helper_hints=_mock_helper_hints_for_fixture(
                    artifact.fixture_name,
                    str(question.normalized_question or question.user_question).lower(),
                ),
                provenance={
                    "source": CAMERA_SOURCE_PROVENANCE_LOCAL,
                    "artifact_id": question.image_artifact_id,
                    "artifact_format": artifact.image_format,
                    "provider": "mock",
                    "model": self.config.vision.model,
                    "mock_analysis": True,
                    "cloud_upload_performed": False,
                    "real_camera_used": True,
                },
                cloud_upload_performed=False,
            )
        fixture = (artifact.fixture_name if artifact is not None else self.config.dev.mock_image_fixture).lower()
        normalized_question = str(question.normalized_question or question.user_question).lower()
        concise, answer = _mock_answer_for_fixture(fixture, normalized_question)
        helper_hints = _mock_helper_hints_for_fixture(fixture, normalized_question)
        return CameraVisionAnswer(
            vision_question_id=question.vision_question_id,
            image_artifact_id=question.image_artifact_id,
            answer_text=answer,
            concise_answer=concise,
            confidence=CameraConfidenceLevel.MEDIUM,
            result_state=CameraAwarenessResultState.CAMERA_ANSWER_READY,
                provider="mock",
                model=self.config.vision.model,
                analysis_mode=question.analysis_mode,
                mock_answer=True,
                provider_kind="mock",
                cloud_analysis_performed=False,
                raw_image_included=False,
                evidence_summary="Deterministic mock fixture analysis.",
                uncertainty_reasons=["No real image analysis was performed."],
                safety_notes=["Mock analysis only; not command authority."],
                helper_hints=helper_hints,
                provenance={
                "source": CAMERA_SOURCE_PROVENANCE_MOCK,
                "artifact_id": question.image_artifact_id,
                "fixture_name": fixture,
                "provider": "mock",
                "model": self.config.vision.model,
                "mock_analysis": True,
                "cloud_upload_performed": False,
                "real_camera_used": False,
            },
            cloud_upload_performed=False,
        )


class OpenAIVisionAnalysisProvider:
    provider_kind = "openai"

    def __init__(
        self,
        config: CameraAwarenessConfig,
        *,
        openai_config: OpenAIConfig | None = None,
        responses_provider: AssistantProvider | None = None,
    ) -> None:
        self.config = config
        self.openai_config = openai_config
        self.responses_provider = responses_provider
        self.network_access_attempted = False
        self.last_availability = self.get_availability()
        self.last_request_metadata: dict[str, Any] = {}
        self.last_preparation: CameraVisionImagePreparation | None = None

    def get_availability(self) -> CameraVisionProviderAvailability:
        if self.responses_provider is not None:
            return CameraVisionProviderAvailability(
                provider_kind=self.provider_kind,
                available=True,
                model=self.config.vision.model,
                cloud_provider=True,
            )
        if self.openai_config is None or not self.openai_config.enabled or not self.openai_config.api_key:
            return CameraVisionProviderAvailability(
                provider_kind=self.provider_kind,
                available=False,
                reason="api_key_missing",
                model=self.config.vision.model,
                cloud_provider=True,
            )
        return CameraVisionProviderAvailability(
            provider_kind=self.provider_kind,
            available=True,
            model=self.config.vision.model or self.openai_config.model,
            cloud_provider=True,
        )

    def get_supported_detail_levels(self) -> tuple[str, ...]:
        return ("auto", "low", "high")

    def analyze_image(
        self,
        question: CameraVisionQuestion,
        artifact: CameraFrameArtifact | None,
    ) -> CameraVisionAnswer:
        availability = self.get_availability()
        self.last_availability = availability
        if not availability.available:
            return _vision_error_answer(
                question,
                reason=availability.reason or "provider_unavailable",
                provider=self.provider_kind,
                model=self.config.vision.model,
                source_provenance=artifact.source_provenance if artifact else CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
            )
        if artifact is None:
            return _vision_error_answer(
                question,
                reason="camera_artifact_missing",
                provider=self.provider_kind,
                model=self.config.vision.model,
            )

        prepared = self._prepare_image_payload(question, artifact)
        if isinstance(prepared, CameraVisionAnswer):
            return prepared
        data_url, preparation = prepared
        self.last_preparation = preparation
        prompt = build_camera_vision_prompt(question)
        input_items = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt.user_prompt},
                    {
                        "type": "input_image",
                        "image_url": data_url,
                        "detail": preparation.detail,
                    },
                ],
            }
        ]
        self.last_request_metadata = {
            **preparation.to_safe_dict(),
            "provider_kind": self.provider_kind,
            "model": self.config.vision.model,
            "analysis_mode": question.analysis_mode.value,
            "cloud_upload_performed": False,
            "raw_image_included": False,
        }
        self.network_access_attempted = True
        try:
            result = self._generate_response(
                instructions=prompt.system_prompt,
                input_items=input_items,
                model=self.config.vision.model,
            )
        except Exception as error:  # noqa: BLE001 - provider failures are normalized below.
            reason = _provider_error_code_from_exception(error)
            return _vision_error_answer(
                question,
                reason=reason,
                provider=self.provider_kind,
                model=self.config.vision.model,
                source_provenance=artifact.source_provenance,
                cloud_upload_performed=True,
            )

        return _normalize_openai_vision_answer(
            question,
            artifact,
            result,
            provider=self.provider_kind,
            model=self.config.vision.model,
        )

    def _prepare_image_payload(
        self,
        question: CameraVisionQuestion,
        artifact: CameraFrameArtifact,
    ) -> tuple[str, CameraVisionImagePreparation] | CameraVisionAnswer:
        artifact_format = str(artifact.image_format or "").strip().lower().lstrip(".")
        mime_type = _mime_type_for_format(artifact_format)
        if mime_type is None:
            return _vision_error_answer(
                question,
                reason="camera_artifact_unsupported_format",
                provider=self.provider_kind,
                model=self.config.vision.model,
                source_provenance=artifact.source_provenance,
            )
        if not artifact.file_path:
            return _vision_error_answer(
                question,
                reason="camera_artifact_missing",
                provider=self.provider_kind,
                model=self.config.vision.model,
                source_provenance=artifact.source_provenance,
            )
        max_bytes = _max_vision_image_bytes(self.config)
        try:
            image_bytes = _read_bounded_image_bytes(Path(artifact.file_path), max_bytes=max_bytes)
        except FileNotFoundError:
            return _vision_error_answer(
                question,
                reason="camera_artifact_missing",
                provider=self.provider_kind,
                model=self.config.vision.model,
                source_provenance=artifact.source_provenance,
            )
        except ValueError:
            return _vision_error_answer(
                question,
                reason="camera_artifact_too_large",
                provider=self.provider_kind,
                model=self.config.vision.model,
                source_provenance=artifact.source_provenance,
            )
        except OSError:
            return _vision_error_answer(
                question,
                reason="camera_artifact_unreadable",
                provider=self.provider_kind,
                model=self.config.vision.model,
                source_provenance=artifact.source_provenance,
            )
        encoded = base64.b64encode(image_bytes).decode("ascii")
        detail = str(getattr(self.config.vision, "detail", "auto") or "auto").strip().lower()
        if detail not in self.get_supported_detail_levels():
            detail = "auto"
        preparation = CameraVisionImagePreparation(
            image_artifact_id=artifact.image_artifact_id,
            artifact_format=artifact_format,
            artifact_size_bytes=len(image_bytes),
            mime_type=mime_type,
            detail=detail,
            source_provenance=artifact.source_provenance,
            storage_mode=artifact.storage_mode.value,
        )
        return f"data:{mime_type};base64,{encoded}", preparation

    def _generate_response(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        model: str,
    ) -> ProviderTurnResult:
        provider = self.responses_provider
        if provider is None:
            from stormhelm.core.providers.openai_responses import OpenAIResponsesProvider

            provider = OpenAIResponsesProvider(self.openai_config)  # type: ignore[arg-type]
        return asyncio.run(
            provider.generate(
                instructions=instructions,
                input_items=input_items,
                previous_response_id=None,
                tools=[],
                model=model,
                max_output_tokens=600,
            )
        )


class UnavailableVisionAnalysisProvider:
    provider_kind = "unavailable"

    def __init__(self, *, reason: str = "vision_analysis_provider_unavailable") -> None:
        self.reason = reason
        self.network_access_attempted = False

    def analyze_image(
        self,
        question: CameraVisionQuestion,
        artifact: CameraFrameArtifact | None,
    ) -> CameraVisionAnswer:
        del artifact
        return CameraVisionAnswer(
            vision_question_id=question.vision_question_id,
            image_artifact_id=question.image_artifact_id,
            answer_text=f"Camera vision analysis is unavailable: {self.reason}.",
            concise_answer="Camera vision analysis unavailable.",
            confidence=CameraConfidenceLevel.INSUFFICIENT,
            result_state=CameraAwarenessResultState.CAMERA_ANALYSIS_FAILED,
            provider="unavailable",
            model="unavailable",
            analysis_mode=question.analysis_mode,
            mock_answer=False,
            provider_kind="unavailable",
            cloud_analysis_performed=False,
            raw_image_included=False,
            evidence_summary="",
            uncertainty_reasons=[self.reason],
            safety_notes=[],
            error_code=self.reason,
            provenance={
                "source": CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
                "reason": self.reason,
                "cloud_upload_performed": False,
                "real_camera_used": False,
            },
            cloud_upload_performed=False,
        )


def _parse_resolution(value: str) -> tuple[int, int]:
    match = re.match(r"^\s*(?P<width>\d+)\s*x\s*(?P<height>\d+)\s*$", str(value or ""))
    if not match:
        return 1280, 720
    return int(match.group("width")), int(match.group("height"))


def _local_capture_temp_path(image_artifact_id: str) -> Path:
    root = Path(tempfile.gettempdir()) / "stormhelm-camera-awareness"
    return root / f"{image_artifact_id}.jpg"


def _local_hash_hint(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return "local:ephemeral"
    return f"local:ephemeral:{stat.st_size}"


def _capture_status_for_error(error_code: str) -> CameraCaptureStatus:
    if error_code == "camera_no_device":
        return CameraCaptureStatus.NO_DEVICE
    if error_code == "camera_device_busy":
        return CameraCaptureStatus.DEVICE_BUSY
    if error_code in {
        "camera_permission_denied",
        "permission_denied",
        "local_capture_backend_unavailable",
        "unsupported_platform",
    }:
        return CameraCaptureStatus.BLOCKED
    return CameraCaptureStatus.FAILED


def _unavailable_device(
    error_code: str,
    provider: str,
    *,
    message: str | None = None,
) -> CameraDeviceStatus:
    return CameraDeviceStatus(
        device_id="local-unavailable",
        display_name="Local camera unavailable",
        provider=provider,
        available=False,
        permission_state=CameraPermissionState.UNAVAILABLE,
        active=False,
        mock_device=False,
        source_provenance=CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
        error_code=error_code,
        error_message=message or error_code,
    )


def _parse_ffmpeg_dshow_devices(output: str) -> list[str]:
    devices: list[str] = []
    in_video_section = False
    for raw_line in str(output or "").splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if "directshow video devices" in lowered:
            in_video_section = True
            continue
        if "directshow audio devices" in lowered:
            in_video_section = False
        if not in_video_section:
            continue
        match = re.search(r'"(?P<device>[^"]+)"', line)
        if match:
            device = match.group("device").strip()
            if device and "alternative name" not in lowered:
                devices.append(device)
    return list(dict.fromkeys(devices))


def _ffmpeg_error_code(output: str) -> str:
    text = str(output or "").lower()
    if "permission" in text or "access is denied" in text:
        return "camera_permission_denied"
    if "busy" in text or "in use" in text:
        return "camera_device_busy"
    if "no such device" in text or "could not find" in text:
        return "camera_no_device"
    if "timeout" in text or "timed out" in text:
        return "camera_capture_timeout"
    return "camera_capture_failed"


def _winrt_error_code(payload: dict[str, Any]) -> str:
    code = str(payload.get("error_code") or "").strip().lower()
    if code:
        return code
    text = str(payload.get("error_message") or payload.get("message") or "").lower()
    if "permission" in text or "access is denied" in text or "unauthorized" in text:
        return "permission_denied"
    if "being used" in text or "busy" in text or "in use" in text:
        return "camera_device_busy"
    if "timeout" in text or "timed out" in text:
        return "camera_capture_timeout"
    if "no_camera_device" in text or "no camera" in text or "not found" in text:
        return "camera_no_device"
    return "camera_capture_failed"


def _image_dimensions(path: Path, *, fallback: str) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            if int(width) > 0 and int(height) > 0:
                return int(width), int(height)
    except Exception:
        pass
    return _parse_resolution(fallback)


def _run_powershell_json(
    executable: str,
    script: str,
    *,
    timeout_seconds: float,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ)
    env.update(extra_env or {})
    try:
        result = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, float(timeout_seconds)),
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error_code": "camera_capture_timeout",
            "error_message": "Windows camera command timed out.",
        }
    except OSError as error:
        return {
            "status": "error",
            "error_code": "local_capture_backend_unavailable",
            "error_message": str(error),
        }
    output = (result.stdout or "").strip() or (result.stderr or "").strip()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = {
            "status": "error",
            "error_code": "camera_capture_failed",
            "error_message": output or f"PowerShell exited with {result.returncode}.",
        }
    if result.returncode != 0 and str(payload.get("status") or "").lower() == "ok":
        payload["status"] = "error"
        payload["error_code"] = "camera_capture_failed"
    return payload


_WINRT_COMMON_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction SilentlyContinue
[Windows.Devices.Enumeration.DeviceInformation, Windows.Devices.Enumeration, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Enumeration.DeviceInformationCollection, Windows.Devices.Enumeration, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Enumeration.DeviceClass, Windows.Devices.Enumeration, ContentType = WindowsRuntime] | Out-Null
function Await-AsyncAction($Op, [int]$TimeoutMs=5000) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object { $_.Name -eq 'AsTask' -and -not $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } |
        Select-Object -First 1
    $task = $method.Invoke($null, @($Op))
    if (-not $task.Wait($TimeoutMs)) { throw 'camera_capture_timeout' }
    return $null
}
function Await-AsyncOperation($Op, [Type]$ResultType, [int]$TimeoutMs=5000) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -like 'IAsyncOperation*' } |
        Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Op))
    if (-not $task.Wait($TimeoutMs)) { throw 'camera_capture_timeout' }
    return $task.Result
}
"""

_WINRT_LIST_DEVICES_SCRIPT = _WINRT_COMMON_SCRIPT + r"""
try {
    $devices = Await-AsyncOperation ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync([Windows.Devices.Enumeration.DeviceClass]::VideoCapture)) ([Windows.Devices.Enumeration.DeviceInformationCollection]) 5000
    $items = @()
    $index = 0
    foreach ($device in $devices) {
        $items += [PSCustomObject]@{
            index = $index
            name = $device.Name
            id = $device.Id
            is_enabled = [bool]$device.IsEnabled
        }
        $index += 1
    }
    [PSCustomObject]@{ status='ok'; devices=$items } | ConvertTo-Json -Compress -Depth 6
} catch {
    [PSCustomObject]@{ status='error'; error_code='camera_probe_failed'; error_message=$_.Exception.Message } | ConvertTo-Json -Compress -Depth 4
    exit 1
}
"""

_WINRT_CAPTURE_SCRIPT = _WINRT_COMMON_SCRIPT + r"""
try {
    [Windows.Media.Capture.MediaCapture, Windows.Media.Capture, ContentType = WindowsRuntime] | Out-Null
    [Windows.Media.Capture.MediaCaptureInitializationSettings, Windows.Media.Capture, ContentType = WindowsRuntime] | Out-Null
    [Windows.Media.Capture.StreamingCaptureMode, Windows.Media.Capture, ContentType = WindowsRuntime] | Out-Null
    [Windows.Media.MediaProperties.ImageEncodingProperties, Windows.Media.MediaProperties, ContentType = WindowsRuntime] | Out-Null
    [Windows.Storage.StorageFolder, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
    [Windows.Storage.CreationCollisionOption, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
    [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null

    $outputPath = [string]$env:STORMHELM_CAMERA_OUTPUT_PATH
    if ([string]::IsNullOrWhiteSpace($outputPath)) { throw 'missing_output_path' }
    $targetId = [string]$env:STORMHELM_CAMERA_DEVICE_ID
    $devices = Await-AsyncOperation ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync([Windows.Devices.Enumeration.DeviceClass]::VideoCapture)) ([Windows.Devices.Enumeration.DeviceInformationCollection]) 5000
    if ($devices.Count -lt 1) { throw 'no_camera_device' }
    $selected = $null
    if (-not [string]::IsNullOrWhiteSpace($targetId)) {
        foreach ($device in $devices) {
            if ($device.Id -eq $targetId -or $device.Name -eq $targetId) {
                $selected = $device
                break
            }
        }
    }
    if ($null -eq $selected) { $selected = $devices[0] }
    $settings = [Windows.Media.Capture.MediaCaptureInitializationSettings]::new()
    $settings.VideoDeviceId = $selected.Id
    $settings.StreamingCaptureMode = [Windows.Media.Capture.StreamingCaptureMode]::Video
    $capture = [Windows.Media.Capture.MediaCapture]::new()
    try {
        Await-AsyncAction ($capture.InitializeAsync($settings)) 10000
        $folderPath = Split-Path -Parent $outputPath
        New-Item -ItemType Directory -Force -Path $folderPath | Out-Null
        $fileName = Split-Path -Leaf $outputPath
        $folder = Await-AsyncOperation ([Windows.Storage.StorageFolder]::GetFolderFromPathAsync($folderPath)) ([Windows.Storage.StorageFolder]) 5000
        $file = Await-AsyncOperation ($folder.CreateFileAsync($fileName, [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile]) 5000
        $props = [Windows.Media.MediaProperties.ImageEncodingProperties]::CreateJpeg()
        Await-AsyncAction ($capture.CapturePhotoToStorageFileAsync($props, $file)) 10000
    } finally {
        if ($null -ne $capture) { $capture.Dispose() }
    }
    $item = Get-Item -LiteralPath $outputPath -ErrorAction Stop
    [PSCustomObject]@{
        status='ok'
        device_name=$selected.Name
        device_id=$selected.Id
        path=$outputPath
        bytes=$item.Length
    } | ConvertTo-Json -Compress -Depth 5
} catch {
    $message = $_.Exception.Message
    $code = 'camera_capture_failed'
    if ($message -match 'no_camera_device') { $code = 'camera_no_device' }
    elseif ($message -match 'permission|denied|UnauthorizedAccess') { $code = 'permission_denied' }
    elseif ($message -match 'busy|used|in use') { $code = 'camera_device_busy' }
    elseif ($message -match 'timeout') { $code = 'camera_capture_timeout' }
    [PSCustomObject]@{ status='error'; error_code=$code; error_message=$message } | ConvertTo-Json -Compress -Depth 4
    exit 1
}
"""


def _mock_answer_for_fixture(fixture: str, normalized_question: str) -> tuple[str, str]:
    if "resistor" in fixture or "resistor" in normalized_question:
        concise = "Mock resistor fixture; likely a resistor component."
        answer = (
            "Mock camera analysis says this looks like a resistor fixture. "
            "C0 cannot verify bands, value, damage, or live image detail."
        )
    elif "connector" in fixture or "connector" in normalized_question:
        concise = "Mock connector fixture."
        answer = (
            "Mock camera analysis says this looks like a connector fixture. "
            "C0 cannot verify pin count, pitch, or exact series from a real frame."
        )
    elif "label" in normalized_question or "read" in normalized_question:
        concise = "Mock label fixture; text reading is simulated."
        answer = (
            "Mock camera analysis can simulate label reading, but C0 has no real image "
            "or OCR evidence."
        )
    else:
        concise = "Mock camera fixture."
        answer = (
            "Mock camera analysis completed against a deterministic fixture. "
            "No real camera frame or cloud vision was used."
        )
    return concise, answer


def _mock_helper_hints_for_fixture(fixture: str, normalized_question: str) -> dict[str, Any]:
    text = f"{fixture} {normalized_question}"
    if "resistor" in text:
        return {
            "helper_family": "engineering.resistor_color_bands",
            "visible_bands": ["brown", "black", "orange", "gold"],
            "band_confidence": "medium",
        }
    if "connector" in text or "jst" in text:
        return {
            "helper_family": "engineering.connector_identification",
            "likely_connector_family": "connector family uncertain",
            "scale_reference_present": False,
        }
    if "solder" in text or "joint" in text:
        return {
            "helper_family": "engineering.solder_joint_inspection",
            "visible_issue": "simulated solder joint observation",
        }
    if "label" in text or "marking" in text or "read" in text:
        return {
            "helper_family": "engineering.component_marking",
            "readable_text": "mock text",
            "uncertain_text": "",
        }
    return {}


def _normalize_openai_vision_answer(
    question: CameraVisionQuestion,
    artifact: CameraFrameArtifact,
    result: ProviderTurnResult,
    *,
    provider: str,
    model: str,
) -> CameraVisionAnswer:
    structured = result.raw_response.get("camera_vision")
    if isinstance(structured, dict) and structured.get("error_code") == "provider_safety_blocked":
        return _vision_error_answer(
            question,
            reason="provider_safety_blocked",
            provider=provider,
            model=model,
            source_provenance=artifact.source_provenance,
            cloud_upload_performed=True,
        )
    answer_text = ""
    concise_answer = ""
    detailed_answer: str | None = None
    evidence_summary = ""
    uncertainty_reasons: list[str] = []
    safety_notes: list[str] = []
    suggested_next_capture: str | None = None
    recommended_user_action: str | None = None
    helper_hints: dict[str, Any] = {}
    confidence = CameraConfidenceLevel.LOW
    if isinstance(structured, dict):
        answer_text = _sanitize_provider_text(
            structured.get("answer_text") or result.output_text or ""
        ).strip()
        concise_answer = _sanitize_provider_text(
            structured.get("concise_answer") or answer_text
        ).strip()
        detailed_answer = (
            _sanitize_provider_text(structured.get("detailed_answer") or "").strip()
            or None
        )
        evidence_summary = _sanitize_provider_text(
            structured.get("evidence_summary") or ""
        ).strip()
        uncertainty_reasons = _as_string_list(structured.get("uncertainty_reasons"))
        safety_notes = _ensure_visual_evidence_note(
            _as_string_list(structured.get("safety_notes"))
        )
        suggested_next_capture = (
            _sanitize_provider_text(structured.get("suggested_next_capture") or "").strip()
            or None
        )
        recommended_user_action = (
            _sanitize_provider_text(structured.get("recommended_user_action") or "").strip()
            or None
        )
        helper_hints = _safe_helper_hints(
            structured.get("helper_hints") or structured.get("engineering_helper")
        )
        confidence = _confidence_from_provider(structured.get("confidence"))
    else:
        answer_text = _sanitize_provider_text(result.output_text or "").strip()
        concise_answer = answer_text
        evidence_summary = "Provider returned unstructured visual analysis text."
        uncertainty_reasons = ["Provider did not return structured confidence metadata."]
        safety_notes = [_VISUAL_EVIDENCE_ONLY_NOTE]
        confidence = CameraConfidenceLevel.LOW
    if not answer_text:
        return _vision_error_answer(
            question,
            reason="provider_response_malformed",
            provider=provider,
            model=model,
            source_provenance=artifact.source_provenance,
            cloud_upload_performed=True,
        )
    return CameraVisionAnswer(
        vision_question_id=question.vision_question_id,
        image_artifact_id=question.image_artifact_id,
        answer_text=answer_text,
        concise_answer=concise_answer,
        detailed_answer=detailed_answer,
        confidence=confidence,
        result_state=CameraAwarenessResultState.CAMERA_ANSWER_READY,
        provider=provider,
        provider_kind=provider,
        model=model,
        analysis_mode=question.analysis_mode,
        mock_answer=False,
        cloud_upload_performed=True,
        cloud_analysis_performed=True,
        raw_image_included=False,
        evidence_summary=evidence_summary,
        uncertainty_reasons=uncertainty_reasons,
        suggested_next_capture=suggested_next_capture,
        recommended_user_action=recommended_user_action,
        safety_notes=safety_notes,
        helper_hints=helper_hints,
        provider_raw_ref=result.response_id,
        provenance={
            "source": artifact.source_provenance,
            "artifact_id": question.image_artifact_id,
            "artifact_format": artifact.image_format,
            "provider": provider,
            "provider_kind": provider,
            "model": model,
            "mock_analysis": False,
            "cloud_upload_performed": True,
            "cloud_analysis_performed": True,
            "raw_image_included": False,
            "real_camera_used": artifact.source_provenance == CAMERA_SOURCE_PROVENANCE_LOCAL,
            "provider_raw_ref": result.response_id,
        },
    )


def _vision_error_answer(
    question: CameraVisionQuestion,
    *,
    reason: str,
    provider: str,
    model: str,
    source_provenance: str = CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
    cloud_upload_performed: bool = False,
) -> CameraVisionAnswer:
    result_state = _vision_result_state_for_error(reason)
    return CameraVisionAnswer(
        vision_question_id=question.vision_question_id,
        image_artifact_id=question.image_artifact_id,
        answer_text=_vision_error_text(reason),
        concise_answer="Camera vision analysis unavailable.",
        confidence=CameraConfidenceLevel.INSUFFICIENT,
        result_state=result_state,
        provider=provider,
        provider_kind=provider,
        model=model,
        analysis_mode=question.analysis_mode,
        mock_answer=False,
        cloud_upload_performed=cloud_upload_performed,
        cloud_analysis_performed=False,
        raw_image_included=False,
        evidence_summary="",
        uncertainty_reasons=[reason],
        safety_notes=[],
        error_code=reason,
        provenance={
            "source": source_provenance,
            "reason": reason,
            "provider": provider,
            "provider_kind": provider,
            "model": model,
            "mock_analysis": False,
            "cloud_upload_performed": cloud_upload_performed,
            "cloud_analysis_performed": False,
            "raw_image_included": False,
        },
    )


def _vision_error_text(reason: str) -> str:
    messages = {
        "camera_cloud_analysis_disabled": (
            "I have the camera image, but cloud vision analysis is disabled."
        ),
        "camera_vision_confirmation_required": (
            "I have the camera image, but cloud vision analysis needs explicit confirmation."
        ),
        "camera_artifact_expired": (
            "I no longer have that camera image. I can capture another still if camera access is enabled."
        ),
        "camera_artifact_missing": "That camera image artifact is missing.",
        "camera_artifact_missing_metadata": "That camera image artifact is missing.",
        "camera_artifact_unreadable": "That camera image artifact is not readable.",
        "camera_artifact_too_large": "That camera image is too large for vision analysis.",
        "camera_artifact_unsupported_format": (
            "That camera image format is not supported for vision analysis."
        ),
        "api_key_missing": "Camera vision provider credentials are not configured.",
        "provider_timeout": "Camera vision provider timed out.",
        "provider_rate_limited": "Camera vision provider rate-limited the request.",
        "provider_auth_failed": "Camera vision provider authentication failed.",
        "provider_bad_request": "Camera vision provider rejected the image request.",
        "provider_safety_blocked": "Camera vision provider blocked this image for safety.",
        "provider_response_malformed": "Camera vision provider returned an unusable response.",
    }
    return messages.get(reason, f"Camera vision analysis failed: {reason}.")


def _vision_result_state_for_error(reason: str) -> CameraAwarenessResultState:
    mapping = {
        "camera_cloud_analysis_disabled": CameraAwarenessResultState.CAMERA_CLOUD_ANALYSIS_DISABLED,
        "camera_vision_confirmation_required": CameraAwarenessResultState.CAMERA_VISION_PERMISSION_REQUIRED,
        "camera_artifact_missing": CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_MISSING,
        "camera_artifact_missing_metadata": CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_MISSING,
        "camera_artifact_expired": CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_EXPIRED,
        "camera_artifact_unreadable": CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_UNREADABLE,
        "camera_artifact_too_large": CameraAwarenessResultState.CAMERA_VISION_IMAGE_TOO_LARGE,
        "camera_artifact_unsupported_format": CameraAwarenessResultState.CAMERA_VISION_UNSUPPORTED_FORMAT,
        "provider_timeout": CameraAwarenessResultState.CAMERA_VISION_PROVIDER_TIMEOUT,
        "provider_rate_limited": CameraAwarenessResultState.CAMERA_VISION_PROVIDER_RATE_LIMITED,
        "provider_auth_failed": CameraAwarenessResultState.CAMERA_VISION_PROVIDER_AUTH_FAILED,
        "provider_bad_request": CameraAwarenessResultState.CAMERA_VISION_PROVIDER_BAD_REQUEST,
        "provider_safety_blocked": CameraAwarenessResultState.CAMERA_VISION_PROVIDER_SAFETY_BLOCKED,
        "provider_response_malformed": CameraAwarenessResultState.CAMERA_VISION_PROVIDER_RESPONSE_MALFORMED,
        "api_key_missing": CameraAwarenessResultState.CAMERA_VISION_PROVIDER_UNAVAILABLE,
        "provider_unavailable": CameraAwarenessResultState.CAMERA_VISION_PROVIDER_UNAVAILABLE,
    }
    return mapping.get(reason, CameraAwarenessResultState.CAMERA_ANALYSIS_FAILED)


def _provider_error_code_from_exception(error: Exception) -> str:
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        return "provider_timeout"
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    try:
        status = int(status_code)
    except (TypeError, ValueError):
        status = 0
    if status in {401, 403}:
        return "provider_auth_failed"
    if status == 429:
        return "provider_rate_limited"
    if status in {400, 413, 415, 422}:
        return "provider_bad_request"
    if "rate" in str(error).lower():
        return "provider_rate_limited"
    if "auth" in str(error).lower() or "api key" in str(error).lower():
        return "provider_auth_failed"
    return "unknown_provider_error"


def _confidence_from_provider(value: Any) -> CameraConfidenceLevel:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low", "insufficient"}:
        return CameraConfidenceLevel(text)
    return CameraConfidenceLevel.LOW


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        item = _sanitize_provider_text(value).strip()
        return [item] if item else []
    if isinstance(value, list):
        return [
            _sanitize_provider_text(item).strip()
            for item in value
            if _sanitize_provider_text(item).strip()
        ]
    return []


def _safe_helper_hints(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "helper_family",
        "family",
        "visible_bands",
        "bands",
        "band_confidence",
        "quality_warnings",
        "likely_connector_family",
        "scale_reference_present",
        "readable_text",
        "uncertain_text",
        "visible_issue",
        "visible_part",
        "indicator_state",
        "visual_estimate",
    }
    safe: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key or "").strip()
        if key_text not in allowed or key_text.lower() in _RAW_PROVIDER_TEXT_FIELDS:
            continue
        if isinstance(item, bool):
            safe[key_text] = item
        elif isinstance(item, (list, tuple, set)):
            safe[key_text] = [
                _sanitize_provider_text(entry).strip()[:120]
                for entry in item
                if _sanitize_provider_text(entry).strip()
            ][:12]
        else:
            safe[key_text] = _sanitize_provider_text(item).strip()[:240]
    return safe


def _ensure_visual_evidence_note(notes: list[str]) -> list[str]:
    if _VISUAL_EVIDENCE_ONLY_NOTE not in notes:
        return [*notes, _VISUAL_EVIDENCE_ONLY_NOTE]
    return notes


def _sanitize_provider_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = re.sub(
        r"data:image/[^\s'\"<>]+;base64,[A-Za-z0-9+/=._:-]+",
        _REDACTED_IMAGE_PAYLOAD,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"base64,[A-Za-z0-9+/=._:-]+",
        _REDACTED_IMAGE_PAYLOAD,
        text,
        flags=re.IGNORECASE,
    )
    for field in _RAW_PROVIDER_TEXT_FIELDS:
        text = re.sub(re.escape(field), "[redacted-image-field]", text, flags=re.IGNORECASE)
    return text


def _mime_type_for_format(value: str) -> str | None:
    normalized = str(value or "").strip().lower().lstrip(".")
    if normalized in {"jpg", "jpeg"}:
        return "image/jpeg"
    if normalized == "png":
        return "image/png"
    if normalized == "webp":
        return "image/webp"
    if normalized == "gif":
        return "image/gif"
    return None


def _max_vision_image_bytes(config: CameraAwarenessConfig) -> int:
    values: list[int] = []
    for value in (
        getattr(config.vision, "max_image_bytes", None),
        getattr(config.capture, "max_artifact_bytes", None),
    ):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            values.append(parsed)
    return min(values) if values else 8_000_000


def _read_bounded_image_bytes(path: Path, *, max_bytes: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("camera image exceeds configured max bytes")
    return data
