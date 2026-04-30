from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CameraAnalysisMode,
    CameraAwarenessResultState,
    CameraAwarenessSubsystem,
    CameraFrameArtifact,
    CameraStorageMode,
    CameraTelemetryEmitter,
    CameraVisionQuestion,
    OpenAIVisionAnalysisProvider,
    UnavailableVisionAnalysisProvider,
    build_camera_awareness_subsystem,
    utc_now,
)
from stormhelm.core.events import EventBuffer
from stormhelm.core.providers.base import ProviderTurnResult


FORBIDDEN_PAYLOAD_TOKENS = (
    "data:image",
    "base64,",
    "SECRET_IMAGE_PAYLOAD",
)
FORBIDDEN_PAYLOAD_KEYS = {
    "image_url",
    "image_bytes",
    "image_base64",
    "raw_image",
    "provider_request_body",
    "provider_request",
}


def _camera_app_config(
    temp_project_root: Path,
    *,
    provider: str = "openai",
    allow_cloud_global: bool = True,
    allow_cloud_vision: bool = True,
    require_confirmation: bool = True,
):
    app_config = load_config(project_root=temp_project_root, env={})
    camera = app_config.camera_awareness
    camera.enabled = True
    camera.privacy.confirm_before_capture = False
    camera.capture.provider = "mock"
    camera.vision.provider = provider
    camera.vision.model = "gpt-vision-test"
    camera.vision.detail = "low"
    camera.vision.max_image_bytes = 4096
    camera.vision.require_confirmation_for_cloud = require_confirmation
    camera.allow_cloud_vision = allow_cloud_global
    camera.vision.allow_cloud_vision = allow_cloud_vision
    app_config.openai.enabled = True
    app_config.openai.api_key = "test-key"
    app_config.openai.model = "gpt-vision-test"
    app_config.openai.timeout_seconds = 3
    return app_config


def _store_artifact(
    service: CameraAwarenessSubsystem,
    tmp_path: Path,
    *,
    payload: bytes = b"fake-jpeg-bytes",
    image_format: str = "jpg",
    expires_in_seconds: int = 60,
) -> CameraFrameArtifact:
    path = tmp_path / f"camera-artifact-{len(list(tmp_path.glob('camera-artifact-*')))}.{image_format}"
    path.write_bytes(payload)
    created_at = utc_now()
    artifact = CameraFrameArtifact(
        capture_result_id="capture-c21",
        storage_mode=CameraStorageMode.EPHEMERAL,
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=expires_in_seconds),
        file_path=str(path),
        width=32,
        height=24,
        image_format=image_format,
        mock_artifact=False,
        fixture_name="local_capture",
        source_provenance="camera_local",
    )
    service.artifacts.add(artifact)
    return artifact


