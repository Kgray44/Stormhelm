from __future__ import annotations

import time
from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

import httpx

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.core.voice.availability import VoiceAvailability
from stormhelm.core.voice.availability import compute_voice_availability
from stormhelm.core.voice.models import VoiceAudioInput
from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.models import VoicePlaybackRequest
from stormhelm.core.voice.models import VoicePlaybackResult
from stormhelm.core.voice.models import VoiceSpeechRequest
from stormhelm.core.voice.models import VoiceSpeechSynthesisResult
from stormhelm.core.voice.models import VoiceTranscriptionResult
from stormhelm.shared.time import utc_now_iso


@dataclass(slots=True, frozen=True)
class VoiceProviderOperationResult:
    ok: bool
    status: str
    provider_name: str
    error_code: str | None = None
    error_message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class VoiceProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_mock(self) -> bool: ...

    def get_availability(self) -> VoiceAvailability: ...

    def create_session(self) -> VoiceProviderOperationResult: ...

    def close_session(self, session_id: str | None = None) -> VoiceProviderOperationResult: ...

    def submit_text_turn(self, text: str, *, session_id: str | None = None) -> VoiceProviderOperationResult: ...


@runtime_checkable
class SpeechToTextProvider(Protocol):
    def transcribe_audio(
        self,
        audio: VoiceAudioInput | bytes | None = None,
        *,
        content_type: str | None = None,
    ) -> VoiceProviderOperationResult | VoiceTranscriptionResult | Awaitable[VoiceTranscriptionResult]: ...


@runtime_checkable
class TextToSpeechProvider(Protocol):
    def synthesize_speech(
        self,
        text: str | VoiceSpeechRequest,
    ) -> VoiceProviderOperationResult | VoiceSpeechSynthesisResult | Awaitable[VoiceSpeechSynthesisResult]: ...


@runtime_checkable
class RealtimeVoiceProvider(Protocol):
    def start_listening(self) -> VoiceProviderOperationResult: ...

    def stop_listening(self) -> VoiceProviderOperationResult: ...


@runtime_checkable
class WakeWordProvider(Protocol):
    def start_wake_detection(self) -> VoiceProviderOperationResult: ...

    def stop_wake_detection(self) -> VoiceProviderOperationResult: ...


@runtime_checkable
class AudioInputProvider(Protocol):
    def start_audio_input(self) -> VoiceProviderOperationResult: ...

    def stop_audio_input(self) -> VoiceProviderOperationResult: ...


@runtime_checkable
class AudioOutputProvider(Protocol):
    def start_audio_output(self) -> VoiceProviderOperationResult: ...

    def stop_audio_output(self) -> VoiceProviderOperationResult: ...


