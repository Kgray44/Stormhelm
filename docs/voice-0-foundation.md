# Stormhelm Voice Foundation

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

Still not implemented:

- real microphone capture;
- real wake word detection;
- live microphone speech-to-text;
- production local audio playback through a platform device;
- OpenAI Realtime sessions;
- WebRTC or WebSocket audio streaming;
- VAD;
- continuous listening;
- full interruption or barge-in command semantics;
- direct voice command execution;
- sensitive action confirmation execution;
- raw audio persistence by default;
- generated audio persistence by default;
- a detached voice UI or large settings dashboard.

Voice remains an input/output surface for Stormhelm. Speech-derived requests enter through the Core bridge or the existing planner/orchestrator boundary. Voice providers must not execute tools, lower trust requirements, or become a separate assistant path.

Availability law:

```text
voice available = voice.enabled
               && voice.mode != "disabled"
               && voice.provider == "openai"
               && openai.enabled
               && OpenAI API key is configured
               && configured voice OpenAI models are present
```

If a mock provider is active, diagnostics must say so. If a later feature is not implemented yet, diagnostics must report `not_implemented` or a truthful `no_*` runtime flag instead of implying listening, speaking, Realtime, or production audio playback support. Voice-2 supports controlled audio file/blob/fixture STT only; it must not imply live microphone capture or continuous listening. Voice-3 supports controlled TTS audio artifact generation only; it must not imply Stormhelm spoke aloud, that playback occurred, or that the user heard the response. Voice-4 can truthfully report controlled local playback through a provider boundary, but playback completion still does not mean the underlying task succeeded or that the user heard it.

Recommended next phase: Voice-5 should add a narrow push-to-talk capture preparation layer or a real opt-in local playback provider, still disabled by default and still separate from wake word, VAD, Realtime, full interruption semantics, and continuous listening. It should preserve `source="voice"`, transcription/synthesis/playback provenance, trust gates, task graph behavior, verification posture, and the manual/mock paths as deterministic test seams.