class FakeResponsesProvider:
    def __init__(self, result: ProviderTurnResult | None = None, exc: Exception | None = None) -> None:
        self.result = result or ProviderTurnResult(
            response_id="resp-c21",
            output_text="Likely a connector.",
            raw_response={
                "camera_vision": {
                    "answer_text": "This looks like a connector.",
                    "concise_answer": "Likely connector.",
                    "confidence": "medium",
                    "evidence_summary": "Visible shrouded body and pins.",
                    "uncertainty_reasons": ["No scale reference is visible."],
                    "safety_notes": ["Visual analysis only; not command authority."],
                    "recommended_user_action": "Compare pitch before ordering.",
                }
            },
        )
        self.exc = exc
        self.calls = 0
        self.last_input_items: Any = None

    async def generate(
        self,
        *,
        instructions: str,
        input_items: str | list[dict[str, Any]],
        previous_response_id: str | None,
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ProviderTurnResult:
        del instructions, previous_response_id, tools, model, max_output_tokens
        self.calls += 1
        self.last_input_items = input_items
        if self.exc is not None:
            raise self.exc
        return self.result


@dataclass(slots=True)
class FakeProviderError(Exception):
    status_code: int
    message: str

    def __str__(self) -> str:
        return self.message


def _openai_service(
    app_config,
    fake_client: FakeResponsesProvider,
    *,
    events: EventBuffer | None = None,
) -> CameraAwarenessSubsystem:
    provider = OpenAIVisionAnalysisProvider(
        app_config.camera_awareness,
        openai_config=app_config.openai,
        responses_provider=fake_client,
    )
    return CameraAwarenessSubsystem(
        app_config.camera_awareness,
        events=events,
        vision_provider=provider,
    )


def _contains_forbidden_payload(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_PAYLOAD_KEYS:
                return True
            if _contains_forbidden_payload(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_contains_forbidden_payload(item) for item in value)
    text = str(value).lower()
    return any(token.lower() in text for token in FORBIDDEN_PAYLOAD_TOKENS)


@pytest.mark.parametrize(
    (
        "allow_cloud_global",
        "allow_cloud_vision",
        "require_confirmation",
        "confirmed",
        "expected_provider_calls",
        "expected_state",
        "expected_error",
    ),
    [
        (
            False,
            True,
            False,
            True,
            0,
            CameraAwarenessResultState.CAMERA_CLOUD_ANALYSIS_DISABLED,
            "camera_cloud_analysis_disabled",
        ),
        (
            True,
            False,
            False,
            True,
            0,
            CameraAwarenessResultState.CAMERA_CLOUD_ANALYSIS_DISABLED,
            "camera_cloud_analysis_disabled",
        ),
        (
            True,
            True,
            True,
            None,
            0,
            CameraAwarenessResultState.CAMERA_VISION_PERMISSION_REQUIRED,
            "camera_vision_confirmation_required",
        ),
        (
            True,
            True,
            True,
            False,
            0,
            CameraAwarenessResultState.CAMERA_VISION_PERMISSION_REQUIRED,
            "camera_vision_confirmation_required",
        ),
        (
            True,
            True,
            True,
            True,
            1,
            CameraAwarenessResultState.CAMERA_ANSWER_READY,
            None,
        ),
        (
            True,
            True,
            False,
            None,
            1,
            CameraAwarenessResultState.CAMERA_ANSWER_READY,
            None,
        ),
    ],
)
def test_c21_cloud_policy_matrix_blocks_before_provider_request_construction(
    temp_project_root,
    tmp_path,
    allow_cloud_global,
    allow_cloud_vision,
    require_confirmation,
    confirmed,
    expected_provider_calls,
    expected_state,
    expected_error,
) -> None:
    app_config = _camera_app_config(
        temp_project_root,
        allow_cloud_global=allow_cloud_global,
        allow_cloud_vision=allow_cloud_vision,
        require_confirmation=require_confirmation,
    )
    fake_client = FakeResponsesProvider()
    service = _openai_service(app_config, fake_client)
    artifact = _store_artifact(service, tmp_path)

    flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=artifact.image_artifact_id,
        user_question="What is this part?",
        user_request_id="c21-policy-matrix",
        cloud_analysis_confirmed=confirmed,
    )

    assert flow.result_state == expected_state
    assert flow.vision_answer.error_code == expected_error
    assert fake_client.calls == expected_provider_calls
    if expected_provider_calls == 0:
        assert service.vision_provider.network_access_attempted is False
        assert getattr(service.vision_provider, "last_preparation", None) is None
        assert getattr(service.vision_provider, "last_request_metadata", {}) == {}
        assert flow.trace.cloud_upload_performed is False
        assert service.status_snapshot()["cloudAnalysisPerformed"] is False
    else:
        assert service.vision_provider.network_access_attempted is True
        assert getattr(service.vision_provider, "last_preparation", None) is not None
        assert flow.trace.cloud_upload_performed is True


def test_c21_capture_permission_does_not_imply_cloud_analysis_permission(
    temp_project_root,
) -> None:
    app_config = _camera_app_config(
        temp_project_root,
        allow_cloud_global=False,
        allow_cloud_vision=False,
    )
    fake_client = FakeResponsesProvider()
    service = _openai_service(app_config, fake_client)

    flow = service.answer_mock_question(
        user_question="What is this I am holding?",
        user_request_id="c21-capture-not-cloud",
        user_confirmed=True,
        cloud_analysis_confirmed=True,
    )

    assert flow.capture_result.status.value == "captured"
    assert flow.result_state == CameraAwarenessResultState.CAMERA_CLOUD_ANALYSIS_DISABLED
    assert flow.vision_answer.error_code == "camera_cloud_analysis_disabled"
    assert fake_client.calls == 0
    assert service.vision_provider.network_access_attempted is False
    assert service.status_snapshot()["cloudAnalysisPerformed"] is False


def test_c21_mock_and_unavailable_providers_do_not_consume_cloud_permission(
    temp_project_root,
    tmp_path,
) -> None:
    mock_config = _camera_app_config(
        temp_project_root,
        provider="mock",
        allow_cloud_global=False,
        allow_cloud_vision=False,
    )
    mock_service = build_camera_awareness_subsystem(mock_config.camera_awareness)
    mock_artifact = _store_artifact(mock_service, tmp_path)

    mock_flow = mock_service.analyze_artifact_with_selected_provider(
        image_artifact_id=mock_artifact.image_artifact_id,
        user_question="What is this?",
        user_request_id="c21-mock-provider",
    )

    assert mock_flow.result_state == CameraAwarenessResultState.CAMERA_ANSWER_READY
    assert mock_flow.vision_answer.mock_answer is True
    assert mock_flow.vision_answer.cloud_upload_performed is False

    unavailable_config = _camera_app_config(
        temp_project_root,
        provider="does-not-exist",
        allow_cloud_global=True,
        allow_cloud_vision=True,
        require_confirmation=False,
    )
    unavailable_service = build_camera_awareness_subsystem(unavailable_config.camera_awareness)
    unavailable_artifact = _store_artifact(unavailable_service, tmp_path)

    unavailable_flow = unavailable_service.analyze_artifact_with_selected_provider(
        image_artifact_id=unavailable_artifact.image_artifact_id,
        user_question="What is this?",
        user_request_id="c21-unavailable-provider",
    )

    assert unavailable_service.vision_provider.provider_kind == "unavailable"
    assert unavailable_flow.result_state == CameraAwarenessResultState.CAMERA_ANALYSIS_FAILED
    assert unavailable_flow.vision_answer.error_code == "unknown_vision_provider"
    assert unavailable_flow.vision_answer.cloud_upload_performed is False


def test_c21_status_selection_and_validation_do_not_call_network_or_encode_image(
    temp_project_root,
    tmp_path,
) -> None:
    app_config = _camera_app_config(temp_project_root)
    fake_client = FakeResponsesProvider(exc=AssertionError("generate must not be called"))
    service = _openai_service(app_config, fake_client)
    artifact = _store_artifact(service, tmp_path)

    snapshot = service.status_snapshot()
    readiness = service.validate_artifact_for_analysis(artifact.image_artifact_id)
    availability = service.vision_provider.get_availability()

    assert snapshot["visionProviderKind"] == "openai"
    assert snapshot["visionProviderAvailable"] is True
    assert readiness.ready is True
    assert availability.available is True
    assert fake_client.calls == 0
    assert service.vision_provider.network_access_attempted is False
    assert getattr(service.vision_provider, "last_preparation", None) is None
    assert getattr(service.vision_provider, "last_request_metadata", {}) == {}


def test_c21_provider_response_payloads_are_sanitized_from_status_events_and_trace(
    temp_project_root,
    tmp_path,
) -> None:
    app_config = _camera_app_config(
        temp_project_root,
        allow_cloud_global=True,
        allow_cloud_vision=True,
        require_confirmation=False,
    )
    leaked_payload = "data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD"
    fake_client = FakeResponsesProvider(
        result=ProviderTurnResult(
            response_id="resp-leaky",
            output_text=leaked_payload,
            raw_response={
                "camera_vision": {
                    "answer_text": f"The visible object is a connector. {leaked_payload}",
                    "concise_answer": f"Connector {leaked_payload}",
                    "detailed_answer": f"Do not echo {leaked_payload}",
                    "confidence": "high",
                    "evidence_summary": f"Provider attempted image_url echo {leaked_payload}",
                    "uncertainty_reasons": [f"raw image_bytes echo {leaked_payload}"],
                    "safety_notes": [f"provider_request_body echo {leaked_payload}"],
                    "recommended_user_action": f"Compare pitch. {leaked_payload}",
                    "suggested_next_capture": f"Retake. {leaked_payload}",
                    "action_executed": True,
                    "verified": True,
                    "trust_approved": True,
                },
                "provider_request_body": {"image_url": leaked_payload},
            },
        )
    )
    events = EventBuffer(capacity=64)
    service = _openai_service(app_config, fake_client, events=events)
    artifact = _store_artifact(service, tmp_path)

    flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=artifact.image_artifact_id,
        user_question="What is this?",
        user_request_id="c21-privacy",
        session_id="session-c21",
        cloud_analysis_confirmed=True,
    )

    assert flow.result_state == CameraAwarenessResultState.CAMERA_ANSWER_READY
    assert flow.vision_answer.raw_image_included is False
    assert flow.vision_answer.cloud_upload_performed is True
    assert flow.vision_answer.cloud_analysis_performed is True
    assert not _contains_forbidden_payload(flow.vision_answer.to_dict())
    assert not _contains_forbidden_payload(flow.trace.to_dict())
    assert not _contains_forbidden_payload(flow.to_dict())
    assert not _contains_forbidden_payload(service.status_snapshot())
    assert all(
        not _contains_forbidden_payload(event["payload"])
        for event in events.recent(limit=64)
    )
    assert fake_client.last_input_items[0]["content"][1]["image_url"].startswith(
        "data:image/jpeg;base64,"
    )