@runtime_checkable
class VoicePlaybackProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_mock(self) -> bool: ...

    def get_availability(self) -> dict[str, Any]: ...

    def play(self, request: VoicePlaybackRequest) -> VoicePlaybackResult | Awaitable[VoicePlaybackResult]: ...

    def stop(
        self,
        playback_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoicePlaybackResult | Awaitable[VoicePlaybackResult]: ...

    def get_active_playback(self) -> VoicePlaybackResult | None: ...


@dataclass(slots=True)
class MockPlaybackProvider:
    provider_name: str = "mock"
    available: bool = True
    blocked: bool = False
    fail_playback: bool = False
    error_code: str | None = None
    error_message: str | None = None
    complete_immediately: bool = True
    playback_latency_ms: int = 0
    playback_call_count: int = 0
    _active_playback: VoicePlaybackResult | None = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return True

    def get_availability(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "available": self.available and not self.blocked,
            "unavailable_reason": None if self.available else "provider_unavailable",
            "mock": True,
        }

    def play(self, request: VoicePlaybackRequest) -> VoicePlaybackResult:
        if not request.allowed_to_play:
            return self._result(
                request,
                ok=False,
                status="blocked",
                error_code=request.blocked_reason or "playback_blocked",
                error_message=f"Playback request blocked: {request.blocked_reason or 'playback_blocked'}.",
            )
        if not self.available:
            return self._result(
                request,
                ok=False,
                status="unavailable",
                error_code="provider_unavailable",
                error_message="Mock playback provider is unavailable.",
            )
        if self.blocked:
            return self._result(
                request,
                ok=False,
                status="blocked",
                error_code="playback_blocked",
                error_message="Mock playback provider blocked playback.",
            )

        self.playback_call_count += 1
        if self.fail_playback:
            return self._result(
                request,
                ok=False,
                status="failed",
                error_code=self.error_code or "playback_failed",
                error_message=self.error_message or "Mock playback provider failed.",
            )

        started_at = utc_now_iso()
        if self.complete_immediately:
            return self._result(
                request,
                ok=True,
                status="completed",
                started_at=started_at,
                completed_at=utc_now_iso(),
                elapsed_ms=self.playback_latency_ms,
                played_locally=True,
            )

        result = self._result(
            request,
            ok=True,
            status="started",
            started_at=started_at,
            elapsed_ms=0,
            played_locally=True,
        )
        self._active_playback = result
        return result

    def stop(
        self,
        playback_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoicePlaybackResult:
        active = self._active_playback
        if active is None or (playback_id and playback_id != active.playback_id):
            return VoicePlaybackResult(
                ok=False,
                playback_request_id=None,
                audio_output_id=None,
                provider=self.provider_name,
                device="default",
                status="unavailable",
                error_code="no_active_playback",
                error_message="No active local playback exists.",
                output_metadata={"reason": reason},
                played_locally=False,
                user_heard_claimed=False,
            )
        self._active_playback = None
        return replace(
            active,
            ok=True,
            status="stopped",
            stopped_at=utc_now_iso(),
            error_code=None,
            error_message=None,
            output_metadata={**dict(active.output_metadata), "stop_reason": reason},
            user_heard_claimed=False,
        )

    def get_active_playback(self) -> VoicePlaybackResult | None:
        return self._active_playback

    def _result(
        self,
        request: VoicePlaybackRequest,
        *,
        ok: bool,
        status: str,
        started_at: str | None = None,
        completed_at: str | None = None,
        stopped_at: str | None = None,
        elapsed_ms: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        played_locally: bool = False,
    ) -> VoicePlaybackResult:
        return VoicePlaybackResult(
            ok=ok,
            playback_request_id=request.playback_request_id,
            audio_output_id=request.audio_output_id,
            synthesis_id=request.synthesis_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            provider=self.provider_name,
            device=request.device,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            stopped_at=stopped_at,
            elapsed_ms=elapsed_ms,
            error_code=error_code,
            error_message=error_message,
            output_metadata={
                "audio_output_id": request.audio_output_id,
                "format": request.format,
                "mime_type": request.mime_type,
                "size_bytes": request.size_bytes,
                "duration_ms": request.duration_ms,
            },
            played_locally=played_locally,
            user_heard_claimed=False,
        )


@dataclass(slots=True)
class LocalPlaybackProvider:
    config: VoiceConfig
    provider_name: str = "local"

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return False

    def get_availability(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "available": False,
            "unavailable_reason": "local_playback_not_implemented",
            "mock": False,
        }

    def play(self, request: VoicePlaybackRequest) -> VoicePlaybackResult:
        return VoicePlaybackResult(
            ok=False,
            playback_request_id=request.playback_request_id,
            audio_output_id=request.audio_output_id,
            synthesis_id=request.synthesis_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            provider=self.provider_name,
            device=request.device,
            status="unavailable",
            error_code="local_playback_not_implemented",
            error_message="Real local playback is not implemented in this Voice-4 boundary.",
            output_metadata=request.to_metadata(),
            played_locally=False,
            user_heard_claimed=False,
        )

    def stop(
        self,
        playback_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoicePlaybackResult:
        del playback_id
        return VoicePlaybackResult(
            ok=False,
            playback_request_id=None,
            audio_output_id=None,
            provider=self.provider_name,
            device=self.config.playback.device,
            status="unavailable",
            error_code="no_active_playback",
            error_message="No active local playback exists.",
            output_metadata={"reason": reason},
            played_locally=False,
            user_heard_claimed=False,
        )

    def get_active_playback(self) -> VoicePlaybackResult | None:
        return None


@dataclass(slots=True)
class MockVoiceProvider:
    provider_name: str = "mock"
    stt_transcript: str = ""
    stt_confidence: float | None = 0.9
    stt_error_code: str | None = None
    stt_error_message: str | None = None
    stt_timeout: bool = False
    stt_unsupported_audio: bool = False
    stt_uncertain: bool = False
    stt_model: str = "mock-stt"
    stt_latency_ms: int = 0
    tts_audio_bytes: bytes = b"mock audio"
    tts_error_code: str | None = None
    tts_error_message: str | None = None
    tts_timeout: bool = False
    tts_unsupported_voice: bool = False
    tts_model: str = "mock-tts"
    tts_voice: str = "mock-voice"
    tts_format: str = "mp3"
    tts_latency_ms: int = 0
    tts_call_count: int = 0

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return True

    def get_availability(self) -> VoiceAvailability:
        return VoiceAvailability(
            enabled_requested=True,
            openai_enabled=False,
            provider_configured=True,
            provider_name=self.provider_name,
            available=True,
            unavailable_reason=None,
            mode="mock",
            realtime_allowed=True,
            stt_allowed=True,
            tts_allowed=True,
            wake_allowed=True,
            mock_provider_active=True,
        )

    def create_session(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"session_id": f"mock-voice-{uuid4().hex[:8]}"})

    def close_session(self, session_id: str | None = None) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"session_id": session_id})

    def submit_text_turn(self, text: str, *, session_id: str | None = None) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"session_id": session_id, "transcript": text})

    def transcribe_audio(
        self,
        audio: VoiceAudioInput | bytes | None = None,
        *,
        content_type: str | None = None,
    ) -> VoiceProviderOperationResult | VoiceTranscriptionResult:
        if not isinstance(audio, VoiceAudioInput):
            del audio, content_type
            return self._mock_result(payload={"transcript": "", "confidence": None, "audio_processed": False})

        if self.stt_timeout:
            return self._transcription_failure(
                audio,
                error_code="provider_timeout",
                error_message="Mock STT provider timed out.",
            )
        if self.stt_unsupported_audio:
            return self._transcription_failure(
                audio,
                error_code="unsupported_audio",
                error_message="Mock STT provider rejected the audio.",
            )
        if self.stt_error_code:
            return self._transcription_failure(
                audio,
                error_code=self.stt_error_code,
                error_message=self.stt_error_message or self.stt_error_code,
            )

        transcript = " ".join(str(self.stt_transcript or "").split()).strip()
        if not transcript:
            return self._transcription_failure(
                audio,
                error_code="empty_transcript",
                error_message="Mock STT provider returned no transcript.",
            )

        return VoiceTranscriptionResult(
            ok=True,
            input_id=audio.input_id,
            provider=self.provider_name,
            model=self.stt_model,
            transcript=transcript,
            confidence=self.stt_confidence,
            duration_ms=audio.duration_ms,
            provider_latency_ms=self.stt_latency_ms,
            raw_provider_metadata={"mock": True, "uncertain": self.stt_uncertain},
            source=f"{self.provider_name}_stt",
            usable_for_core_turn=True,
            transcription_uncertain=self.stt_uncertain,
            status="completed",
            audio_input_metadata=audio.to_metadata(),
        )

    def synthesize_speech(self, text: str | VoiceSpeechRequest) -> VoiceProviderOperationResult | VoiceSpeechSynthesisResult:
        if not isinstance(text, VoiceSpeechRequest):
            return self._mock_result(payload={"text": text, "audio_playback_started": False})

        self.tts_call_count += 1
        if self.tts_timeout:
            return self._speech_failure(
                text,
                error_code="provider_timeout",
                error_message="Mock TTS provider timed out.",
            )
        if self.tts_unsupported_voice:
            return self._speech_failure(
                text,
                error_code="unsupported_voice",
                error_message="Mock TTS provider rejected the configured voice.",
            )
        if self.tts_error_code:
            return self._speech_failure(
                text,
                error_code=self.tts_error_code,
                error_message=self.tts_error_message or self.tts_error_code,
            )

        audio_output = VoiceAudioOutput.from_bytes(
            self.tts_audio_bytes,
            format=text.format or self.tts_format,
            metadata={"mock": True, "speech_request_id": text.speech_request_id},
        )
        return VoiceSpeechSynthesisResult(
            ok=True,
            speech_request_id=text.speech_request_id,
            speech_request=text,
            provider=self.provider_name,
            model=text.model or self.tts_model,
            voice=text.voice or self.tts_voice,
            format=text.format or self.tts_format,
            status="succeeded",
            audio_output=audio_output,
            output_size_bytes=audio_output.size_bytes,
            provider_latency_ms=self.tts_latency_ms,
            raw_provider_metadata={"mock": True},
            playable=False,
            persisted=False,
        )

    def _transcription_failure(
        self,
        audio: VoiceAudioInput,
        *,
        error_code: str,
        error_message: str,
    ) -> VoiceTranscriptionResult:
        return VoiceTranscriptionResult(
            ok=False,
            input_id=audio.input_id,
            provider=self.provider_name,
            model=self.stt_model,
            transcript="",
            duration_ms=audio.duration_ms,
            provider_latency_ms=self.stt_latency_ms,
            error_code=error_code,
            error_message=error_message,
            raw_provider_metadata={"mock": True},
            source=f"{self.provider_name}_stt",
            usable_for_core_turn=False,
            transcription_uncertain=True,
            status="failed",
            audio_input_metadata=audio.to_metadata(),
        )

    def start_listening(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"listening_started": False})

    def _speech_failure(
        self,
        request: VoiceSpeechRequest,
        *,
        error_code: str,
        error_message: str,
    ) -> VoiceSpeechSynthesisResult:
        return VoiceSpeechSynthesisResult(
            ok=False,
            speech_request_id=request.speech_request_id,
            speech_request=request,
            provider=self.provider_name,
            model=request.model or self.tts_model,
            voice=request.voice or self.tts_voice,
            format=request.format or self.tts_format,
            status="failed",
            provider_latency_ms=self.tts_latency_ms,
            error_code=error_code,
            error_message=error_message,
            raw_provider_metadata={"mock": True},
            playable=False,
            persisted=False,
        )

    def stop_listening(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"listening_stopped": True})

    def start_wake_detection(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"wake_detection_started": False, "audio_sent_to_cloud": False})

    def stop_wake_detection(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"wake_detection_stopped": True})

    def start_audio_input(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_input_started": False})

    def stop_audio_input(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_input_stopped": True})

    def start_audio_output(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_output_started": False})

    def stop_audio_output(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_output_stopped": True})

    def _mock_result(self, *, payload: dict[str, Any] | None = None) -> VoiceProviderOperationResult:
        return VoiceProviderOperationResult(
            ok=True,
            status="mock",
            provider_name=self.provider_name,
            payload=dict(payload or {}),
        )


@dataclass(slots=True)
class OpenAIVoiceProviderStub:
    config: VoiceConfig
    openai_config: OpenAIConfig
    network_call_count: int = 0

    @property
    def name(self) -> str:
        return "openai"

    @property
    def is_mock(self) -> bool:
        return False

    def get_availability(self) -> VoiceAvailability:
        return compute_voice_availability(self.config, self.openai_config)

    def create_session(self) -> VoiceProviderOperationResult:
        return self._not_implemented("OpenAI Realtime sessions are not implemented in Voice-0.")

    def close_session(self, session_id: str | None = None) -> VoiceProviderOperationResult:
        del session_id
        return self._not_implemented("OpenAI voice sessions are not implemented in Voice-0.")

    def submit_text_turn(self, text: str, *, session_id: str | None = None) -> VoiceProviderOperationResult:
        del text, session_id
        return self._not_implemented("Voice text turns must cross the Core bridge in a later phase.")

    def transcribe_audio(self, audio: bytes | None = None, *, content_type: str | None = None) -> VoiceProviderOperationResult:
        del audio, content_type
        return self._not_implemented("OpenAI speech-to-text is not implemented in Voice-0.")

    def synthesize_speech(self, text: str) -> VoiceProviderOperationResult:
        del text
        return self._not_implemented("OpenAI text-to-speech is not implemented in Voice-0.")

    def start_listening(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Realtime listening is not implemented in Voice-0.")

    def stop_listening(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Realtime listening is not implemented in Voice-0.")

    def start_wake_detection(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Wake detection is not implemented in Voice-0.")

    def stop_wake_detection(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Wake detection is not implemented in Voice-0.")

    def start_audio_input(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Microphone capture is not implemented in Voice-0.")

    def stop_audio_input(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Microphone capture is not implemented in Voice-0.")

    def start_audio_output(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Audio playback is not implemented in Voice-0.")

    def stop_audio_output(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Audio playback is not implemented in Voice-0.")

    def _not_implemented(self, message: str) -> VoiceProviderOperationResult:
        return VoiceProviderOperationResult(
            ok=False,
            status="not_implemented",
            provider_name=self.name,
            error_code="not_implemented",
            error_message=message,
        )


PostTranscription = Callable[
    ...,
    dict[str, Any] | Awaitable[dict[str, Any]],
]

PostSpeech = Callable[
    ...,
    bytes | dict[str, Any] | Awaitable[bytes | dict[str, Any]],
]


@dataclass(slots=True)
class OpenAIVoiceProvider(OpenAIVoiceProviderStub):
    post_transcription: PostTranscription | None = None
    post_speech: PostSpeech | None = None

    @property
    def stt_model(self) -> str:
        return str(self.config.openai.stt_model or "").strip() or "gpt-4o-mini-transcribe"

    @property
    def tts_model(self) -> str:
        return str(self.config.openai.tts_model or "").strip() or "gpt-4o-mini-tts"

    @property
    def tts_voice(self) -> str:
        return str(self.config.openai.tts_voice or "").strip() or "cedar"

    @property
    def tts_format(self) -> str:
        return str(self.config.openai.tts_format or "mp3").strip().lower() or "mp3"

    async def transcribe_audio(
        self,
        audio: VoiceAudioInput | bytes | None = None,
        *,
        content_type: str | None = None,
    ) -> VoiceProviderOperationResult | VoiceTranscriptionResult:
        if not isinstance(audio, VoiceAudioInput):
            del content_type
            return self._not_implemented("OpenAI speech-to-text requires a typed VoiceAudioInput in Voice-2.")
        if not self.openai_config.enabled or not self.openai_config.api_key:
            return self._transcription_failure(
                audio,
                error_code="provider_unavailable",
                error_message="OpenAI STT is unavailable because OpenAI is disabled or missing credentials.",
            )

        start = time.perf_counter()
        self.network_call_count += 1
        try:
            payload = await self._post_transcription(audio)
        except TimeoutError:
            return self._transcription_failure(
                audio,
                error_code="provider_timeout",
                error_message="OpenAI STT provider timed out.",
                provider_latency_ms=_elapsed_ms(start),
            )
        except httpx.TimeoutException:
            return self._transcription_failure(
                audio,
                error_code="provider_timeout",
                error_message="OpenAI STT provider timed out.",
                provider_latency_ms=_elapsed_ms(start),
            )
        except Exception as error:
            return self._transcription_failure(
                audio,
                error_code="provider_error",
                error_message=str(error),
                provider_latency_ms=_elapsed_ms(start),
            )

        transcript = " ".join(str(payload.get("text") or payload.get("transcript") or "").split()).strip()
        if not transcript:
            return self._transcription_failure(
                audio,
                error_code="empty_transcript",
                error_message="OpenAI STT returned no transcript.",
                provider_latency_ms=_elapsed_ms(start),
                raw_provider_metadata=_sanitize_openai_metadata(payload),
            )

        duration_value = payload.get("duration_ms", payload.get("duration"))
        duration_ms = audio.duration_ms
        if duration_ms is None and isinstance(duration_value, (int, float)):
            duration_ms = int(duration_value * 1000) if duration_value < 1000 else int(duration_value)
        confidence = payload.get("confidence")
        return VoiceTranscriptionResult(
            ok=True,
            input_id=audio.input_id,
            provider="openai",
            model=self.stt_model,
            transcript=transcript,
            language=str(payload.get("language") or "").strip() or self.config.openai.transcription_language,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            duration_ms=duration_ms,
            provider_latency_ms=_elapsed_ms(start),
            raw_provider_metadata=_sanitize_openai_metadata(payload),
            source="openai_stt",
            usable_for_core_turn=True,
            transcription_uncertain=False,
            status="completed",
            audio_input_metadata=audio.to_metadata(),
        )

    async def _post_transcription(self, audio: VoiceAudioInput) -> dict[str, Any]:
        data = {
            "model": self.stt_model,
            "response_format": "json",
        }
        if self.config.openai.transcription_language:
            data["language"] = self.config.openai.transcription_language
        if self.config.openai.transcription_prompt:
            data["prompt"] = self.config.openai.transcription_prompt
        files = {"file": (audio.filename, audio.read_bytes(), audio.mime_type)}
        timeout = float(self.config.openai.timeout_seconds or self.openai_config.timeout_seconds)
        url = f"{self.openai_config.base_url.rstrip('/')}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.openai_config.api_key}"}

        if self.post_transcription is not None:
            result = self.post_transcription(url=url, headers=headers, data=data, files=files, timeout=timeout)
            if hasattr(result, "__await__"):
                return await result  # type: ignore[no-any-return]
            return dict(result)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}

    def _transcription_failure(
        self,
        audio: VoiceAudioInput,
        *,
        error_code: str,
        error_message: str,
        provider_latency_ms: int | None = None,
        raw_provider_metadata: dict[str, Any] | None = None,
    ) -> VoiceTranscriptionResult:
        return VoiceTranscriptionResult(
            ok=False,
            input_id=audio.input_id,
            provider="openai",
            model=self.stt_model,
            transcript="",
            duration_ms=audio.duration_ms,
            provider_latency_ms=provider_latency_ms,
            error_code=error_code,
            error_message=error_message,
            raw_provider_metadata=dict(raw_provider_metadata or {}),
            source="openai_stt",
            usable_for_core_turn=False,
            transcription_uncertain=True,
            status="failed",
            audio_input_metadata=audio.to_metadata(),
        )

    async def synthesize_speech(self, text: str | VoiceSpeechRequest) -> VoiceProviderOperationResult | VoiceSpeechSynthesisResult:
        if not isinstance(text, VoiceSpeechRequest):
            return self._not_implemented("OpenAI text-to-speech requires a typed VoiceSpeechRequest in Voice-3.")
        if not self.openai_config.enabled or not self.openai_config.api_key:
            return self._speech_failure(
                text,
                error_code="provider_unavailable",
                error_message="OpenAI TTS is unavailable because OpenAI is disabled or missing credentials.",
            )

        start = time.perf_counter()
        self.network_call_count += 1
        try:
            payload = await self._post_speech(text)
        except TimeoutError:
            return self._speech_failure(
                text,
                error_code="provider_timeout",
                error_message="OpenAI TTS provider timed out.",
                provider_latency_ms=_elapsed_ms(start),
            )
        except httpx.TimeoutException:
            return self._speech_failure(
                text,
                error_code="provider_timeout",
                error_message="OpenAI TTS provider timed out.",
                provider_latency_ms=_elapsed_ms(start),
            )
        except Exception as error:
            return self._speech_failure(
                text,
                error_code="provider_error",
                error_message=str(error),
                provider_latency_ms=_elapsed_ms(start),
            )

        audio_bytes, provider_metadata = _speech_payload_to_bytes_and_metadata(payload)
        if not audio_bytes:
            return self._speech_failure(
                text,
                error_code="empty_audio_output",
                error_message="OpenAI TTS returned no audio bytes.",
                provider_latency_ms=_elapsed_ms(start),
                raw_provider_metadata=provider_metadata,
            )

        audio_output = self._build_tts_audio_output(text, audio_bytes)
        persisted = bool(audio_output.file_path)
        return VoiceSpeechSynthesisResult(
            ok=True,
            speech_request_id=text.speech_request_id,
            speech_request=text,
            provider="openai",
            model=text.model or self.tts_model,
            voice=text.voice or self.tts_voice,
            format=text.format or self.tts_format,
            status="succeeded",
            audio_output=audio_output,
            output_size_bytes=audio_output.size_bytes,
            provider_latency_ms=_elapsed_ms(start),
            raw_provider_metadata=provider_metadata,
            playable=False,
            persisted=persisted,
        )

    async def _post_speech(self, request: VoiceSpeechRequest) -> bytes | dict[str, Any]:
        body: dict[str, object] = {
            "model": request.model or self.tts_model,
            "input": request.text,
            "voice": request.voice or self.tts_voice,
            "response_format": request.format or self.tts_format,
            "speed": float(self.config.openai.tts_speed or 1.0),
        }
        timeout = float(self.config.openai.timeout_seconds or self.openai_config.timeout_seconds)
        url = f"{self.openai_config.base_url.rstrip('/')}/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.openai_config.api_key}",
            "Content-Type": "application/json",
        }

        if self.post_speech is not None:
            result = self.post_speech(url=url, headers=headers, json=body, timeout=timeout)
            if hasattr(result, "__await__"):
                return await result  # type: ignore[no-any-return]
            return result

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.content

    def _build_tts_audio_output(self, request: VoiceSpeechRequest, audio_bytes: bytes) -> VoiceAudioOutput:
        if self.config.openai.persist_tts_outputs and self.config.openai.output_audio_dir:
            directory = Path(self.config.openai.output_audio_dir)
            directory.mkdir(parents=True, exist_ok=True)
            suffix = (request.format or self.tts_format).strip().lower() or "mp3"
            path = directory / f"{request.speech_request_id}.{suffix}"
            path.write_bytes(audio_bytes)
            return VoiceAudioOutput.from_file(
                path,
                format=suffix,
                metadata={"speech_request_id": request.speech_request_id},
            )
        return VoiceAudioOutput.from_bytes(
            audio_bytes,
            format=request.format or self.tts_format,
            metadata={"speech_request_id": request.speech_request_id},
        )

    def _speech_failure(
        self,
        request: VoiceSpeechRequest,
        *,
        error_code: str,
        error_message: str,
        provider_latency_ms: int | None = None,
        raw_provider_metadata: dict[str, Any] | None = None,
    ) -> VoiceSpeechSynthesisResult:
        return VoiceSpeechSynthesisResult(
            ok=False,
            speech_request_id=request.speech_request_id,
            speech_request=request,
            provider="openai",
            model=request.model or self.tts_model,
            voice=request.voice or self.tts_voice,
            format=request.format or self.tts_format,
            status="failed",
            provider_latency_ms=provider_latency_ms,
            error_code=error_code,
            error_message=error_message,
            raw_provider_metadata=dict(raw_provider_metadata or {}),
            playable=False,
            persisted=False,
        )


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _sanitize_openai_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {
        "response_keys": sorted(str(key) for key in payload.keys()),
    }
    for key in ("language", "duration", "duration_ms", "segments"):
        value = payload.get(key)
        if key == "segments" and isinstance(value, list):
            safe["segment_count"] = len(value)
            continue
        if value is not None and key != "segments":
            safe[key] = value
    return safe


def _speech_payload_to_bytes_and_metadata(payload: bytes | dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if isinstance(payload, bytes):
        return payload, {"response_kind": "bytes"}
    if isinstance(payload, dict):
        audio = payload.get("audio") or payload.get("content") or b""
        if isinstance(audio, str):
            audio_bytes = audio.encode("utf-8")
        elif isinstance(audio, bytes):
            audio_bytes = audio
        else:
            audio_bytes = b""
        return audio_bytes, {
            "response_kind": "dict",
            "response_keys": sorted(str(key) for key in payload.keys()),
        }
    return b"", {"response_kind": type(payload).__name__}
