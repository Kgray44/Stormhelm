from __future__ import annotations

from typing import Any

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CameraAwarenessSubsystem,
    CameraCaptureRequest,
    MockVisionAnalysisProvider,
)
from stormhelm.core.camera_awareness.providers import CameraCaptureProvider
from stormhelm.ui.bridge import UiBridge


FORBIDDEN_UI_KEYS = {
    "api_key",
    "authorization",
    "bytes",
    "file_path",
    "image_base64",
    "image_bytes",
    "image_url",
    "local_path",
    "path",
    "provider_request",
    "provider_request_body",
    "raw_bytes",
    "raw_image",
    "request_body",
    "temp_path",
}
FORBIDDEN_UI_TOKENS = (
    "data:image",
    "base64,",
    "SECRET_IMAGE_PAYLOAD",
    "sk-test-secret",
    "C:\\Temp\\camera-frame.jpg",
)


def _contains_forbidden_payload(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_UI_KEYS:
                return True
            if _contains_forbidden_payload(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_contains_forbidden_payload(item) for item in value)
    text = str(value)
    return any(token in text for token in FORBIDDEN_UI_TOKENS)


def _entries_by_primary(station: dict[str, Any]) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    for section in station.get("sections", []):
        for entry in section.get("entries", []):
            entries[str(entry.get("primary", ""))] = entry
    return entries


def _sections_by_title(station: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(section.get("title", "")): section for section in station.get("sections", [])}


def _actions_by_label(actions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(action.get("label", "")): action for action in actions}


def _camera_request(
    *,
    stage: str = "camera_answer_ready",
    result_state: str | None = None,
) -> dict[str, Any]:
    return {
        "request_id": "camera-c4-request",
        "family": "camera_awareness",
        "subject": "camera still",
        "request_type": "camera_awareness_request",
        "query_shape": "camera_awareness_request",
        "parameters": {
            "request_stage": stage,
            "result_state": result_state or stage,
            "selected_source_route": "camera_awareness",
        },
    }


def _camera_status(**overrides: Any) -> dict[str, Any]:
    status: dict[str, Any] = {
        "enabled": True,
        "route_family": "camera_awareness",
        "providerKind": "local",
        "captureProviderKind": "local",
        "visionProviderKind": "openai",
        "configuredCaptureProvider": "local",
        "configuredVisionProvider": "openai",
        "mockMode": False,
        "mockCapture": False,
        "realCameraUsed": True,
        "cloudUploadPerformed": True,
        "cloudAnalysisPerformed": True,
        "rawImageIncluded": False,
        "storageMode": "ephemeral",
        "permissionState": "granted",
        "lastVisionStatus": "camera_answer_ready",
        "lastVisionConfidence": "medium",
        "lastArtifactFresh": True,
        "lastArtifactExpired": False,
        "artifactExpired": False,
        "artifactReadable": True,
        "artifactExists": True,
        "artifactSizeBytes": 2048,
        "artifactFormat": "jpg",
        "artifactSourceProvenance": "camera_local",
        "latestArtifactId": "camera-frame-c4",
        "cleanupPending": False,
        "cleanupFailed": False,
        "visionProviderAvailable": True,
    }
    status.update(overrides)
    return status


def _answer_message(answer: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "image_artifact_id": "camera-frame-c4",
        "answer_text": "Likely a JST-style connector.",
        "concise_answer": "Likely JST-style connector.",
        "confidence": "medium",
        "evidence_summary": "White shrouded body with two visible pins.",
        "uncertainty_reasons": ["No scale reference is visible."],
        "recommended_user_action": "Compare the pitch before ordering a replacement.",
        "safety_notes": ["Visual evidence only; not verification or action authority."],
        "provenance": {
            "source": "camera_local",
            "raw_image_included": False,
            "cloud_upload_performed": True,
        },
        "mock_answer": False,
        "provider_kind": "openai",
        "cloud_analysis_performed": True,
        "cloud_upload_performed": True,
        "raw_image_included": False,
    }
    if answer:
        payload.update(answer)
    return {
        "message_id": "assistant-camera-c4",
        "role": "assistant",
        "content": payload["answer_text"],
        "created_at": "2026-04-30T19:00:00Z",
        "metadata": {
            "bearing_title": "Camera Awareness",
            "micro_response": payload["concise_answer"],
            "camera_awareness": {"vision_answer": payload},
            "route_state": {
                "winner": {
                    "route_family": "camera_awareness",
                    "query_shape": "camera_awareness_request",
                    "posture": "clear_winner",
                    "status": "camera_answer_ready",
                },
                "decomposition": {"subject": "camera still"},
            },
        },
    }


def _apply_answer_snapshot(
    bridge: UiBridge,
    *,
    status: dict[str, Any] | None = None,
    answer: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
) -> None:
    bridge.apply_snapshot(
        {
            "history": [_answer_message(answer)],
            "status": {"camera_awareness": status or _camera_status()},
            "active_request_state": request or _camera_request(),
        }
    )


def _camera_station(bridge: UiBridge) -> dict[str, Any]:
    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    assert panels["camera-visual-context"]["contentKind"] == "command-station"
    return panels["camera-visual-context"]["stationData"]


def test_c4_camera_answer_opens_deck_with_safe_visual_artifact_panel(temp_config) -> None:
    bridge = UiBridge(temp_config)

    _apply_answer_snapshot(bridge)

    ghost_actions = _actions_by_label(bridge.ghostActionStrip)
    station = _camera_station(bridge)
    visual = station["visualArtifact"]
    sections = _sections_by_title(station)
    entries = _entries_by_primary(station)
    station_actions = _actions_by_label(station["actions"])

    assert ghost_actions["Open In Deck"]["enabled"] is True
    assert ghost_actions["Open In Deck"]["localAction"] == "open_panel:camera-visual-context"
    assert station["title"] == "Camera Visual Context"
    assert visual["previewKind"] == "safe_ref"
    assert visual["safePreviewRef"] == "camera-artifact:camera-frame-c4"
    assert visual["rawPayloadIncluded"] is False
    assert visual["directFilePathIncluded"] is False
    assert visual["artifactState"] == "fresh"
    assert visual["storageMode"] == "ephemeral"
    assert {"Visual Artifact", "Analysis Detail", "Provenance And Policy", "Artifact Lifecycle", "Trace Boundary"}.issubset(sections)
    assert entries["Answer"]["secondary"] == "Likely JST-style connector."
    assert "White shrouded" in entries["Evidence"]["secondary"]
    assert "No scale reference" in entries["Uncertainty"]["secondary"]
    assert "Compare the pitch" in entries["Recommended Next Step"]["secondary"]
    assert entries["Provider Output"]["secondary"] == "Visual Evidence Only"
    assert entries["Verified Outcome"]["secondary"] == "No"
    assert entries["Action Executed"]["secondary"] == "No"
    assert station_actions["Retake"]["sendText"] == "retake the camera still"
    assert station_actions["Analyze Again"]["sendText"] == "reanalyze this camera still"
    assert station_actions["Discard"]["enabled"] is False
    assert station_actions["Attach To Task"]["enabled"] is False
    assert station_actions["Open Trace"]["localAction"] == "open_route_inspector"
    assert _contains_forbidden_payload({"station": station, "actions": bridge.ghostActionStrip}) is False


def test_c4_ghost_open_in_deck_handoff_reveals_camera_panel_without_backend_side_effects(temp_config) -> None:
    bridge = UiBridge(temp_config)
    _apply_answer_snapshot(bridge)
    action = _actions_by_label(bridge.ghostActionStrip)["Open In Deck"]

    bridge.performLocalSurfaceAction(action["localAction"])

    visible_ids = {panel["panelId"] for panel in bridge.deckPanels}
    hidden_ids = {panel["panelId"] for panel in bridge.hiddenDeckPanels}
    assert bridge.mode_value == "deck"
    assert "camera-visual-context" in visible_ids
    assert "camera-visual-context" not in hidden_ids


def test_c4_expired_and_cleanup_warning_lifecycle_is_not_shown_as_usable_or_saved(temp_config) -> None:
    expired_bridge = UiBridge(temp_config)
    _apply_answer_snapshot(
        expired_bridge,
        status=_camera_status(
            lastVisionStatus="camera_vision_artifact_expired",
            lastArtifactFresh=False,
            lastArtifactExpired=True,
            artifactExpired=True,
            artifactReadable=False,
            artifactExists=False,
            cloudUploadPerformed=False,
            cloudAnalysisPerformed=False,
        ),
        request=_camera_request(
            stage="camera_vision_artifact_expired",
            result_state="camera_vision_artifact_expired",
        ),
    )
    expired_station = _camera_station(expired_bridge)
    expired_visual = expired_station["visualArtifact"]
    expired_entries = _entries_by_primary(expired_station)
    expired_actions = _actions_by_label(expired_station["actions"])

    assert expired_visual["artifactState"] == "expired"
    assert expired_visual["previewKind"] == "expired_placeholder"
    assert expired_visual["safePreviewRef"] == ""
    assert expired_entries["Usable For Analysis"]["secondary"] == "No"
    assert expired_entries["Saved"]["secondary"] == "No"
    assert expired_actions["Analyze Again"]["enabled"] is False

    cleanup_bridge = UiBridge(temp_config)
    _apply_answer_snapshot(
        cleanup_bridge,
        status=_camera_status(
            lastVisionStatus="camera_answer_ready",
            cleanupPending=True,
            cleanupFailed=True,
        ),
    )
    cleanup_station = _camera_station(cleanup_bridge)
    cleanup_entries = _entries_by_primary(cleanup_station)
    cleanup_chip_values = {chip["label"]: chip["value"] for chip in cleanup_station["chips"]}

    assert cleanup_chip_values["Artifact"] == "Cleanup Warning"
    assert cleanup_entries["Cleanup"]["secondary"] == "Warning"
    assert cleanup_station["invalidations"][0]["label"] == "Cleanup"


def test_c4_deck_state_redacts_raw_payloads_provider_bodies_and_temp_paths(temp_config) -> None:
    bridge = UiBridge(temp_config)
    dirty_answer = {
        "image_url": "data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD",
        "provider_request_body": {"image_url": "SECRET_IMAGE_PAYLOAD"},
        "raw_image": "SECRET_IMAGE_PAYLOAD",
        "api_key": "sk-test-secret",
        "file_path": "C:\\Temp\\camera-frame.jpg",
        "path": "C:\\Temp\\camera-frame.jpg",
    }
    dirty_status = _camera_status(
        image_url="data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD",
        provider_request_body={"raw_image": "SECRET_IMAGE_PAYLOAD"},
        api_key="sk-test-secret",
        file_path="C:\\Temp\\camera-frame.jpg",
        path="C:\\Temp\\camera-frame.jpg",
    )

    _apply_answer_snapshot(bridge, status=dirty_status, answer=dirty_answer)

    ui_payload = {
        "ghostPrimaryCard": bridge.ghostPrimaryCard,
        "ghostActionStrip": bridge.ghostActionStrip,
        "requestComposer": bridge.requestComposer,
        "routeInspector": bridge.routeInspector,
        "deckPanels": bridge.deckPanels,
        "deckPanelCatalog": bridge.deckPanelCatalog,
    }
    assert _contains_forbidden_payload(ui_payload) is False


class CountingCaptureProvider(CameraCaptureProvider):
    provider_kind = "mock"

    def __init__(self) -> None:
        self.capture_attempted = False
        self.hardware_access_attempted = False
        self.devices_checked = 0

    def list_devices(self):  # noqa: ANN201
        self.devices_checked += 1
        return []

    def capture_still(self, request: CameraCaptureRequest):  # noqa: ANN201
        del request
        self.capture_attempted = True
        raise AssertionError("Deck rendering must not trigger camera capture")


def test_c4_deck_render_reads_do_not_trigger_capture_analysis_upload_save_or_discard(temp_project_root) -> None:
    app_config = load_config(project_root=temp_project_root, env={})
    camera = app_config.camera_awareness
    camera.enabled = True
    camera.privacy.confirm_before_capture = True
    camera.capture.provider = "mock"
    camera.vision.provider = "mock"
    capture_provider = CountingCaptureProvider()
    vision_provider = MockVisionAnalysisProvider(camera)
    service = CameraAwarenessSubsystem(
        camera,
        capture_provider=capture_provider,
        vision_provider=vision_provider,
    )

    snapshot = service.status_snapshot()
    bridge = UiBridge(app_config)
    bridge.apply_snapshot(
        {
            "status": {"camera_awareness": snapshot},
            "active_request_state": _camera_request(
                stage="camera_permission_required",
                result_state="camera_permission_required",
            ),
        }
    )
    _ = bridge.deckPanels
    _ = bridge.deckPanelCatalog
    bridge.performLocalSurfaceAction("open_panel:camera-visual-context")

    assert capture_provider.capture_attempted is False
    assert capture_provider.hardware_access_attempted is False
    assert capture_provider.devices_checked == 0
    assert vision_provider.network_access_attempted is False
    assert service.status_snapshot()["cloudUploadPerformed"] is False
    assert service.status_snapshot()["rawImageIncluded"] is False


def test_c4_deck_labels_mock_local_and_cloud_provenance_distinctly(temp_config) -> None:
    mock_bridge = UiBridge(temp_config)
    _apply_answer_snapshot(
        mock_bridge,
        status=_camera_status(
            providerKind="mock",
            captureProviderKind="mock",
            visionProviderKind="mock",
            mockMode=True,
            mockCapture=True,
            realCameraUsed=False,
            cloudUploadPerformed=False,
            cloudAnalysisPerformed=False,
            artifactFormat="mock",
            artifactSourceProvenance="camera_mock",
        ),
        answer={
            "mock_answer": True,
            "provider_kind": "mock",
            "cloud_analysis_performed": False,
            "cloud_upload_performed": False,
            "provenance": {"source": "camera_mock"},
        },
    )
    mock_entries = _entries_by_primary(_camera_station(mock_bridge))
    assert mock_entries["Source"]["secondary"] == "Mock Camera"
    assert mock_entries["Analysis"]["secondary"] == "Mock Analysis"
    assert mock_entries["Capture"]["secondary"] == "Mock Capture"

    cloud_bridge = UiBridge(temp_config)
    _apply_answer_snapshot(cloud_bridge)
    cloud_entries = _entries_by_primary(_camera_station(cloud_bridge))
    assert cloud_entries["Source"]["secondary"] == "Local Camera Still"
    assert cloud_entries["Analysis"]["secondary"] == "Cloud Vision"
    assert cloud_entries["Cloud Upload"]["secondary"] == "Yes"