def test_c21_telemetry_recursively_redacts_raw_image_payloads() -> None:
    events = EventBuffer(capacity=8)
    emitter = CameraTelemetryEmitter(events)

    emitter.emit(
        "camera.test",
        "Camera telemetry redaction test.",
        payload={
            "safe": {"artifact_id": "artifact-c21"},
            "nested": {
                "image_url": "data:image/png;base64,SECRET_IMAGE_PAYLOAD",
                "items": [
                    {"provider_request_body": {"image_bytes": "SECRET_IMAGE_PAYLOAD"}},
                    "prefix data:image/png;base64,SECRET_IMAGE_PAYLOAD suffix",
                ],
            },
        },
    )

    payload = events.recent(limit=1)[0]["payload"]
    assert payload["safe"]["artifact_id"] == "artifact-c21"
    assert not _contains_forbidden_payload(payload)
    assert payload["raw_image_included"] is False
    assert payload["cloud_upload_performed"] is False


def test_c21_invalid_artifacts_block_before_provider_request_construction(
    temp_project_root,
    tmp_path,
    monkeypatch,
) -> None:
    app_config = _camera_app_config(
        temp_project_root,
        allow_cloud_global=True,
        allow_cloud_vision=True,
        require_confirmation=False,
    )
    fake_client = FakeResponsesProvider()
    service = _openai_service(app_config, fake_client)
    artifact = _store_artifact(service, tmp_path)
    original_open = Path.open

    def locked_open(path: Path, *args, **kwargs):
        if str(path) == artifact.file_path:
            raise PermissionError("camera test file is locked")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked_open)

    flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=artifact.image_artifact_id,
        user_question="What is this?",
        user_request_id="c21-unreadable",
        cloud_analysis_confirmed=True,
    )

    assert flow.result_state == CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_UNREADABLE
    assert flow.vision_answer.error_code == "camera_artifact_unreadable"
    assert fake_client.calls == 0
    assert service.vision_provider.network_access_attempted is False
    assert getattr(service.vision_provider, "last_preparation", None) is None


