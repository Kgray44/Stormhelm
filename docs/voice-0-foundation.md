# Stormhelm Voice Foundation

This is the developer/foundation record for the voice subsystem. For user-facing setup, status, examples, and safety boundaries, use [voice.md](voice.md).

For the consolidated Voice-0 through Voice-20 release-readiness inventory, config matrix, authority matrix, smoke plan, and staging guidance, use [voice-c1-release-readiness.md](voice-c1-release-readiness.md).

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

Voice-9 adds:

- typed `VoiceInterruptionIntent`, `VoiceInterruptionRequest`, and `VoiceInterruptionResult` objects for output-only stop/suppress/mute behavior;
- `VoiceService.interrupt_voice_output(...)`, `VoiceService.stop_speaking(...)`, `VoiceService.suppress_current_response(...)`, and `VoiceService.set_spoken_output_muted(...)`;
- spoken output suppression checks before TTS and before playback, while preserving Core result and task state;
- interruption diagnostics for muted state, current-response suppression, last interruption, active playback interruptibility, and the invariant that Core tasks/results are not changed by stop-speaking;
- backend-owned API/UI actions for `voice.stopSpeaking`, `voice.suppressCurrentResponse`, `voice.muteSpokenResponses`, and `voice.unmuteSpokenResponses`;
- Ghost/Deck payload support for stop-speaking, muted/unmuted state, and output interruption status without adding task cancellation or Realtime barge-in;
- interruption events including `voice.interruption_requested`, `voice.interruption_completed`, `voice.interruption_blocked`, `voice.interruption_failed`, `voice.speech_suppressed`, `voice.spoken_output_muted`, and `voice.spoken_output_unmuted`.

Voice-10 adds:

- disabled-by-default `voice.wake` configuration for future wake word behavior;
- typed `VoiceWakeEvent`, `VoiceWakeSession`, and `VoiceWakeReadiness` objects;
- a backend-owned `WakeWordProvider` boundary with deterministic `MockWakeWordProvider` and unavailable/stub provider behavior;
- `VoiceService.wake_readiness_report(...)`, `start_wake_monitoring(...)`, `stop_wake_monitoring(...)`, `simulate_wake_event(...)`, `accept_wake_event(...)`, `reject_wake_event(...)`, `expire_wake_session(...)`, and `cancel_wake_session(...)`;
- wake diagnostics under `VoiceService.status_snapshot()["wake"]` that distinguish disabled, configured, available, monitoring, mock/dev provider state, cooldown, active session, and last wake event;
- backend API surfaces for wake readiness, mock simulation, accept/reject, cancel, and expire without UI/provider direct calls;
- wake events including `voice.wake_monitoring_started`, `voice.wake_monitoring_stopped`, `voice.wake_detected`, `voice.wake_rejected`, `voice.wake_session_started`, `voice.wake_session_expired`, `voice.wake_session_cancelled`, and `voice.wake_error`;
- tests proving mock wake does not start capture, call OpenAI, route Core, invoke STT/TTS/playback, expose raw audio, or imply real always-listening behavior.

Voice-11 adds:

- a disabled-by-default `LocalWakeWordProvider` behind the Voice-10 `WakeWordProvider` contract;
- a small `WakeBackend` abstraction and `UnavailableWakeBackend` default so missing local wake dependencies report typed unavailable states instead of silently falling back to mock;
- optional config fields for wake device, sample rate, backend label, model path, and sensitivity;
- local wake monitoring lifecycle behavior for explicitly enabled backends, including one active monitor at a time and truthful no-active stop results;
- local wake candidate handling with confidence threshold and cooldown enforcement, creating wake events and wake sessions without starting capture or routing Core;
- diagnostics and event payloads for wake backend, dependency, platform, device, permission, `cloud_used=false`, `openai_used=false`, and no raw audio exposure;
- tests proving local wake does not call OpenAI, use cloud services, start capture, invoke STT/TTS/playback, route Core, or expose dormant audio.

Voice-12 adds:

