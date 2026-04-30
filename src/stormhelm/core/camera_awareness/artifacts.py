from __future__ import annotations

from datetime import datetime
from pathlib import Path

from stormhelm.core.camera_awareness.models import (
    CameraArtifactCleanupResult,
    CameraArtifactReadiness,
    CameraArtifactResolution,
    CameraAwarenessResultState,
    CameraFrameArtifact,
)


SUPPORTED_CAMERA_ANALYSIS_FORMATS = frozenset({"jpg", "jpeg", "png", "mock"})


class CameraArtifactStore:
    """In-memory C0 frame artifact lifecycle.

    C0 intentionally keeps artifacts ephemeral. The store only holds typed
    metadata and fixture references, never raw image bytes.
    """

    def __init__(self) -> None:
        self._artifacts: dict[str, CameraFrameArtifact] = {}
        self._pending_cleanup_artifacts: dict[str, CameraFrameArtifact] = {}
        self._latest_artifact_id: str | None = None
        self.last_cleanup_result: CameraArtifactCleanupResult | None = None

    def add(self, artifact: CameraFrameArtifact) -> CameraFrameArtifact:
        self._artifacts[artifact.image_artifact_id] = artifact
        self._latest_artifact_id = artifact.image_artifact_id
        return artifact

    def get(self, artifact_id: str, *, at: datetime | None = None) -> CameraFrameArtifact | None:
        key = str(artifact_id or "").strip()
        artifact = self._artifacts.get(key)
        if artifact is None:
            return None
        if artifact.is_expired(at=at):
            self._artifacts.pop(key, None)
            self.last_cleanup_result = _delete_ephemeral_file(artifact)
            self._remember_pending_cleanup(artifact, self.last_cleanup_result)
            return None
        return artifact

    def peek(self, artifact_id: str | None) -> CameraFrameArtifact | None:
        return self._artifacts.get(str(artifact_id or "").strip())

    @property
    def latest_artifact_id(self) -> str | None:
        return self._latest_artifact_id

    def latest(self, *, at: datetime | None = None) -> CameraFrameArtifact | None:
        if not self._latest_artifact_id:
            return None
        return self.get(self._latest_artifact_id, at=at)

    def expire(self, artifact_id: str) -> bool:
        artifact = self._artifacts.pop(str(artifact_id or "").strip(), None)
        if artifact is None:
            self.last_cleanup_result = None
            return False
        self.last_cleanup_result = _delete_ephemeral_file(artifact)
        self._remember_pending_cleanup(artifact, self.last_cleanup_result)
        return True

    def retry_cleanup(self, artifact_id: str) -> CameraArtifactCleanupResult:
        key = str(artifact_id or "").strip()
        artifact = self._pending_cleanup_artifacts.get(key)
        if artifact is None:
            self.last_cleanup_result = CameraArtifactCleanupResult(
                image_artifact_id=key,
                cleanup_attempted=False,
                cleanup_succeeded=True,
                cleanup_failed=False,
                cleanup_pending=False,
            )
            return self.last_cleanup_result
        self.last_cleanup_result = _delete_ephemeral_file(artifact)
        self._remember_pending_cleanup(artifact, self.last_cleanup_result)
        return self.last_cleanup_result

    def resolve_for_followup(
        self,
        artifact_id: str | None = None,
        *,
        at: datetime | None = None,
    ) -> CameraArtifactResolution:
        artifact = self.get(artifact_id or self._latest_artifact_id or "", at=at)
        if artifact is not None:
            return CameraArtifactResolution(
                artifact=artifact,
                result_state=CameraAwarenessResultState.CAMERA_ANSWER_READY,
                message="Camera artifact is still available.",
            )
        return CameraArtifactResolution(
            artifact=None,
            result_state=CameraAwarenessResultState.CAMERA_ARTIFACT_EXPIRED,
            message="I no longer have that camera frame. It was ephemeral and has expired.",
        )

    def _remember_pending_cleanup(
        self,
        artifact: CameraFrameArtifact,
        result: CameraArtifactCleanupResult | None,
    ) -> None:
        if result is not None and (result.cleanup_failed or result.cleanup_pending):
            self._pending_cleanup_artifacts[artifact.image_artifact_id] = artifact
            return
        self._pending_cleanup_artifacts.pop(artifact.image_artifact_id, None)