def test_c21_cleanup_failure_is_truthful_and_retry_is_idempotent(
    temp_project_root,
    tmp_path,
    monkeypatch,
) -> None:
    app_config = _camera_app_config(temp_project_root, provider="mock")
    service = build_camera_awareness_subsystem(app_config.camera_awareness)
    artifact = _store_artifact(service, tmp_path)
    path = Path(artifact.file_path)
    unlink_calls = {"count": 0, "fail": True}
    original_unlink = Path.unlink

    def flaky_unlink(target: Path, *args, **kwargs):
        if target == path and unlink_calls["fail"]:
            unlink_calls["count"] += 1
            raise PermissionError("camera test file is locked")
        return original_unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    assert service.expire_artifact(artifact.image_artifact_id) is True
    cleanup = service.artifacts.last_cleanup_result
    assert cleanup is not None
    assert cleanup.cleanup_attempted is True
    assert cleanup.cleanup_succeeded is False
    assert cleanup.cleanup_failed is True
    assert cleanup.cleanup_pending is True
    assert cleanup.file_exists_after is True
    assert path.exists()
    snapshot = service.status_snapshot()
    assert snapshot["cleanupFailed"] is True
    assert snapshot["cleanupPending"] is True

    unlink_calls["fail"] = False
    retry = service.retry_artifact_cleanup(artifact.image_artifact_id)

    assert retry is not None
    assert retry.cleanup_attempted is True
    assert retry.cleanup_succeeded is True
    assert retry.cleanup_failed is False
    assert retry.cleanup_pending is False
    assert retry.file_exists_after is False
    assert not path.exists()

    second_retry = service.retry_artifact_cleanup(artifact.image_artifact_id)
    assert second_retry is not None
    assert second_retry.cleanup_attempted is False
    assert second_retry.cleanup_succeeded is True
    assert second_retry.cleanup_failed is False


