from __future__ import annotations

from pathlib import Path

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CameraCaptureRequest,
    CameraDeviceStatus,
    CameraPermissionState,
    LocalCameraCaptureProvider,
    LocalStillCaptureBackendResult,
)
from stormhelm.core.events import EventBuffer
from stormhelm.core.kraken.camera_awareness_live import (
    CameraLiveGates,
    build_gate_summary,
    build_live_camera_corpus,
    execute_corpus,
    preflight_camera,
    run_lane,
)
from stormhelm.core.orchestrator.planner import DeterministicPlanner


class KrakenFakeBackend:
    backend_kind = "kraken_fake_local_still"

    def __init__(self, *, available: bool = True, error_code: str | None = None) -> None:
        self.available = available
        self.error_code = error_code
        self.capture_calls = 0
        self.output_paths: list[Path] = []

    def is_available(self) -> bool:
        return self.available

    def get_devices(self, *, timeout_seconds: float) -> list[CameraDeviceStatus]:
        del timeout_seconds
        if not self.available:
            return [
                CameraDeviceStatus(
                    device_id="local-default",
                    display_name="No local camera device",
                    provider=self.backend_kind,
                    available=False,
                    permission_state=CameraPermissionState.UNAVAILABLE,
                    mock_device=False,
                    source_provenance="camera_unavailable",
                    error_code="camera_no_device",
                    error_message="No camera device was available.",
                )
            ]
        return [
            CameraDeviceStatus(
                device_id="fake-camera-0",
                display_name="Fake Unit Camera",
                provider=self.backend_kind,
                available=True,
                permission_state=CameraPermissionState.UNKNOWN,
                mock_device=False,
                source_provenance="camera_local",
            )
        ]

    def capture_still(
        self,
        *,
        device_id: str,
        output_path: Path,
        timeout_seconds: float,
        requested_resolution: str,
    ) -> LocalStillCaptureBackendResult:
        del timeout_seconds, requested_resolution
        self.capture_calls += 1
        self.output_paths.append(output_path)
        if not self.available:
            return LocalStillCaptureBackendResult(
                success=False,
                error_code="camera_no_device",
                error_message="No fake camera available.",
                device_id=device_id,
            )
        if self.error_code:
            return LocalStillCaptureBackendResult(
                success=False,
                error_code=self.error_code,
                error_message=f"Fake capture failed: {self.error_code}",
                device_id=device_id,
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"real-frame-placeholder")
        return LocalStillCaptureBackendResult(
            success=True,
            device_id=device_id,
            width=640,
            height=480,
            image_format="jpg",
            file_path=output_path,
        )


def _live_camera_config(temp_project_root, backend: KrakenFakeBackend):
    config = load_config(project_root=temp_project_root, env={})
    camera = config.camera_awareness
    camera.enabled = True
    camera.capture.provider = "local"
    camera.capture.timeout_seconds = 1.0
    camera.capture.requested_resolution = "640x480"
    camera.privacy.confirm_before_capture = False
    camera.dev.mock_capture_enabled = False
    camera.dev.mock_vision_enabled = False
    camera.vision.provider = "mock"
    provider = LocalCameraCaptureProvider(camera, backend=backend)
    return config, provider


def _winner(message: str) -> str:
    decision = DeterministicPlanner().plan(
        message,
        session_id="camera-live-route",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state={},
        active_context={},
        recent_tool_results=[],
    )
    return decision.route_state.to_dict()["winner"]["route_family"]


def test_preflight_requires_captured_frame_not_just_device(temp_project_root) -> None:
    config, provider = _live_camera_config(temp_project_root, KrakenFakeBackend())
    events = EventBuffer(capacity=32)

    report = preflight_camera(
        config.camera_awareness,
        gates=CameraLiveGates(live_camera_tests_enabled=True, require_real_device=True),
        capture_provider=provider,
        events=events,
    )

    assert report.status == "ready"
    assert report.camera_available is True
    assert report.camera_opened is True
    assert report.frame_captured is True
    assert report.capture_width == 640
    assert report.capture_height == 480
    assert report.raw_frame_persisted is False
    assert provider.capture_attempted is True
    assert provider.hardware_access_attempted is True
    assert provider.release_count == 1
    assert not _contains_raw_frame(events.recent(limit=32))


