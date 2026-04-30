from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CameraAnalysisMode,
    CameraAwarenessResultState,
    CameraAwarenessSubsystem,
    CameraFrameArtifact,
    CameraStorageMode,
    CameraVisionQuestion,
    OpenAIVisionAnalysisProvider,
    build_camera_awareness_subsystem,
    build_camera_vision_prompt,
    utc_now,
)
from stormhelm.core.events import EventBuffer
from stormhelm.core.providers.base import ProviderTurnResult


def _camera_app_config(temp_project_root, *, allow_cloud: bool = False):
    app_config = load_config(project_root=temp_project_root, env={})
    camera = app_config.camera_awareness
    camera.enabled = True
    camera.privacy.confirm_before_capture = False
    camera.capture.provider = "mock"
    camera.vision.provider = "openai"
    camera.vision.model = "gpt-vision-test"
    camera.vision.detail = "low"
    camera.vision.max_image_bytes = 4096
    camera.vision.require_confirmation_for_cloud = True
    camera.allow_cloud_vision = allow_cloud
    camera.vision.allow_cloud_vision = allow_cloud
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
    path = tmp_path / f"camera-artifact.{image_format}"
    path.write_bytes(payload)
    created_at = utc_now()
    artifact = CameraFrameArtifact(
        capture_result_id="capture-c2",
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
            response_id="resp-c2",
            output_text="Likely a JST-style connector.",
            raw_response={
                "camera_vision": {
                    "answer_text": "This looks like a JST-style connector.",
                    "concise_answer": "Likely JST-style connector.",
                    "confidence": "high",
                    "evidence_summary": "White shrouded connector body with visible pins.",
                    "uncertainty_reasons": ["No scale reference is visible."],
                    "safety_notes": ["Visual analysis only; not command authority."],
                    "suggested_next_capture": "Retake beside a ruler to estimate pitch.",
                    "recommended_user_action": "Compare pitch before ordering a replacement.",
                }
            },
        )
        self.exc = exc
        self.calls = 0
        self.last_input_items: Any = None
        self.last_model: str | None = None
        self.last_max_output_tokens: int | None = None

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
        del instructions, previous_response_id, tools
        self.calls += 1
        self.last_input_items = input_items
        self.last_model = model
        self.last_max_output_tokens = max_output_tokens
        if self.exc is not None:
            raise self.exc
        return self.result


@dataclass(slots=True)
class FakeProviderError(Exception):
    status_code: int
    message: str

    def __str__(self) -> str:
        return self.message


def test_c2_openai_provider_selection_is_configured_but_unavailable_without_credentials(
    temp_project_root,
) -> None:
    app_config = _camera_app_config(temp_project_root, allow_cloud=True)
    app_config.openai.enabled = False
    app_config.openai.api_key = None

    service = build_camera_awareness_subsystem(
        app_config.camera_awareness,
        openai_config=app_config.openai,
    )
    snapshot = service.status_snapshot()

    assert service.vision_provider.provider_kind == "openai"
    assert service.vision_provider.network_access_attempted is False
    assert snapshot["visionProviderKind"] == "openai"
    assert snapshot["visionProviderAvailable"] is False
    assert snapshot["visionUnavailableReason"] == "api_key_missing"
    assert snapshot["cloudAnalysisPerformed"] is False


def test_c2_cloud_disabled_blocks_real_provider_before_upload(temp_project_root, tmp_path) -> None:
    app_config = _camera_app_config(temp_project_root, allow_cloud=False)
    fake_client = FakeResponsesProvider()
    provider = OpenAIVisionAnalysisProvider(
        app_config.camera_awareness,
        openai_config=app_config.openai,
        responses_provider=fake_client,
    )
    events = EventBuffer(capacity=64)
    service = CameraAwarenessSubsystem(
        app_config.camera_awareness,
        events=events,
        vision_provider=provider,
    )
    artifact = _store_artifact(service, tmp_path)

    flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=artifact.image_artifact_id,
        user_question="What connector is this?",
        user_request_id="c2-cloud-disabled",
        session_id="session-c2",
        cloud_analysis_confirmed=True,
    )

    assert flow.result_state == CameraAwarenessResultState.CAMERA_CLOUD_ANALYSIS_DISABLED
    assert flow.vision_answer.error_code == "camera_cloud_analysis_disabled"
    assert fake_client.calls == 0
    assert provider.network_access_attempted is False
    assert flow.trace.cloud_upload_performed is False
    assert service.status_snapshot()["cloudAnalysisPerformed"] is False