def test_c21_provider_failures_are_typed_without_raw_error_echo(
    temp_project_root,
    tmp_path,
) -> None:
    app_config = _camera_app_config(
        temp_project_root,
        allow_cloud_global=True,
        allow_cloud_vision=True,
        require_confirmation=False,
    )
    question = CameraVisionQuestion(
        image_artifact_id="artifact-c21",
        user_question="What is this?",
        normalized_question="what is this",
        analysis_mode=CameraAnalysisMode.IDENTIFY,
        provider="openai",
        model="gpt-vision-test",
        cloud_analysis_allowed=True,
    )

    cases: list[tuple[FakeResponsesProvider, CameraAwarenessResultState, str]] = [
        (
            FakeResponsesProvider(exc=TimeoutError("timeout data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD")),
            CameraAwarenessResultState.CAMERA_VISION_PROVIDER_TIMEOUT,
            "provider_timeout",
        ),
        (
            FakeResponsesProvider(exc=FakeProviderError(401, "auth failed data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD")),
            CameraAwarenessResultState.CAMERA_VISION_PROVIDER_AUTH_FAILED,
            "provider_auth_failed",
        ),
        (
            FakeResponsesProvider(exc=FakeProviderError(429, "rate limited data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD")),
            CameraAwarenessResultState.CAMERA_VISION_PROVIDER_RATE_LIMITED,
            "provider_rate_limited",
        ),
        (
            FakeResponsesProvider(exc=RuntimeError("unknown data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD")),
            CameraAwarenessResultState.CAMERA_ANALYSIS_FAILED,
            "unknown_provider_error",
        ),
        (
            FakeResponsesProvider(
                result=ProviderTurnResult(
                    response_id="resp-safety",
                    output_text="",
                    raw_response={"camera_vision": {"error_code": "provider_safety_blocked"}},
                )
            ),
            CameraAwarenessResultState.CAMERA_VISION_PROVIDER_SAFETY_BLOCKED,
            "provider_safety_blocked",
        ),
        (
            FakeResponsesProvider(
                result=ProviderTurnResult(response_id="resp-empty", output_text="", raw_response={})
            ),
            CameraAwarenessResultState.CAMERA_VISION_PROVIDER_RESPONSE_MALFORMED,
            "provider_response_malformed",
        ),
    ]

    for fake_client, expected_state, expected_error in cases:
        service = CameraAwarenessSubsystem(app_config.camera_awareness)
        artifact = _store_artifact(service, tmp_path)
        question.image_artifact_id = artifact.image_artifact_id
        provider = OpenAIVisionAnalysisProvider(
            app_config.camera_awareness,
            openai_config=app_config.openai,
            responses_provider=fake_client,
        )

        answer = provider.analyze_image(question, artifact)

        assert answer.result_state == expected_state
        assert answer.error_code == expected_error
        assert answer.raw_image_included is False
        assert not _contains_forbidden_payload(answer.to_dict())