def test_missing_camera_is_typed_unavailable(temp_project_root) -> None:
    config, provider = _live_camera_config(temp_project_root, KrakenFakeBackend(available=False))

    report = preflight_camera(
        config.camera_awareness,
        gates=CameraLiveGates(live_camera_tests_enabled=True, require_real_device=True),
        capture_provider=provider,
    )

    assert report.status == "no_camera_device"
    assert report.camera_available is False
    assert report.frame_captured is False
    assert "camera_no_device" in report.blocking_reasons


def test_permission_denied_maps_to_blocked_state(temp_project_root) -> None:
    config, provider = _live_camera_config(
        temp_project_root,
        KrakenFakeBackend(error_code="permission_denied"),
    )

    report = preflight_camera(
        config.camera_awareness,
        gates=CameraLiveGates(live_camera_tests_enabled=True, require_real_device=True),
        capture_provider=provider,
    )

    assert report.status == "permission_denied"
    assert report.frame_captured is False
    assert "permission_denied" in report.blocking_reasons


def test_live_camera_corpus_and_rows_do_not_use_mock_or_provider(temp_project_root) -> None:
    config, provider = _live_camera_config(temp_project_root, KrakenFakeBackend())
    gates = CameraLiveGates(live_camera_tests_enabled=True, require_real_device=True)
    preflight = preflight_camera(config.camera_awareness, gates=gates, capture_provider=provider)
    rows = execute_corpus(
        build_live_camera_corpus(),
        config=config,
        gates=gates,
        preflight=preflight,
        capture_provider=provider,
    )
    gate = build_gate_summary(rows, preflight=preflight)

    assert gate["fake_or_mock_camera_rows"] == 0
    assert gate["generic_provider_hijack_rows"] == 0
    assert gate["provider_calls_total"] == 0
    assert gate["identity_claim_violations"] == 0
    assert gate["emotion_claim_violations"] == 0
    assert gate["surveillance_claim_violations"] == 0
    assert gate["raw_frame_leak_count"] == 0
    assert gate["release_posture"] == "pass"


def test_run_lane_writes_bounded_artifacts_without_raw_frames(temp_project_root, tmp_path) -> None:
    config, provider = _live_camera_config(temp_project_root, KrakenFakeBackend())

    summary = run_lane(
        output_dir=tmp_path,
        config=config,
        gates=CameraLiveGates(live_camera_tests_enabled=True, require_real_device=True),
        capture_provider=provider,
    )

    assert summary["release_posture"] == "pass"
    assert summary["real_camera_capture_attempted_rows"] > 0
    assert summary["real_camera_capture_success_rows"] > 0
    assert summary["fake_or_mock_camera_rows"] == 0
    assert (tmp_path / "camera_awareness_kraken_report.json").exists()
    assert (tmp_path / "camera_awareness_kraken_rows.jsonl").exists()
    assert "real-frame-placeholder" not in (tmp_path / "camera_awareness_kraken_report.json").read_text(encoding="utf-8")


def test_run_lane_can_save_artifact_refs_only_when_explicit(temp_project_root, tmp_path) -> None:
    config, provider = _live_camera_config(temp_project_root, KrakenFakeBackend())

    summary = run_lane(
        output_dir=tmp_path,
        config=config,
        gates=CameraLiveGates(
            live_camera_tests_enabled=True,
            require_real_device=True,
            save_artifacts=True,
        ),
        capture_provider=provider,
    )

    report_text = (tmp_path / "camera_awareness_kraken_report.json").read_text(encoding="utf-8")
    assert summary["artifacts_saved_count"] > 0
    assert "camera-artifact:" in report_text
    assert "real-frame-placeholder" not in report_text
    assert summary["raw_frame_leak_count"] == 0


def test_camera_route_ownership_blocks_provider_for_live_camera_prompts() -> None:
    camera_prompts = [
        "what can you see through the camera?",
        "is the camera working?",
        "are you watching me right now?",
        "did you see what happened a minute ago?",
        "can you identify who is in frame?",
        "am I smiling?",
        "is anyone behind me?",
        "verify the room is safe",
        "keep watching the camera",
        "record video until I say stop",
        "take a camera snapshot",
        "save this camera image",
    ]
    for prompt in camera_prompts:
        assert _winner(prompt) == "camera_awareness", prompt

    assert _winner("what is on my screen?") == "screen_awareness"
    assert _winner("read this URL https://example.com") == "web_retrieval"


def _contains_raw_frame(events) -> bool:  # noqa: ANN001
    for event in events:
        payload = event.get("payload", {})
        text = str(payload)
        if "real-frame-placeholder" in text or "data:image" in text or "base64," in text:
            return True
        if "raw_image" in payload or "image_bytes" in payload or "image_base64" in payload:
            return True
    return False