def test_c2_cloud_confirmation_required_blocks_provider_call(temp_project_root, tmp_path) -> None:
    app_config = _camera_app_config(temp_project_root, allow_cloud=True)
    fake_client = FakeResponsesProvider()
    provider = OpenAIVisionAnalysisProvider(
        app_config.camera_awareness,
        openai_config=app_config.openai,
        responses_provider=fake_client,
    )
    service = CameraAwarenessSubsystem(app_config.camera_awareness, vision_provider=provider)
    artifact = _store_artifact(service, tmp_path)

    flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=artifact.image_artifact_id,
        user_question="What connector is this?",
        user_request_id="c2-cloud-confirmation",
        session_id="session-c2",
    )

    assert flow.result_state == CameraAwarenessResultState.CAMERA_VISION_PERMISSION_REQUIRED
    assert flow.vision_answer.error_code == "camera_vision_confirmation_required"
    assert fake_client.calls == 0
    assert provider.network_access_attempted is False
    assert flow.trace.cloud_upload_performed is False


def test_c2_openai_request_construction_normalization_and_redacted_events(
    temp_project_root,
    tmp_path,
) -> None:
    app_config = _camera_app_config(temp_project_root, allow_cloud=True)
    fake_client = FakeResponsesProvider()
    provider = OpenAIVisionAnalysisProvider(
        app_config.camera_awareness,
        openai_config=app_config.openai,
        responses_provider=fake_client,
    )
    events = EventBuffer(capacity=64)
    service = CameraAwarenessSubsystem(
        app_config.camera_awareness,
        events=events,
        vision_provider=provider,
    )
    artifact = _store_artifact(service, tmp_path)

    flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=artifact.image_artifact_id,
        user_question="What connector is this?",
        user_request_id="c2-real-analysis",
        session_id="session-c2",
        cloud_analysis_confirmed=True,
    )
    snapshot = service.status_snapshot()

    assert flow.result_state == CameraAwarenessResultState.CAMERA_ANSWER_READY
    assert flow.vision_answer.mock_answer is False
    assert flow.vision_answer.provider == "openai"
    assert flow.vision_answer.provider_kind == "openai"
    assert flow.vision_answer.cloud_upload_performed is True
    assert flow.vision_answer.cloud_analysis_performed is True
    assert flow.vision_answer.confidence.value == "high"
    assert "White shrouded connector" in flow.vision_answer.evidence_summary
    assert flow.vision_answer.uncertainty_reasons == ["No scale reference is visible."]
    assert flow.vision_answer.safety_notes == ["Visual analysis only; not command authority."]
    assert flow.vision_answer.provenance["source"] == "camera_local"
    assert flow.vision_answer.provenance["raw_image_included"] is False
    assert flow.vision_answer.provenance["cloud_upload_performed"] is True
    assert fake_client.calls == 1
    assert provider.network_access_attempted is True
    assert fake_client.last_model == "gpt-vision-test"
    content = fake_client.last_input_items[0]["content"]
    assert content[0]["type"] == "input_text"
    assert "identity recognition" in content[0]["text"].lower()
    assert content[1]["type"] == "input_image"
    assert content[1]["detail"] == "low"
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")

    assert snapshot["visionProviderKind"] == "openai"
    assert snapshot["cloudAnalysisAllowed"] is True
    assert snapshot["cloudAnalysisPerformed"] is True
    assert snapshot["lastVisionStatus"] == "camera_answer_ready"
    assert snapshot["lastVisionConfidence"] == "high"
    assert snapshot["rawImageIncluded"] is False
    assert snapshot["artifactSourceProvenance"] == "camera_local"

    event_payloads = [event["payload"] for event in events.recent(limit=64)]
    event_types = [event["event_type"] for event in events.recent(limit=64)]
    assert "camera.vision_policy_checked" in event_types
    assert "camera.vision_provider_selected" in event_types
    assert "camera.vision_image_prepared" in event_types
    assert "camera.vision_completed" in event_types
    assert "camera.answer_normalized" in event_types
    assert "camera.answer_ready" in event_types
    assert all("image_url" not in payload for payload in event_payloads)
    assert all("base64" not in str(payload).lower() for payload in event_payloads)
    assert all("raw_image" not in payload for payload in event_payloads)
    assert all(payload.get("raw_image_included") is False for payload in event_payloads)