def test_c21_missing_credentials_and_unavailable_provider_fail_without_network(
    temp_project_root,
    tmp_path,
) -> None:
    app_config = _camera_app_config(
        temp_project_root,
        allow_cloud_global=True,
        allow_cloud_vision=True,
        require_confirmation=False,
    )
    app_config.openai.enabled = False
    app_config.openai.api_key = None
    provider = OpenAIVisionAnalysisProvider(
        app_config.camera_awareness,
        openai_config=app_config.openai,
    )
    service = CameraAwarenessSubsystem(app_config.camera_awareness, vision_provider=provider)
    artifact = _store_artifact(service, tmp_path)
    question = CameraVisionQuestion(
        image_artifact_id=artifact.image_artifact_id,
        user_question="What is this?",
        normalized_question="what is this",
        provider="openai",
        model="gpt-vision-test",
        cloud_analysis_allowed=True,
    )

    answer = provider.analyze_image(question, artifact)

    assert answer.result_state == CameraAwarenessResultState.CAMERA_VISION_PROVIDER_UNAVAILABLE
    assert answer.error_code == "api_key_missing"
    assert provider.network_access_attempted is False
    assert getattr(provider, "last_preparation", None) is None

    unavailable = UnavailableVisionAnalysisProvider(reason="provider_unavailable")
    unavailable_answer = unavailable.analyze_image(question, artifact)

    assert unavailable_answer.result_state == CameraAwarenessResultState.CAMERA_ANALYSIS_FAILED
    assert unavailable_answer.error_code == "provider_unavailable"
    assert unavailable.network_access_attempted is False
    assert unavailable_answer.cloud_upload_performed is False


def test_c21_provider_output_remains_visual_evidence_only(
    temp_project_root,
    tmp_path,
) -> None:
    app_config = _camera_app_config(
        temp_project_root,
        allow_cloud_global=True,
        allow_cloud_vision=True,
        require_confirmation=False,
    )
    fake_client = FakeResponsesProvider(
        result=ProviderTurnResult(
            response_id="resp-action-claim",
            output_text="Click the button. This is definitely fixed.",
            raw_response={
                "camera_vision": {
                    "answer_text": "Click the button. This is definitely fixed.",
                    "concise_answer": "Provider suggests clicking the button.",
                    "confidence": "high",
                    "evidence_summary": "Visible dialog with a button.",
                    "uncertainty_reasons": [],
                    "safety_notes": [],
                    "recommended_user_action": "Click the visible button.",
                    "action_executed": True,
                    "verified": True,
                    "trust_approved": True,
                    "route_command": "click_button",
                    "task_mutation": {"done": True},
                }
            },
        )
    )
    service = _openai_service(app_config, fake_client)
    artifact = _store_artifact(service, tmp_path)

    flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=artifact.image_artifact_id,
        user_question="What should I do with this popup?",
        user_request_id="c21-visual-evidence",
        cloud_analysis_confirmed=True,
    )
    payload = flow.vision_answer.to_dict()

    assert flow.result_state == CameraAwarenessResultState.CAMERA_ANSWER_READY
    assert flow.vision_answer.recommended_user_action == "Click the visible button."
    assert flow.vision_answer.cloud_analysis_performed is True
    assert flow.vision_answer.raw_image_included is False
    assert "action_executed" not in payload
    assert "verified" not in payload
    assert "trust_approved" not in payload
    assert "route_command" not in payload
    assert "task_mutation" not in payload
    assert "Visual analysis only; not command authority." in flow.vision_answer.safety_notes