def get_artifact_readiness(
    artifact: CameraFrameArtifact | None,
    *,
    image_artifact_id: str | None = None,
    at: datetime | None = None,
    max_size_bytes: int | None = None,
    allowed_formats: set[str] | frozenset[str] | None = None,
) -> CameraArtifactReadiness:
    checked_at = at or datetime.now().astimezone()
    if artifact is None:
        return CameraArtifactReadiness(
            image_artifact_id=str(image_artifact_id or "missing-artifact"),
            ready=False,
            artifact_exists=False,
            artifact_readable=False,
            artifact_expired=False,
            reason_code="camera_artifact_missing_metadata",
            message="Camera artifact metadata is missing.",
            checked_at=checked_at,
        )

    artifact_format = _artifact_format(artifact)
    storage_mode = artifact.storage_mode
    if artifact.is_expired(at=at):
        return CameraArtifactReadiness(
            image_artifact_id=artifact.image_artifact_id,
            ready=False,
            artifact_exists=_artifact_exists(artifact),
            artifact_readable=False,
            artifact_expired=True,
            artifact_size_bytes=_artifact_size(artifact),
            artifact_format=artifact_format,
            artifact_source_provenance=artifact.source_provenance,
            storage_mode=storage_mode,
            reason_code="camera_artifact_expired",
            message="Camera artifact is expired and cannot be analyzed.",
            checked_at=checked_at,
        )

    exists, readable, size_bytes, reason_code, message = _artifact_file_state(artifact)
    if not exists:
        return CameraArtifactReadiness(
            image_artifact_id=artifact.image_artifact_id,
            ready=False,
            artifact_exists=False,
            artifact_readable=False,
            artifact_expired=False,
            artifact_size_bytes=size_bytes,
            artifact_format=artifact_format,
            artifact_source_provenance=artifact.source_provenance,
            storage_mode=storage_mode,
            reason_code=reason_code,
            message=message,
            checked_at=checked_at,
        )
    if not readable:
        return CameraArtifactReadiness(
            image_artifact_id=artifact.image_artifact_id,
            ready=False,
            artifact_exists=True,
            artifact_readable=False,
            artifact_expired=False,
            artifact_size_bytes=size_bytes,
            artifact_format=artifact_format,
            artifact_source_provenance=artifact.source_provenance,
            storage_mode=storage_mode,
            reason_code=reason_code,
            message=message,
            checked_at=checked_at,
        )

    formats = allowed_formats or SUPPORTED_CAMERA_ANALYSIS_FORMATS
    if artifact_format not in formats:
        return CameraArtifactReadiness(
            image_artifact_id=artifact.image_artifact_id,
            ready=False,
            artifact_exists=True,
            artifact_readable=True,
            artifact_expired=False,
            artifact_size_bytes=size_bytes,
            artifact_format=artifact_format,
            artifact_source_provenance=artifact.source_provenance,
            storage_mode=storage_mode,
            reason_code="camera_artifact_unsupported_format",
            message=f"Camera artifact format is not ready for analysis: {artifact_format}.",
            checked_at=checked_at,
        )

    if max_size_bytes is not None and size_bytes is not None and size_bytes > max_size_bytes:
        return CameraArtifactReadiness(
            image_artifact_id=artifact.image_artifact_id,
            ready=False,
            artifact_exists=True,
            artifact_readable=True,
            artifact_expired=False,
            artifact_size_bytes=size_bytes,
            artifact_format=artifact_format,
            artifact_source_provenance=artifact.source_provenance,
            storage_mode=storage_mode,
            reason_code="camera_artifact_too_large",
            message="Camera artifact exceeds the configured analysis size limit.",
            checked_at=checked_at,
        )

    return CameraArtifactReadiness(
        image_artifact_id=artifact.image_artifact_id,
        ready=True,
        artifact_exists=True,
        artifact_readable=True,
        artifact_expired=False,
        artifact_size_bytes=size_bytes,
        artifact_format=artifact_format,
        artifact_source_provenance=artifact.source_provenance,
        storage_mode=storage_mode,
        message="Camera artifact is fresh, readable, and ready for mock analysis handoff.",
        checked_at=checked_at,
    )


def validate_artifact_for_analysis(
    artifact: CameraFrameArtifact | None,
    *,
    image_artifact_id: str | None = None,
    at: datetime | None = None,
    max_size_bytes: int | None = None,
    allowed_formats: set[str] | frozenset[str] | None = None,
) -> CameraArtifactReadiness:
    return get_artifact_readiness(
        artifact,
        image_artifact_id=image_artifact_id,
        at=at,
        max_size_bytes=max_size_bytes,
        allowed_formats=allowed_formats,
    )


