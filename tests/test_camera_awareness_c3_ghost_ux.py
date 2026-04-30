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
    "image_base64",
    "image_bytes",
    "image_url",
    "provider_request",
    "provider_request_body",
    "raw_image",
}
FORBIDDEN_UI_TOKENS = (
    "data:image",
    "base64,",
    "SECRET_IMAGE_PAYLOAD",
    "sk-test-secret",
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


def _camera_request(
    *,
    stage: str = "camera_permission_required",
    result_state: str | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "request_stage": stage,
        "result_state": result_state or stage,
        "selected_source_route": "camera_awareness",
    }
    return {
        "request_id": "camera-c3-request",
        "family": "camera_awareness",
        "subject": "camera still",
        "request_type": "camera_awareness_request",
        "query_shape": "camera_awareness_request",
        "parameters": parameters,
    }


def _camera_status(**overrides: Any) -> dict[str, Any]:
    status: dict[str, Any] = {
        "enabled": True,
        "route_family": "camera_awareness",
        "providerKind": "mock",
        "captureProviderKind": "mock",
        "visionProviderKind": "mock",
        "configuredCaptureProvider": "mock",
        "configuredVisionProvider": "mock",
        "mockMode": True,
        "mockCapture": False,
        "realCameraUsed": False,
        "cloudUploadPerformed": False,
        "cloudAnalysisPerformed": False,
        "rawImageIncluded": False,
        "storageMode": "ephemeral",
        "permissionState": "required",
        "lastArtifactFresh": False,
        "lastArtifactExpired": False,
        "artifactExpired": False,
        "artifactReadable": False,
        "artifactExists": False,
        "artifactFormat": "unknown",
        "artifactSourceProvenance": "camera_unavailable",
        "cleanupPending": False,
        "cleanupFailed": False,
        "visionProviderAvailable": True,
    }
    status.update(overrides)
    return status


def _answer_message(answer: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "answer_text": "Likely a JST-style connector.",
        "concise_answer": "Likely JST-style connector.",
        "confidence": "medium",
        "evidence_summary": "White shrouded body with visible pins.",
        "uncertainty_reasons": ["No scale reference is visible."],
        "safety_notes": ["Visual analysis only; not command authority."],
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
        "message_id": "assistant-camera-c3",
        "role": "assistant",
        "content": payload["answer_text"],
        "created_at": "2026-04-30T18:00:00Z",
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


def test_c3_camera_permission_required_maps_to_compact_ghost_card(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_snapshot(
        {
            "status": {"camera_awareness": _camera_status(enabled=True)},
            "active_request_state": _camera_request(),
        }
    )

    card = bridge.ghostPrimaryCard
    actions = {entry["label"]: entry for entry in bridge.ghostActionStrip}

    assert card["cameraGhost"]["state"] == "camera_permission_required"
    assert card["routeLabel"] == "Camera Awareness"
    assert card["title"] == "Camera Still Needed"
    assert "single still" in card["body"].lower()
    assert card["cameraGhost"]["storageMode"] == "ephemeral"
    assert card["cameraGhost"]["rawImageIncluded"] is False
    assert actions["Allow Once"]["sendText"] == "allow camera once"
    assert actions["Dismiss"]["localAction"] == "dismiss_camera_card"
    assert "Analyze Once" not in actions


def test_c3_cloud_confirmation_is_distinct_from_capture_permission(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_snapshot(
        {
            "status": {
                "camera_awareness": _camera_status(
                    providerKind="local",
                    captureProviderKind="local",
                    visionProviderKind="openai",
                    mockMode=False,
                    mockCapture=False,
                    permissionState="granted",
                    cloudAnalysisAllowed=True,
                    cloudAnalysisPerformed=False,
                    lastArtifactFresh=True,
                    artifactReadable=True,
                    artifactExists=True,
                    artifactFormat="jpg",
                    artifactSourceProvenance="camera_local",
                    lastVisionStatus="camera_vision_permission_required",
                    lastVisionErrorCode="camera_vision_confirmation_required",
                )
            },
            "active_request_state": _camera_request(
                stage="camera_vision_permission_required",
                result_state="camera_vision_permission_required",
            ),
        }
    )

    card = bridge.ghostPrimaryCard
    actions = {entry["label"]: entry for entry in bridge.ghostActionStrip}

    assert card["cameraGhost"]["state"] == "camera_confirmation_required"
    assert card["title"] == "Vision Analysis Needs Confirmation"
    assert "cloud vision" in card["body"].lower()
    assert actions["Analyze Once"]["sendText"] == "analyze this camera still once"
    assert "Allow Once" not in actions
    assert card["cameraGhost"]["cloudUploadPerformed"] is False
    assert card["cameraGhost"]["storageMode"] == "ephemeral"


def test_c3_answer_card_shows_truthful_source_confidence_and_boundaries(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_snapshot(
        {
            "history": [_answer_message()],
            "status": {
                "camera_awareness": _camera_status(
                    providerKind="local",
                    captureProviderKind="local",
                    visionProviderKind="openai",
                    mockMode=False,
                    mockCapture=False,
                    realCameraUsed=True,
                    cloudAnalysisAllowed=True,
                    cloudAnalysisPerformed=True,
                    cloudUploadPerformed=True,
                    lastVisionStatus="camera_answer_ready",
                    lastVisionConfidence="medium",
                    lastArtifactFresh=True,
                    artifactExists=True,
                    artifactReadable=True,
                    artifactExpired=False,
                    artifactFormat="jpg",
                    artifactSourceProvenance="camera_local",
                    storageMode="ephemeral",
                )
            },
            "active_request_state": _camera_request(
                stage="camera_answer_ready",
                result_state="camera_answer_ready",
            ),
        }
    )

    card = bridge.ghostPrimaryCard
    actions = {entry["label"]: entry for entry in bridge.ghostActionStrip}
    provenance = {entry["label"]: entry["value"] for entry in card["provenance"]}

    assert card["cameraGhost"]["state"] == "camera_answer_ready"
    assert card["title"] == "Camera Answer Ready"
    assert card["body"] == "Likely JST-style connector."
    assert provenance["Source"] == "Local Camera Still"
    assert provenance["Confidence"] == "Medium"
    assert provenance["Storage"] == "Ephemeral"
    assert provenance["Analysis"] == "Cloud Vision"
    assert "No scale reference" in card["cameraGhost"]["uncertaintySummary"]
    assert "Visual analysis only" in card["cameraGhost"]["safetyNote"]
    assert card["cameraGhost"]["realCameraUsed"] is True
    assert card["cameraGhost"]["cloudUploadPerformed"] is True
    assert card["cameraGhost"]["rawImageIncluded"] is False
    assert actions["Retake"]["sendText"] == "retake the camera still"
    assert actions["Open In Deck"]["enabled"] is True
    assert actions["Open In Deck"]["localAction"] == "open_panel:camera-visual-context"


def test_c3_mock_answer_is_not_displayed_as_real_analysis(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_snapshot(
        {
            "history": [
                _answer_message(
                    {
                        "concise_answer": "Mock camera fixture: resistor.",
                        "answer_text": "Mock camera fixture: resistor.",
                        "mock_answer": True,
                        "provider_kind": "mock",
                        "cloud_analysis_performed": False,
                        "cloud_upload_performed": False,
                        "provenance": {"source": "camera_mock"},
                    }
                )
            ],
            "status": {
                "camera_awareness": _camera_status(
                    mockCapture=True,
                    mockMode=True,
                    realCameraUsed=False,
                    cloudUploadPerformed=False,
                    cloudAnalysisPerformed=False,
                    lastVisionStatus="camera_answer_ready",
                    lastVisionConfidence="medium",
                    lastArtifactFresh=True,
                    artifactSourceProvenance="camera_mock",
                    artifactFormat="mock",
                )
            },
            "active_request_state": _camera_request(
                stage="camera_answer_ready",
                result_state="camera_answer_ready",
            ),
        }
    )

    card = bridge.ghostPrimaryCard
    provenance = {entry["label"]: entry["value"] for entry in card["provenance"]}

    assert card["title"] == "Mock Camera Result"
    assert provenance["Source"] == "Mock Camera"
    assert provenance["Analysis"] == "Mock Analysis"
    assert card["cameraGhost"]["mockAnalysis"] is True
    assert card["cameraGhost"]["realCameraUsed"] is False
    assert card["cameraGhost"]["cloudUploadPerformed"] is False


def test_c3_expired_cleanup_and_provider_unavailable_states_are_truthful(temp_config) -> None:
    cases = [
        (
            _camera_status(
                lastVisionStatus="camera_vision_artifact_expired",
                lastArtifactExpired=True,
                artifactExpired=True,
                lastArtifactFresh=False,
                artifactSourceProvenance="camera_local",
            ),
            "camera_artifact_expired",
            "Camera Still Expired",
        ),
        (
            _camera_status(
                lastVisionStatus="camera_answer_ready",
                lastArtifactFresh=True,
                cleanupPending=True,
                cleanupFailed=True,
                artifactSourceProvenance="camera_local",
            ),
            "camera_cleanup_warning",
            "Camera Cleanup Warning",
        ),
        (
            _camera_status(
                visionProviderKind="unavailable",
                visionProviderAvailable=False,
                visionUnavailableReason="api_key_missing",
                lastVisionStatus="camera_vision_provider_unavailable",
            ),
            "camera_provider_unavailable",
            "Vision Provider Unavailable",
        ),
    ]

    for status, expected_state, expected_title in cases:
        bridge = UiBridge(temp_config)
        bridge.apply_snapshot(
            {
                "status": {"camera_awareness": status},
                "active_request_state": _camera_request(
                    stage=status.get("lastVisionStatus") or expected_state,
                    result_state=status.get("lastVisionStatus") or expected_state,
                ),
            }
        )
        assert bridge.ghostPrimaryCard["cameraGhost"]["state"] == expected_state
        assert bridge.ghostPrimaryCard["title"] == expected_title


def test_c3_capture_and_analysis_status_states_stay_low_density(temp_config) -> None:
    cases = [
        ("camera_disabled", _camera_status(enabled=False), "Camera Awareness Disabled"),
        ("camera_capture_requested", _camera_status(permissionState="granted"), "Camera Capture Requested"),
        ("camera_capturing", _camera_status(permissionState="granted"), "Capturing Camera Still"),
        (
            "camera_captured",
            _camera_status(
                permissionState="granted",
                lastArtifactFresh=True,
                artifactExists=True,
                artifactReadable=True,
                artifactSourceProvenance="camera_local",
            ),
            "Camera Still Captured",
        ),
        ("camera_analyzing", _camera_status(permissionState="granted"), "Analyzing Camera Still"),
    ]

    for state, status, title in cases:
        bridge = UiBridge(temp_config)
        bridge.apply_snapshot(
            {
                "status": {"camera_awareness": status},
                "active_request_state": _camera_request(stage=state, result_state=state),
            }
        )

        card = bridge.ghostPrimaryCard
        assert card["cameraGhost"]["state"] == state
        assert card["title"] == title
        assert len(card["body"]) < 180
        assert card["cameraGhost"]["rawImageIncluded"] is False


def test_c3_visual_source_labels_do_not_impersonate_local_camera(temp_config) -> None:
    cases = [
        ("uploaded_image", "Uploaded Image"),
        ("screen_context", "Screen Context"),
        ("clipboard", "Clipboard"),
        ("file", "File"),
    ]

    for source, expected_label in cases:
        bridge = UiBridge(temp_config)
        bridge.apply_snapshot(
            {
                "history": [
                    _answer_message(
                        {
                            "provenance": {"source": source},
                            "mock_answer": False,
                            "provider_kind": "mock",
                            "cloud_analysis_performed": False,
                            "cloud_upload_performed": False,
                        }
                    )
                ],
                "status": {
                    "camera_awareness": _camera_status(
                        permissionState="granted",
                        lastVisionStatus="camera_answer_ready",
                        lastVisionConfidence="medium",
                        lastArtifactFresh=True,
                        artifactSourceProvenance=source,
                    )
                },
                "active_request_state": _camera_request(
                    stage="camera_answer_ready",
                    result_state="camera_answer_ready",
                ),
            }
        )

        provenance = {
            entry["label"]: entry["value"]
            for entry in bridge.ghostPrimaryCard["provenance"]
        }
        assert provenance["Source"] == expected_label
        assert provenance["Source"] != "Local Camera Still"


def test_c3_ui_state_recursively_redacts_raw_camera_payloads(temp_config) -> None:
    bridge = UiBridge(temp_config)
    dirty_answer = {
        "image_url": "data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD",
        "provider_request_body": {"image_url": "SECRET_IMAGE_PAYLOAD"},
        "raw_image": "SECRET_IMAGE_PAYLOAD",
        "api_key": "sk-test-secret",
    }

    bridge.apply_snapshot(
        {
            "history": [_answer_message(dirty_answer)],
            "status": {
                "camera_awareness": _camera_status(
                    lastVisionStatus="camera_answer_ready",
                    lastVisionConfidence="medium",
                    lastArtifactFresh=True,
                    artifactSourceProvenance="camera_local",
                    image_url="data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD",
                    provider_request_body={"raw_image": "SECRET_IMAGE_PAYLOAD"},
                    api_key="sk-test-secret",
                )
            },
            "active_request_state": _camera_request(
                stage="camera_answer_ready",
                result_state="camera_answer_ready",
            ),
        }
    )

    ui_payload = {
        "ghostPrimaryCard": bridge.ghostPrimaryCard,
        "ghostActionStrip": bridge.ghostActionStrip,
        "requestComposer": bridge.requestComposer,
        "routeInspector": bridge.routeInspector,
        "contextCards": bridge.contextCards,
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
        raise AssertionError("UI rendering must not trigger camera capture")


def test_c3_bridge_render_reads_do_not_trigger_capture_or_analysis(temp_project_root) -> None:
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
            "active_request_state": _camera_request(),
        }
    )
    _ = bridge.ghostPrimaryCard
    _ = bridge.ghostActionStrip
    _ = bridge.requestComposer
    bridge.performLocalSurfaceAction("dismiss_camera_card")

    assert capture_provider.capture_attempted is False
    assert capture_provider.hardware_access_attempted is False
    assert capture_provider.devices_checked == 0
    assert vision_provider.network_access_attempted is False
    assert service.status_snapshot()["cloudUploadPerformed"] is False
