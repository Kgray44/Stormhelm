# Stormhelm Voice Foundation

This is the developer/foundation record for the voice subsystem. For user-facing setup, status, examples, and safety boundaries, use [voice.md](voice.md).

Voice-0 added the typed foundation for Stormhelm voice without enabling real audio runtime.

Voice-0 implemented:

- `voice` configuration with disabled-by-default OpenAI-backed settings.
- OpenAI-dependent availability rules with explicit unavailable reasons.
- Typed voice state snapshots and a traceable state controller.
- Provider protocols for future wake, audio input, audio output, STT, TTS, and Realtime providers.
- A clearly marked mock provider for tests and development diagnostics.
- OpenAI provider stubs for not-yet-implemented voice surfaces that return `not_implemented` and make no network calls.
- Voice-to-Core request/result contracts.
- A deterministic spoken response renderer scaffold.
- Voice event names and payload helpers.
- Core status diagnostics under `/status` via `CoreContainer.status_snapshot()["voice"]`.

Voice-1 adds:

- manual transcript voice-turn submission through `VoiceService.submit_manual_voice_turn(...)`;
- typed `VoiceTurn` and `VoiceTurnResult` objects;
- a Core bridge path that calls the existing `AssistantOrchestrator.handle_message(...)` boundary;
- voice metadata in Core `input_context` with `source="manual_voice"` and `core_bridge_required=true`;
- spoken response preview/scaffold integration;
- manual turn diagnostics for the last turn, route family, subsystem, result state, trust posture, verification posture, and spoken candidate;
- manual turn events including `voice.manual_turn_received`, `voice.core_request_started`, `voice.core_request_completed`, `voice.spoken_response_prepared`, `voice.turn_completed`, and `voice.turn_failed`;
- truthful runtime flags for manual transcript input, no real audio, no live STT/listening, no TTS, no Realtime, and no playback.

Voice-2 adds:

- typed `VoiceAudioInput` metadata for controlled file/blob/fixture audio;
- typed `VoiceTranscriptionResult` objects with provider/model/source/error/latency/provenance fields;
- an OpenAI STT provider for bounded controlled audio input using the configured `voice.openai.stt_model`;
- optional OpenAI STT hints through `voice.openai.transcription_language` and `voice.openai.transcription_prompt`;
- OpenAI STT safety limits through `voice.openai.timeout_seconds`, `voice.openai.max_audio_seconds`, and `voice.openai.max_audio_bytes`;
- deterministic mock STT behavior for tests, including transcript, empty transcript, timeout, provider error, unsupported audio, and uncertainty cases;
- `VoiceService.submit_audio_voice_turn(...)`, which validates controlled audio, transcribes it, creates a `VoiceTurn` with source such as `openai_stt` or `mock_stt`, and reuses the Voice-1 Core bridge;
- STT diagnostics for the last transcription, audio metadata, provider/model, latency, blocked reasons, and OpenAI call attempt status;
- STT events including `voice.audio_input_received`, `voice.audio_validation_failed`, `voice.transcription_started`, `voice.transcription_completed`, and `voice.transcription_failed`.

Voice-3 adds:

- typed `VoiceSpeechRequest` objects for Core-approved spoken response text and explicit safe test text;
- typed `VoiceSpeechSynthesisResult` and `VoiceAudioOutput` objects for generated speech artifacts and bounded output metadata;
- OpenAI TTS synthesis through the configured `voice.openai.tts_model`, `voice.openai.tts_voice`, `voice.openai.tts_format`, and `voice.openai.tts_speed`;
- bounded TTS controls through `voice.openai.max_tts_chars`, `voice.openai.output_audio_dir`, and disabled-by-default `voice.openai.persist_tts_outputs`;
- deterministic mock TTS behavior for tests, including fake transient audio output, provider errors, timeouts, unsupported voices, and blocked requests;
- `VoiceService.synthesize_turn_response(...)` and `VoiceService.synthesize_speech_text(...)` for controlled speech artifact creation without re-routing turns or executing tools;
- TTS diagnostics for the last speech request, synthesis result, spoken text preview, provider/model/voice/format, audio output metadata, latency, blocked reasons, and OpenAI TTS call attempt status;
- TTS events including `voice.speech_request_created`, `voice.speech_request_blocked`, `voice.synthesis_started`, `voice.synthesis_completed`, `voice.synthesis_failed`, and `voice.audio_output_created`.

Voice-4 adds:

- disabled-by-default `voice.playback` configuration that is gated separately from TTS generation;
- typed `VoicePlaybackRequest` and `VoicePlaybackResult` objects for local playback attempts, stops, blocks, and failures;
- a `VoicePlaybackProvider` boundary plus deterministic `MockPlaybackProvider` test implementation;
- a stub `LocalPlaybackProvider` that reports unavailable instead of silently invoking platform audio;
- `VoiceService.play_speech_output(...)`, `VoiceService.play_turn_response(...)`, and `VoiceService.stop_playback(...)`;
- playback diagnostics for provider/device/volume, last request/result, active playback, timestamps, blocked reasons, and the invariant that Stormhelm never claims the user heard audio;
- playback events including `voice.playback_request_created`, `voice.playback_blocked`, `voice.playback_started`, `voice.playback_completed`, `voice.playback_failed`, and `voice.playback_stopped`.

Voice-5 adds:

- disabled-by-default `voice.capture` configuration for controlled push-to-talk/manual capture;
- typed `VoiceCaptureRequest`, `VoiceCaptureSession`, `VoiceCaptureResult`, and `VoiceCaptureTurnResult` objects;
- a `VoiceCaptureProvider` boundary plus deterministic `MockCaptureProvider` test implementation;
- `VoiceService.start_push_to_talk_capture(...)`, `VoiceService.stop_push_to_talk_capture(...)`, `VoiceService.cancel_capture(...)`, and `VoiceService.submit_captured_audio_turn(...)`;
- `VoiceService.capture_and_submit_turn(...)` as a supervised pipeline helper that reuses Voice-2 STT, Voice-1 Core bridge, Voice-3 TTS, and Voice-4 playback without creating new command authority;
- capture diagnostics for provider/device/mode, active capture, last capture, bounded audio metadata, errors, and truth flags for no wake word, no VAD, no Realtime, no continuous loop, and `always_listening=false`;
- capture events including `voice.capture_request_created`, `voice.capture_blocked`, `voice.capture_started`, `voice.capture_stopped`, `voice.capture_cancelled`, `voice.capture_timeout`, `voice.capture_failed`, and `voice.capture_audio_created`.

Voice-6A adds:

- a real `LocalCaptureProvider` boundary that remains disabled by default and requires `voice.capture.enabled=true` plus `voice.capture.allow_dev_capture=true`;
- a lazy optional `sounddevice` WAV backend, reported unavailable with typed reasons such as `dependency_missing`, `unsupported_platform`, `device_unavailable`, or `permission_denied` when the platform cannot record;
- explicit local capture start/stop/cancel lifecycle behavior, with one active capture at a time, max-duration timeout marking, max-byte checks, transient WAV output metadata, and cleanup hooks;
- provider diagnostics for dependency, platform, configured device, device availability, permission state/error, local gate state, and cleanup warning without exposing raw audio bytes;
- fake-backend tests for real-provider internals so normal pytest never touches microphone hardware or OS permissions.

Voice-6B adds:

- backend-owned voice control API actions for start, stop, cancel, submit captured audio, capture-and-submit, and stop playback;
- UI client/controller wiring that routes Ghost/Deck requests to `VoiceService` rather than providers or tools;
- a compact sanitized `voiceState` payload for Ghost and Deck, including capture provider kind, active capture, last transcription/Core/TTS/playback state, bounded previews, and truth flags;
- Ghost action strip and context-card affordances for explicit push-to-talk capture without adding a detached recorder panel;
- a compact Command Deck voice capture station generated from backend status for provider, capture, pipeline, and truth inspection;
- voice-core state mapping where explicit active capture maps to `listening`, transcription/Core routing maps to `thinking`, playback maps to `speaking`, and disabled/unavailable states map to `warning`;
- event/snapshot reconciliation through the existing stream and polling pattern, with no frontend-owned command router.

Voice-7 adds:

- a typed `VoiceReadinessReport` that distinguishes disabled, misconfigured, unavailable, degraded, and ready voice states;
- a typed `VoicePipelineStageSummary` that preserves capture, STT, Core bridge, TTS, and playback stage truth without collapsing partial success into overall success;
- readiness diagnostics under `VoiceService.status_snapshot()["readiness"]` plus compact `/voice/readiness` and `/voice/pipeline` API surfaces;
- readiness and stage summary content in the Ghost/Deck `voiceState` payload, with bounded previews and no raw audio or secrets;
- a refined Command Deck voice station with readiness, stage, capture, pipeline, and truth sections;
- a `voice.refreshReadiness` local surface action that refreshes backend readiness instead of touching providers directly;
- Ghost copy hardening for capture disabled, provider unavailable, capture cancelled, transcribing, Core routing, response prepared, and playback active states.