def test_c2_artifact_validation_blocks_before_provider_call(temp_project_root, tmp_path) -> None:
    app_config = _camera_app_config(temp_project_root, allow_cloud=True)
    fake_client = FakeResponsesProvider()
    provider = OpenAIVisionAnalysisProvider(
        app_config.camera_awareness,
        openai_config=app_config.openai,
        responses_provider=fake_client,
    )
    service = CameraAwarenessSubsystem(app_config.camera_awareness, vision_provider=provider)
    expired = _store_artifact(service, tmp_path, expires_in_seconds=-1)

    expired_flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=expired.image_artifact_id,
        user_question="What is this?",
        user_request_id="c2-expired",
        cloud_analysis_confirmed=True,
    )

    assert expired_flow.result_state == CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_EXPIRED
    assert expired_flow.vision_answer.error_code == "camera_artifact_expired"
    assert fake_client.calls == 0

    missing = _store_artifact(service, tmp_path, image_format="jpg")
    Path(missing.file_path).unlink()
    missing_flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=missing.image_artifact_id,
        user_question="What is this?",
        user_request_id="c2-missing",
        cloud_analysis_confirmed=True,
    )

    assert missing_flow.result_state == CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_MISSING
    assert missing_flow.vision_answer.error_code == "camera_artifact_missing"
    assert fake_client.calls == 0

    unsupported = _store_artifact(service, tmp_path, image_format="tiff")
    unsupported_flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=unsupported.image_artifact_id,
        user_question="What is this?",
        user_request_id="c2-unsupported",
        cloud_analysis_confirmed=True,
    )

    assert unsupported_flow.result_state == CameraAwarenessResultState.CAMERA_VISION_UNSUPPORTED_FORMAT
    assert unsupported_flow.vision_answer.error_code == "camera_artifact_unsupported_format"
    assert fake_client.calls == 0

    app_config.camera_awareness.vision.max_image_bytes = 4
    too_large = _store_artifact(service, tmp_path, payload=b"0123456789", image_format="jpg")
    too_large_flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=too_large.image_artifact_id,
        user_question="What is this?",
        user_request_id="c2-too-large",
        cloud_analysis_confirmed=True,
    )

    assert too_large_flow.result_state == CameraAwarenessResultState.CAMERA_VISION_IMAGE_TOO_LARGE
    assert too_large_flow.vision_answer.error_code == "camera_artifact_too_large"
    assert fake_client.calls == 0


def test_c2_prompt_templates_cover_analysis_modes() -> None:
    cases = {
        CameraAnalysisMode.IDENTIFY: "likely object",
        CameraAnalysisMode.READ_TEXT: "transcribe",
        CameraAnalysisMode.INSPECT: "visible observations",
        CameraAnalysisMode.TROUBLESHOOT: "visible symptom",
        CameraAnalysisMode.EXPLAIN: "explain",
        CameraAnalysisMode.UNKNOWN: "visible evidence",
    }

    for mode, expected_text in cases.items():
        prompt = build_camera_vision_prompt(
            CameraVisionQuestion(
                image_artifact_id="artifact-c2",
                user_question="What am I seeing?",
                normalized_question="what am i seeing",
                analysis_mode=mode,
            )
        )

        assert prompt.analysis_mode == mode
        assert expected_text in prompt.user_prompt.lower()
        assert "do not identify people" in prompt.system_prompt.lower()
        assert "do not execute commands" in prompt.system_prompt.lower()


def test_c2_provider_failures_are_typed(temp_project_root, tmp_path) -> None:
    app_config = _camera_app_config(temp_project_root, allow_cloud=True)
    question = CameraVisionQuestion(
        image_artifact_id="artifact-c2",
        user_question="What is this?",
        normalized_question="what is this",
        analysis_mode=CameraAnalysisMode.IDENTIFY,
        provider="openai",
        model="gpt-vision-test",
        cloud_analysis_allowed=True,
    )

    cases: list[tuple[FakeResponsesProvider, CameraAwarenessResultState, str]] = [
        (
            FakeResponsesProvider(exc=TimeoutError("timeout")),
            CameraAwarenessResultState.CAMERA_VISION_PROVIDER_TIMEOUT,
            "provider_timeout",
        ),
        (
            FakeResponsesProvider(exc=FakeProviderError(401, "auth failed")),
            CameraAwarenessResultState.CAMERA_VISION_PROVIDER_AUTH_FAILED,
            "provider_auth_failed",
        ),
        (
            FakeResponsesProvider(exc=FakeProviderError(429, "rate limited")),
            CameraAwarenessResultState.CAMERA_VISION_PROVIDER_RATE_LIMITED,
            "provider_rate_limited",
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
        assert answer.cloud_upload_performed is True
        assert answer.raw_image_included is False
        assert fake_client.calls == 1