def reject_if_expired_or_missing(
    artifact: CameraFrameArtifact | None,
    *,
    image_artifact_id: str | None = None,
    at: datetime | None = None,
    max_size_bytes: int | None = None,
    allowed_formats: set[str] | frozenset[str] | None = None,
) -> CameraArtifactReadiness:
    return validate_artifact_for_analysis(
        artifact,
        image_artifact_id=image_artifact_id,
        at=at,
        max_size_bytes=max_size_bytes,
        allowed_formats=allowed_formats,
    )


def _artifact_format(artifact: CameraFrameArtifact) -> str:
    value = str(artifact.image_format or "").strip().lower().lstrip(".")
    if value:
        return value
    if artifact.file_path:
        suffix = Path(artifact.file_path).suffix.lower().lstrip(".")
        if suffix:
            return suffix
    return "unknown"


def _artifact_exists(artifact: CameraFrameArtifact) -> bool:
    if artifact.mock_artifact:
        return True
    if not artifact.file_path:
        return False
    try:
        return Path(artifact.file_path).is_file()
    except OSError:
        return False


def _artifact_size(artifact: CameraFrameArtifact) -> int | None:
    if artifact.mock_artifact:
        return 0
    if not artifact.file_path:
        return None
    try:
        return Path(artifact.file_path).stat().st_size
    except OSError:
        return None


def _artifact_file_state(
    artifact: CameraFrameArtifact,
) -> tuple[bool, bool, int | None, str | None, str]:
    if artifact.mock_artifact:
        return True, True, 0, None, "Mock camera artifact is fixture-backed."
    if not artifact.file_path:
        return (
            False,
            False,
            None,
            "camera_artifact_missing",
            "Camera artifact has no readable file reference.",
        )
    path = Path(artifact.file_path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (
            False,
            False,
            None,
            "camera_artifact_missing",
            "Camera artifact file is missing.",
        )
    except OSError as error:
        return (
            False,
            False,
            None,
            "camera_artifact_unreadable",
            f"Camera artifact file cannot be checked: {error}.",
        )
    if not path.is_file():
        return (
            False,
            False,
            None,
            "camera_artifact_missing",
            "Camera artifact file reference is not a file.",
        )
    try:
        with path.open("rb"):
            pass
    except OSError as error:
        return (
            True,
            False,
            stat.st_size,
            "camera_artifact_unreadable",
            f"Camera artifact file cannot be read: {error}.",
        )
    return True, True, stat.st_size, None, "Camera artifact file is readable."


def _delete_ephemeral_file(artifact: CameraFrameArtifact) -> CameraArtifactCleanupResult:
    result_id = artifact.image_artifact_id
    if not artifact.file_path:
        return CameraArtifactCleanupResult(
            image_artifact_id=result_id,
            cleanup_attempted=False,
            cleanup_succeeded=True,
        )
    if artifact.persisted_by_user_request:
        return CameraArtifactCleanupResult(
            image_artifact_id=result_id,
            cleanup_attempted=False,
            cleanup_succeeded=True,
        )
    path = Path(artifact.file_path)
    try:
        existed_before = path.exists()
    except OSError:
        existed_before = False
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        try:
            exists_after = path.exists()
        except OSError:
            exists_after = True
        return CameraArtifactCleanupResult(
            image_artifact_id=result_id,
            cleanup_attempted=True,
            cleanup_succeeded=False,
            cleanup_failed=True,
            cleanup_pending=exists_after,
            file_existed_before=existed_before,
            file_exists_after=exists_after,
            error_code="camera_artifact_cleanup_failed",
            error_message=str(error),
        )
    try:
        exists_after = path.exists()
    except OSError:
        exists_after = True
    cleanup_failed = exists_after
    return CameraArtifactCleanupResult(
        image_artifact_id=result_id,
        cleanup_attempted=True,
        cleanup_succeeded=not cleanup_failed,
        cleanup_failed=cleanup_failed,
        cleanup_pending=cleanup_failed,
        file_existed_before=existed_before,
        file_exists_after=exists_after,
        error_code="camera_artifact_cleanup_failed" if cleanup_failed else None,
        error_message="Camera artifact file still exists after cleanup." if cleanup_failed else None,
    )