- typed `VoiceWakeGhostRequest` presentation state for accepted wake sessions;
- automatic wake-to-Ghost request/show behavior when a wake session is accepted;
- `VoiceService.create_wake_ghost_request(...)`, `show_wake_ghost(...)`, `expire_wake_ghost(...)`, `cancel_wake_ghost(...)`, and `get_active_wake_ghost_request(...)`;
- backend status under `status_snapshot()["wake_ghost"]` and `status_snapshot()["wake"]["ghost"]`;
- Ghost/Deck UI payload fields for wake Ghost active/requested/status/phrase/confidence/timeout, with `voice_core_state="wake_ready"` and no capture/listening/Core claims;
- wake-to-Ghost events including `voice.wake_ghost_requested`, `voice.wake_ghost_shown`, `voice.wake_ghost_expired`, `voice.wake_ghost_cancelled`, and `voice.wake_ghost_failed`;
- API surfaces for wake Ghost status and cancel/dismiss;
- tests proving wake-to-Ghost is presentation only and does not start capture, STT, Core routing, TTS, playback, Realtime, VAD, or OpenAI.

Voice-13R backfills:

- `VoicePostWakeConfig` and `[voice.post_wake]` configuration, disabled by default and gated separately from wake, capture, VAD, STT, TTS, playback, and Realtime;
- typed `VoicePostWakeListenWindow` records for the missing post-wake listen-window layer between wake-Ghost presentation and bounded capture;
- `VoiceService.open_post_wake_listen_window(...)`, `start_post_wake_capture(...)`, `complete_post_wake_capture(...)`, `submit_post_wake_listen_window(...)`, `cancel_post_wake_listen_window(...)`, `expire_post_wake_listen_window(...)`, and `get_active_post_wake_listen_window(...)`;
- status under `VoiceService.status_snapshot()["post_wake_listen"]` with active/last listen-window ID/status/expiry, capture/audio/VAD references, and truth flags that listen windows are bounded and do not route Core;
- post-wake listen events including `voice.post_wake_listen_opened`, `voice.post_wake_listen_started`, `voice.post_wake_listen_capture_started`, `voice.post_wake_listen_captured`, `voice.post_wake_listen_submitted`, `voice.post_wake_listen_expired`, `voice.post_wake_listen_cancelled`, and `voice.post_wake_listen_failed`;
- Voice-14 VAD binding and Voice-15 supervised-loop integration updated to use the concrete listen-window ID instead of a generated placeholder;
- tests proving accepted wake sessions can open one bounded listen window, rejected/expired windows do not route Core, capture metadata carries `listen_window_id`, VAD events bind to the window, and the wake loop uses the real window.

Voice-14/15/16 revalidation after Voice-13R confirms:

- VAD binds to the explicit listen window when present and still stops with capture/window expiry or cancellation;
- the wake-driven supervised loop carries `listen_window_id` through capture, STT, Core, and spoken-response events;
- spoken confirmation phrases from post-wake transcripts are evaluated only after STT and only through the trust binding model;
- `listen_window_id` is treated as provenance, not command authority or approval authority.

Voice-14 adds:

- `VoiceVADConfig` and `[voice.vad]` configuration, disabled by default and gated separately from wake, capture, STT, TTS, playback, and Realtime;
- `VoiceActivityDetector` provider interface plus `MockVADProvider` and `UnavailableVADProvider`;
- typed `VoiceActivityEvent`, `VoiceVADSession`, and `VoiceVADReadiness` models;
- VAD service methods for readiness, starting/stopping detection, and mock speech-started/speech-stopped simulation;
- capture-bound VAD startup/stop hooks so VAD can run only during an explicit capture/listen window and can optionally finalize capture on speech stop;
- VAD diagnostics/status, bridge payload fields, API readiness/simulation routes, and event taxonomy;
- tests proving VAD detects audio activity only, does not route Core, does not call STT directly, does not claim semantic completion, and does not expose raw audio.

Voice-15 adds:

- typed `VoiceWakeSupervisedLoopResult` records for the first complete wake-driven supervised loop;
- `VoiceService.run_wake_supervised_voice_loop(...)`, which composes accepted wake sessions, wake-to-Ghost presentation, the Voice-13R post-wake listen window, one bounded capture, optional mock VAD finalization, Voice-2 STT, the Voice-1 Core bridge, Voice-3 TTS, and Voice-4 playback;
- loop status under `VoiceService.status_snapshot()["wake_supervised_loop"]`, including readiness, active loop stage, final status, failed/stopped stage, and one-bounded-request truth flags;
- a backend API action at `/voice/wake/loop` returning the typed loop result plus fresh voice status;
- Ghost/Deck payload fields for the wake loop without adding a detached voice dashboard;
- correlated loop events `voice.wake_supervised_loop_started`, `voice.wake_supervised_loop_completed`, `voice.wake_supervised_loop_blocked`, and `voice.wake_supervised_loop_failed`;
- tests proving the loop stands down after one bounded request, preserves STT/Core/TTS/playback stage truth, respects mute/suppression, and does not introduce Realtime, cloud wake, or continuous listening.

Voice-16 adds:

- typed `VoiceSpokenConfirmationIntent`, `VoiceConfirmationBinding`, `VoiceSpokenConfirmationRequest`, and `VoiceSpokenConfirmationResult` records;
- conservative deterministic phrase classification for confirm/reject/cancel-pending/show-plan/repeat/explain-risk/wait/ambiguous responses;
- binding checks against the existing trust approval request, task, route family, payload hash, recipient/target where present, session, freshness, consumed state, and required confirmation strength;
- risk-sensitive phrase strength where casual acknowledgements cannot approve higher-risk prompts;
- once-only confirmation consumption through the existing trust service instead of a parallel approval path;
- manual voice and audio/STT turn interception for short confirmation phrases before generic Core routing when a pending confirmation context exists;
- backend API and UI bridge/client actions for spoken confirmation submission plus status inspection;
- Ghost/Deck payload fields for concise confirmation state, deeper binding/risk/freshness inspection, and the invariant that confirmation accepted is not action completed;
- confirmation events and audit records that distinguish received, classified, bound, accepted, consumed, rejected, expired, ambiguous, and failed states.

Voice-17 adds:

- expanded `VoiceInterruptionIntent` values plus typed `VoiceInterruptionClassification`, `VoiceInterruptionRequest`, and `VoiceInterruptionResult` fields for output, capture, listen-window, confirmation, Core-routed cancellation, correction, and ambiguous interruption cases;
- `VoiceService.classify_voice_interruption(...)` and `VoiceService.handle_voice_interruption(...)` as the backend-owned interruption resolver while preserving Voice-9 output methods;
- output interruption that reuses stop-speaking/mute/suppression and never cancels Core tasks or mutates Core results;
- capture/listen interruption that cancels the active bounded capture/listen/VAD path without submitting STT or routing Core;
- spoken-confirmation interruption that delegates to Voice-16 binding rules for `no`, `cancel that`, `show me the plan`, and `repeat that`;
- Core-routed cancellation/correction handling that sends phrases such as `cancel the task` or `actually open the docs instead` through the normal Voice-to-Core bridge with interruption provenance, without direct tool execution or direct task cancellation;
- interruption events including `voice.interruption_received`, `voice.interruption_classified`, `voice.barge_in_detected`, `voice.output_interrupted`, `voice.capture_interrupted`, `voice.listen_window_interrupted`, `voice.confirmation_interrupted`, `voice.core_cancellation_requested`, and `voice.correction_routed`;
- status/Ghost/Deck payload fields that distinguish output stopped, capture cancelled, listen window cancelled, confirmation rejected, Core cancellation requested, and correction routed while preserving `core_task_cancelled_by_voice=false` unless Core explicitly changes task state;
- focused tests in `tests/test_voice_barge_in_interruption.py`.

Voice-18 adds:

- `VoiceRealtimeConfig` and `[voice.realtime]` configuration, disabled by default, with `mode="transcription_bridge"`, `direct_tools_allowed=false`, `core_bridge_required=true`, and `audio_output_enabled=false`;
- `RealtimeTranscriptionProvider` plus deterministic `MockRealtimeProvider` and `UnavailableRealtimeProvider` boundaries;
- typed `VoiceRealtimeReadiness`, `VoiceRealtimeSession`, `VoiceRealtimeTranscriptEvent`, and `VoiceRealtimeTurnResult` models;
- service methods for Realtime readiness, bounded session start/close/cancel, mock/dev partial transcript simulation, final transcript simulation, and final transcript submission through the existing VoiceTurn/Core bridge;
- Realtime status under `VoiceService.status_snapshot()["realtime"]`, including active session/turn, bounded transcript previews, unavailable reasons, and truth flags for transcription-bridge-only behavior;
- API routes for `/voice/realtime/readiness`, `/voice/realtime/start`, `/voice/realtime/stop`, `/voice/realtime/partial`, and `/voice/realtime/final`;
- Ghost/Deck payload fields that identify Realtime as transcription bridge only, with direct tools disabled and speech-to-speech disabled;
- Realtime events including `voice.realtime_session_started`, `voice.realtime_session_closed`, `voice.realtime_partial_transcript`, `voice.realtime_final_transcript`, `voice.realtime_turn_created`, `voice.realtime_turn_submitted_to_core`, and `voice.realtime_turn_completed`;
- interruption integration that can cancel a bound Realtime transcription session without cancelling Core tasks;
- tests proving partial transcripts do not route Core, final transcripts create VoiceTurns through the existing bridge, confirmation/interruption laws still apply, provider-injected authority is ignored, no raw audio/secrets are exposed, and no live OpenAI calls occur in normal tests.

Voice-19 adds:

- explicit `speech_to_speech_core_bridge` Realtime mode fields on `VoiceRealtimeConfig`, still disabled by default and requiring `speech_to_speech_enabled=true`, `audio_output_from_realtime=true`, `direct_tools_allowed=false`, and `core_bridge_required=true`;
- typed Realtime speech session status fields for voice, Core bridge tool enablement, direct-action-tool exposure, last Core bridge call, last Core result state, and spoken-summary source;
- `stormhelm_core_request(...)` as the single Realtime-visible command/action/system bridge, implemented through the existing Voice/Core bridge rather than a second command router;
- strict Realtime session instructions that frame Realtime as Stormhelm's voice surface and require Core for actions, approvals, verification, completion claims, and uncertainty;
- response gating so Realtime speaks Core-provided `spoken_summary` only when Core allows speech, preserves `requires_confirmation`, `blocked`, `failed`, `attempted_not_verified`, `completed`, and `verified` result-state semantics, and blocks direct tool attempts;
- Voice-16 integration so Realtime transcript `yes`/`confirm` still uses spoken confirmation binding/freshness/consumption rules;
- Voice-17 integration so stop/cancel/correction phrases preserve interruption law and do not directly cancel Core tasks;
- Realtime speech events including `voice.realtime_speech_session_started`, `voice.realtime_core_bridge_call_started`, `voice.realtime_core_bridge_call_completed`, `voice.realtime_response_gated`, `voice.realtime_spoken_response_allowed`, and `voice.realtime_direct_tool_blocked`;
- status/Ghost/Deck payload fields that show `speech_to_speech_core_bridge`, `direct_tools_allowed=false`, `direct_action_tools_exposed=false`, Core bridge requirement, last Core result, and response-gating source;
- tests proving direct tools are not exposed, provider-injected authority is ignored, response claims are not strengthened, Voice-16/17 seams still apply, and no raw audio/secrets are exposed in status/events.

Voice-20 adds:

- `VoiceReleaseScenario`, `VoiceReleaseEvaluationResult`, and `VoiceLatencyBreakdown` in `src/stormhelm/core/voice/evaluation.py`;
- a default release scenario suite covering push-to-talk, wake-driven loop, Realtime transcription, Realtime speech Core bridge, spoken confirmation, interruption, correction, blocked results, attempted-not-verified results, playback failure, STT failure, empty transcript, provider unavailable, privacy/redaction, and Realtime authority boundaries;
- deterministic fake-clock latency breakdowns for wake, Ghost, listen window, capture, VAD, STT, Realtime partial/final transcript, Core bridge, spoken rendering, TTS, playback start, Realtime response gating, and total latency;
- release audit helpers for payload redaction, forbidden copy, result-state overclaims, direct Realtime tool exposure, partial-transcript Core routing, direct-tool blocked events that look executed, and confirmation-accepted events that overclaim action completion;
- a `voice_release_readiness_matrix()` helper used by tests/docs to keep implemented/default/provider/authority/test/caveat/release posture explicit;
- focused tests in `tests/test_voice_release_evaluation.py`, `tests/test_voice_latency_instrumentation.py`, and `tests/test_voice_release_hardening.py`.

Voice-I1 adds:

- `VoiceRuntimeModeReadiness` and `VoiceService.runtime_mode_readiness_report()` for selected/effective mode, ready/degraded/blocked/disabled status, missing requirements, contradictory settings, provider availability, and next-fix guidance;
- explicit runtime mode contracts for `disabled`, `manual_only`, `output_only`, `push_to_talk`, `wake_supervised`, `realtime_transcription`, and `realtime_speech_core_bridge`;
- output-only readiness that requires spoken responses, OpenAI TTS availability, and live playback availability instead of treating persisted TTS artifacts as speech;
- provider aggregation across TTS, STT, playback, capture, wake, VAD, Realtime, Core bridge, and trust/confirmation without adding new authority;
- Ghost/Deck/status payload fields for concise runtime mode readiness and live-playback truth;
- `scripts/voice_output_smoke.py` for mock-by-default output-only smoke and opt-in live TTS plus local playback smoke.

OpenAI voice boundary audit adds:

- explicit runtime/status truth that OpenAI voice is limited to STT transcript generation and TTS speech rendering;
- static tests proving OpenAI `/audio/transcriptions` and `/audio/speech` calls stay isolated to the voice provider module;
- tests proving STT does not return route/action/approval/result-state authority, and audio turns still route through the Voice-to-Core bridge;
- tests proving TTS speaks exactly the supplied Stormhelm-approved text and does not mutate or strengthen Core result state.

Still not implemented:

- automatic/background microphone capture;
- live microphone speech-to-text outside the controlled push-to-talk boundary;
- platform local audio playback without explicit `voice.playback` enablement/provider gates;
- WebRTC or WebSocket audio streaming;
- semantic VAD or request-completion inference;
- continuous listening or always-listening behavior;
- full Realtime barge-in command semantics;
- direct voice-layer Core task cancellation;
- direct voice command execution;
- frontend command authority;
- provider calls from UI;
- secret editing UI;
- direct tool execution from spoken confirmation;
- raw audio persistence by default;
- generated audio persistence by default;
- a detached voice UI or large settings dashboard.

Voice remains an input/output surface for Stormhelm. Speech-derived requests enter through the Core bridge or the existing planner/orchestrator boundary. Voice providers must not execute tools, lower trust requirements, or become a separate assistant path.

Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/bridge.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/events.py`, `src/stormhelm/core/voice/evaluation.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/voice_surface.py`, `config/default.toml`
Tests: `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_manual_turn.py`, `tests/test_voice_audio_turn.py`, `tests/test_voice_core_bridge_contracts.py`, `tests/test_voice_events.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_playback_service.py`, `tests/test_voice_pipeline_e2e.py`, `tests/test_voice_interruption_service.py`, `tests/test_voice_interruption_bridge.py`, `tests/test_voice_openai_boundary.py`, `tests/test_voice_post_wake_listen.py`, `tests/test_voice_wake_supervised_loop.py`, `tests/test_voice_realtime_transcription_bridge.py`, `tests/test_voice_realtime_speech_core_bridge.py`, `tests/test_voice_release_evaluation.py`, `tests/test_voice_latency_instrumentation.py`, `tests/test_voice_release_hardening.py`, `tests/test_voice_runtime_modes.py`
Additional Voice-10/11 tests: `tests/test_voice_wake_config.py`, `tests/test_voice_wake_service.py`, `tests/test_voice_local_wake_provider.py`

Availability law:

```text
voice available = voice.enabled
               && voice.mode != "disabled"
               && voice.provider == "openai"
               && openai.enabled
               && OpenAI API key is configured
               && configured voice OpenAI models are present