Voice-8 adds:

- `VoicePipelineScenario`, `VoicePipelineExpectedResult`, and `VoicePipelineEvaluationResult` for deterministic supervised-loop evaluation;
- `run_voice_pipeline_scenario(...)` and `run_voice_pipeline_suite(...)` for mocked end-to-end checks that exercise the merged Voice-5 capture boundary, Voice-2 STT, the Voice-1 Core bridge, Voice-3 TTS, Voice-4 playback, and stop-playback behavior;
- stage-specific pipeline summaries that keep capture, transcription, Core routing, spoken response preparation, synthesis, and playback truth separate;
- correlated synthetic voice pipeline events for evaluation, including capture start/stop/cancel/timeout, STT, Core, TTS, audio-output, and playback events;
- compact Ghost/Deck-facing payloads for evaluation assertions that avoid wake/VAD/Realtime/always-listening claims and avoid saying the user heard audio;
- failure-path tests for capture cancellation, capture timeout, STT failure, empty transcript, Core clarification, Core confirmation, Core blocked, TTS disabled/failure, playback unavailable/failure, and stop playback.

Still not implemented:

- real wake word detection;
- automatic/background microphone capture;
- live microphone speech-to-text outside the controlled push-to-talk boundary;
- production local audio playback through a platform device;
- OpenAI Realtime sessions;
- WebRTC or WebSocket audio streaming;
- VAD;
- continuous listening or always-listening behavior;
- full interruption or barge-in command semantics;
- direct voice command execution;
- frontend command authority;
- provider calls from UI;
- secret editing UI;
- sensitive action confirmation execution;
- raw audio persistence by default;
- generated audio persistence by default;
- a detached voice UI or large settings dashboard.

Voice remains an input/output surface for Stormhelm. Speech-derived requests enter through the Core bridge or the existing planner/orchestrator boundary. Voice providers must not execute tools, lower trust requirements, or become a separate assistant path.

Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/bridge.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/events.py`, `src/stormhelm/core/voice/evaluation.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `config/default.toml`
Tests: `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_manual_turn.py`, `tests/test_voice_audio_turn.py`, `tests/test_voice_core_bridge_contracts.py`, `tests/test_voice_events.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_playback_service.py`, `tests/test_voice_pipeline_e2e.py`

Availability law:

```text
voice available = voice.enabled
               && voice.mode != "disabled"
               && voice.provider == "openai"
               && openai.enabled
               && OpenAI API key is configured
               && configured voice OpenAI models are present
```

If a mock provider is active, diagnostics must say so. If a later feature is not implemented yet, diagnostics must report `not_implemented` or a truthful `no_*` runtime flag instead of implying listening, speaking, Realtime, or production audio playback support. Voice-2 supports controlled audio file/blob/fixture STT only; it must not imply live microphone capture or continuous listening. Voice-3 supports controlled TTS audio artifact generation only; it must not imply Stormhelm spoke aloud, that playback occurred, or that the user heard the response. Voice-4 can truthfully report controlled local playback through a provider boundary, but playback completion still does not mean the underlying task succeeded or that the user heard it. Voice-5 can truthfully report an explicit push-to-talk/manual capture boundary, but capture completion still does not mean transcription succeeded, Core understood intent, an action completed, TTS generated audio, playback occurred, or the user heard it. Voice-6A may record one explicitly started local capture when all gates and dependencies allow it; local capture availability still must not imply wake word, VAD, Realtime, always-listening, continuous conversation, or command authority. Voice-6B may expose push-to-talk controls in Ghost/Deck, but those controls still only call backend `VoiceService` actions and must not call providers, tools, or Core directly from the frontend. Voice-7 may expose readiness and setup hints, but readiness still distinguishes enabled from available, available from active, capture from transcription, Core routing from action success, TTS generation from playback, and playback from the user hearing the response. Voice-8 evaluates the supervised push-to-talk pipeline with mocks/fakes by default and does not add new capture, wake word, VAD, Realtime, continuous listening, or command authority.

Recommended next phase: run the post-merge Voice-8.1 revalidation against the merged Voice-5 through Voice-7 stack, then move to the next dedicated voice phase only if the pipeline remains truthful and bounded.