```

OpenAI Voice Boundary Law:

```text
OpenAI may hear the words and speak the words.
Stormhelm decides what the words mean.
```

STT is a transcript provider. TTS is a speech rendering provider. Realtime in Voice-18 is a transcription bridge, and Realtime in Voice-19 is a speech surface behind a strict Core bridge. None of these surfaces are command authority. OpenAI STT may convert bounded captured audio into transcript text, OpenAI Realtime may receive bounded active-session audio only after an explicit Realtime session starts, and OpenAI TTS or Realtime audio output may speak only Stormhelm-approved/gated text. OpenAI must not decide command intent, route commands, execute tools, approve actions, verify outcomes, determine task state, generate arbitrary spoken content independent of Core, or receive dormant wake audio. Realtime speech-to-speech must call `stormhelm_core_request` for commands/actions/system requests and preserve Core result state.

If a mock provider is active, diagnostics must say so. If a later feature is not implemented yet, diagnostics must report `not_implemented` or a truthful `no_*` runtime flag instead of implying listening, speaking, full Realtime conversation, or production audio playback support. Voice-2 supports controlled audio file/blob/fixture STT only; it must not imply live microphone capture or continuous listening. Voice-3 supports controlled TTS audio artifact generation only; it must not imply Stormhelm spoke aloud, that playback occurred, or that the user heard the response. Voice-4 can truthfully report controlled local playback through a provider boundary, but playback completion still does not mean the underlying task succeeded or that the user heard it. Voice-5 can truthfully report an explicit push-to-talk/manual capture boundary, but capture completion still does not mean transcription succeeded, Core understood intent, an action completed, TTS generated audio, playback occurred, or the user heard it. Voice-6A may record one explicitly started local capture when all gates and dependencies allow it; local capture availability still must not imply wake word, Realtime conversation, always-listening, continuous conversation, or command authority. Voice-6B may expose push-to-talk controls in Ghost/Deck, but those controls still only call backend `VoiceService` actions and must not call providers, tools, or Core directly from the frontend. Voice-7 may expose readiness and setup hints, but readiness still distinguishes enabled from available, available from active, capture from transcription, Core routing from action success, TTS generation from playback, and playback from the user hearing the response. Voice-8 evaluates the supervised push-to-talk pipeline with mocks/fakes by default and does not add new capture, wake word, Realtime, continuous listening, or command authority. Voice-9 can stop or suppress spoken output, but stop-speaking still does not cancel Core tasks, mutate Core results, undo actions, claim the user heard audio, or implement full Realtime barge-in. Voice-10 can represent wake readiness and mock wake events, but wake detection still does not start capture, invoke STT, route Core, open Ghost, execute commands, call OpenAI, or monitor the microphone in Dormant. Voice-11 can wrap a local wake backend when explicitly enabled, but local wake still does not start capture, route Core, open Ghost, use OpenAI/cloud wake detection, expose raw audio, or become command authority. Voice-12 can surface Ghost presentation from an accepted wake session, but Ghost wake state still does not mean request audio is being captured, STT occurred, Core understood, a VoiceTurn exists, TTS/playback occurred, or an action was requested. Voice-13R opens one bounded post-wake listen window after accepted wake/Ghost presentation, but the listen window itself still does not understand, transcribe, route, execute, or become command authority. Voice-14 can detect speech activity boundaries during an explicit capture/listen window, but speech stopped still does not mean request complete, command understood, confirmation intent, Core routing, or task success. Voice-15 can run one supervised wake-driven request through the existing voice chain, but it still does not create continuous listening, Realtime, cloud wake, or voice-driven task cancellation. Voice-16 can accept or reject one fresh matching trust prompt from spoken phrases, but "yes" is not global permission and confirmation accepted still does not mean action completed. Voice-17 can interrupt output/capture/listen/confirmation contexts, but it still does not directly cancel Core tasks or execute tools. Voice-18 can use Realtime as a bounded transcription bridge, but partial transcripts are provisional, final transcripts must become VoiceTurns through the existing Core bridge, and Realtime still cannot expose direct tools, approve actions, verify outcomes, mutate Core state, or detect wake. Voice-19 can use Realtime as a bounded speech-to-speech Core bridge, but commands/actions/system requests must call `stormhelm_core_request`, responses are gated by Core result state, direct tool attempts are blocked, and Core remains the only command authority. Voice-20 hardens and evaluates the full stack with mock/fake release scenarios, latency diagnostics, provider fallback checks, redaction audits, authority tripwires, event correlation checks, and UI truth checks; it adds no new command authority or live-provider behavior. Voice-I1 tightens runtime mode coherence and output-only live-playback readiness, but it still only reports/blocks incoherent settings and never enables new voice powers.

Recommended next phase: proceed only to release packaging or operator/live-provider smoke planning after reviewing Voice-20 caveats and keeping live OpenAI/Realtime tests opt-in.
