# Voice

Stormhelm voice is a bounded input/output surface. It is not an always-listening assistant, and it does not give audio providers authority to run commands. Voice requests enter the same backend-owned core path as typed requests.

Current status: implemented for Windows manual voice conversations and Windows typed-response voice output when explicitly enabled. Typed `/chat/send` responses now leave a safe `VOICE_SPEAK_DECISION` trail, then speak user-facing assistant text through OpenAI streaming TTS and progressive Windows local speaker playback when the voice gates allow it. Stormforge Anchor audio-reactive motion uses a backend PCM stream meter with startup preroll and exposes only scalar visual energy. The main supported input loop is explicit user-triggered listen, default microphone capture, silence endpointing, OpenAI STT, normal Core dispatch, visible response, and spoken response through the existing Windows local speaker playback path. Voice remains disabled by default.

For the Voice-C1 phase inventory, config matrix, authority boundary matrix, release notes, live-provider smoke plan, test commands, and commit hygiene guidance, see [voice-c1-release-readiness.md](voice-c1-release-readiness.md).

Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/bridge.py`, `config/default.toml`
Tests: `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_manual_turn.py`, `tests/test_voice_audio_turn.py`, `tests/test_voice_core_bridge_contracts.py`

## What Works

| Capability | Current behavior | Enabled by default? | Sources | Tests |
|---|---|---:|---|---|
| Manual voice turns | Text treated as a voice-originated turn and sent through the core bridge. | Partly; voice is off by default but manual input config defaults true. | `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/bridge.py` | `tests/test_voice_manual_turn.py`, `tests/test_voice_core_bridge_contracts.py` |
| Windows manual voice conversation | A Ghost/Deck/API listen action opens the default microphone, records one utterance, endpoints after silence/max duration/no speech/cancel, transcribes through OpenAI STT, submits the transcript through the normal Core bridge, surfaces the transcript/result in voice status, and speaks the Core-approved response through the configured Windows local speaker path. | No | `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/controllers/main_controller.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_l6_manual_conversation.py`, `tests/test_voice_bridge_controls.py`, `tests/test_voice_config.py` |
| Controlled audio STT | Bounded file/blob/fixture-style audio metadata can be transcribed through the configured provider path. | No | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_audio_turn.py`, `tests/test_voice_stt_provider.py` |
| TTS artifact generation | Core-approved text or explicit safe test text can be rendered into a controlled speech artifact. | No | `src/stormhelm/core/voice/speech_renderer.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_tts_provider.py`, `tests/test_voice_tts_from_turn_result.py` |
| Streaming TTS output | Core-approved spoken text can optionally use a chunked TTS contract with redacted chunk metadata and first-audio timing. L5.1 wires normal `/chat/send` assistant voice output and capture play-response through streaming when streaming TTS and streaming playback are enabled. L5.3 adds a null streaming playback sink for device-independent first-output timing and routes the wake supervised loop through the same approved streaming path when playback is requested. L5.4/L5.5 add Windows local speaker progressive playback for PCM chunks and carry speaker truth into status/UI state. L5.6 records the typed-response speech decision for every `/chat/send` response and keeps the utility/time route speakable through the same path. Streaming never starts from partial transcripts, wake alone, STT final alone, or unapproved filler. | No | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_chat_output_integration.py`, `tests/test_latency_l5_voice_streaming_first_audio.py`, `tests/test_latency_l51_voice_streaming_reality.py`, `tests/test_latency_l53_live_voice_benchmark.py`, `tests/test_latency_l55_windows_voice_runtime.py`, `tests/test_voice_playback_provider.py` |
| Voice anchor visual state | Backend status exposes a `voice_anchor` payload for Ghost motion: dormant, idle, wake detected, listening, transcribing, thinking, confirmation required, preparing speech, speaking, interrupted, muted, continuing task, blocked, and error. Stormforge production audio-reactive motion uses the scalar `pcm_stream_meter` visual payload and never carries raw audio. AR4 names the approved renderer `legacy_blob_reference`, keeps `legacy_blob` as a compatibility alias, adds an opt-in `legacy_blob_fast_candidate` parity mode, and preserves the rejected AR3 split renderer behind an explicit experiment flag. AR5 adds the opt-in `legacy_blob_qsg_candidate` scene-graph/Shape clone for performance review; it is not default until human visual parity review accepts it. | No | `src/stormhelm/core/voice/voice_visual_meter.py`, `src/stormhelm/core/voice/visualizer.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/ui/voice_surface.py`, `assets/qml/components/VoiceCore.qml`, `assets/qml/variants/stormforge/StormforgeAnchorCore.qml`, `assets/qml/variants/stormforge/StormforgeAnchorFrame.qml`, `assets/qml/variants/stormforge/StormforgeAnchorDynamicCore.qml`, `assets/qml/variants/stormforge/StormforgeAnchorLegacyBlobQsgCore.qml` | `tests/test_voice_visual_meter.py`, `tests/test_latency_l52_voice_anchor_motion.py`, `tests/test_voice_ui_state_payload.py`, `tests/test_stormforge_voice_visual_meter_contract.py`, `tests/test_qml_shell.py` |
| Push-to-talk capture boundary | Explicit start/stop/cancel/submit actions exist. L6 adds one-shot `listen-turn`, which uses the same capture provider and endpointing path instead of requiring a manual stop before STT/Core dispatch. Local capture is separately gated. | No | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_capture_service.py`, `tests/test_voice_bridge_controls.py`, `tests/test_voice_l6_manual_conversation.py` |
| Playback boundary | Playback requests and stop controls exist behind provider/config gates. Voice-LP1 adds a real Windows local playback provider for MP3/WAV output while preserving mock/unavailable paths. L5 adds live stream/chunk contracts and prewarm status while keeping artifact persistence separate from live playback truth. L5.3 adds `null_stream`, a silent streaming sink that measures first accepted output without claiming audible playback. L5.4/L5.5 wire the Windows local provider to progressive PCM streaming through the system speaker output, expose `speaker_backend_available`, and set `user_heard_claimed=true` only after the local speaker sink starts. | No | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_playback_service.py`, `tests/test_voice_playback_provider.py`, `tests/test_latency_l5_voice_streaming_first_audio.py`, `tests/test_latency_l53_live_voice_benchmark.py`, `tests/test_latency_l55_windows_voice_runtime.py` |
| Interruption and barge-in hardening | Active playback can be stopped, spoken output muted, capture/listen windows cancelled, pending confirmations rejected, and cancellation/correction phrases routed safely without direct task cancellation. | No; controlled by explicit action or bounded voice context. | `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_interruption_service.py`, `tests/test_voice_interruption_bridge.py`, `tests/test_voice_barge_in_interruption.py` |
| Wake word foundation | Wake config, provider contracts, mock wake events, wake sessions, readiness, diagnostics, and events exist without real wake listening. | No | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py` | `tests/test_voice_wake_config.py`, `tests/test_voice_wake_service.py` |
| Local wake provider boundary | A disabled-by-default `LocalWakeWordProvider` can wrap an optional local backend and report dependency/platform/device/permission state. | Only when explicitly enabled and the local backend is available. | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_local_wake_provider.py` |
| Wake-to-Ghost presentation | Accepted wake sessions can create a backend-owned Ghost presentation request with wake-ready status and timeout/cancel behavior. | Presentation only; no request audio capture. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_wake_ghost_service.py`, `tests/test_voice_wake_ghost_payload.py` |
| Post-wake listen window | Voice-13R backfills the explicit one-utterance listen window between wake-Ghost and capture. It binds to an accepted wake session, can expire/cancel, and does not route Core. | No; it is a bounded opportunity to capture one request. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_post_wake_listen.py` |
| Wake-driven supervised loop | Accepted wake sessions can run one bounded wake -> Ghost -> post-wake listen window -> capture -> STT -> Core -> approved speech/TTS -> playback loop, then stand down. When streaming TTS/playback are enabled, requested playback uses the Core-approved streaming output path and reports `wake_loop_streaming_output_used`; wake alone and STT final alone still do not authorize speech. | No; requires explicit wake/listen/capture/STT/TTS/playback gates. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py` | `tests/test_voice_wake_supervised_loop.py`, `tests/test_latency_l53_live_voice_benchmark.py` |
| VAD / end-of-speech | The Windows local capture backend computes safe PCM level metadata during an explicit listen session, marks speech start, endpoints after configurable silence, and returns `speech_ended`, `max_duration`, `cancelled`, `no_speech_detected`, or `mic_error`. The older mock VAD provider remains available for isolated tests. | No; enabled only for explicit voice input sessions. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_l6_manual_conversation.py`, `tests/test_voice_vad_config.py`, `tests/test_voice_vad_provider.py`, `tests/test_voice_vad_service.py` |
| Spoken confirmation handling | Short confirmation/rejection/control phrases are classified deterministically and can bind only to a fresh pending trust confirmation. | Yes, but inert without a pending confirmation. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_spoken_confirmation.py` |
| Realtime transcription bridge | OpenAI Realtime can be represented as a disabled-by-default transcription bridge. Mock/dev sessions can produce partial transcript status and final transcripts that become VoiceTurns through the existing Core bridge. | No; disabled and dev-gated by default. | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py` | `tests/test_voice_realtime_transcription_bridge.py` |
| Realtime speech-to-speech Core bridge | OpenAI Realtime speech sessions can be represented as a disabled-by-default audio conversation surface. Command/action/system turns must call `stormhelm_core_request`; responses are gated by Core result state and spoken summary. | No; explicit speech/audio flags and dev gates are required. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_realtime_speech_core_bridge.py` |
| Voice release hardening | Voice-20 adds mock/fake release scenarios, deterministic latency diagnostics, provider fallback checks, redaction audits, Realtime authority tripwires, event correlation checks, and Ghost/Deck/status truth checks. | Diagnostic only. | `src/stormhelm/core/voice/evaluation.py` | `tests/test_voice_release_evaluation.py`, `tests/test_voice_latency_instrumentation.py`, `tests/test_voice_release_hardening.py` |
| OpenAI STT/TTS boundary | OpenAI may transcribe bounded audio and synthesize approved speech text only. It is not voice command authority. | No | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_openai_boundary.py` |
| Ghost/Deck voice state | The bridge maps backend voice status into compact UI state and voice actions. L5.5 exposes playback provider, speaker backend availability, speaking state, and speaker-only `user_heard_claimed` truth to the UI state payload. L5.6 adds `runtime_gate_snapshot`, `typed_response_speech_enabled`, `last_voice_speak_decision`, and skip reasons so a visible text response that does not speak can be diagnosed from `/status`, `/snapshot`, events, and UI state. | UI depends on current worktree files. | `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/controllers/main_controller.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_ui_state_payload.py`, `tests/test_voice_bridge_controls.py`, `tests/test_voice_chat_output_integration.py`, `tests/test_latency_l55_windows_voice_runtime.py` |

## What Does Not Work Yet

| Request | Current answer |
|---|---|
| Always-listening mode | Not implemented. |
| Robust always-on local wake word | Not implemented. Wake provider boundaries remain disabled unless explicitly configured, and background room audio is not sent to OpenAI for wake detection. |
| Continuous post-wake listening | Not implemented. Voice-13R/15 handle one bounded post-wake listen window/request only, then return to idle/Dormant. |
| Continuous microphone capture | Not implemented. L6 supports the explicit one-utterance Windows manual listen path. |
| Unbounded Realtime conversation | Not implemented. Voice-19 speech mode is bounded, explicitly started, and still Core-bridged. |
| Semantic VAD / request completion | Not implemented. VAD detects audio activity only. |
| OpenAI Realtime direct actions or direct Core task cancellation | Not implemented and not allowed. Voice-19 exposes only `stormhelm_core_request`; cancellation/correction still routes through Core/task/trust. |
| Voice provider executing tools directly | Not allowed by design. |
| Independent proof that the human heard audio | Not implemented. `user_heard_claimed=true` is allowed only when the real local speaker sink successfully starts output; mock and `null_stream` keep it false. |
| Automatic live OpenAI smoke in CI | Not enabled. Live smoke is opt-in only because it spends provider credits. Use `scripts/voice_first_audio_smoke.py --mode openai-stream --sink-kind null_stream` or `--sink-kind speaker`, gated by `STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE=1`, `STORMHELM_OPENAI_ENABLED=1`, and `OPENAI_API_KEY`; otherwise the artifact is an honest skip. |
| Cross-platform live speaker streaming | Not implemented. L5.4 provides the Windows local speaker sink first; unsupported platforms/backends report typed unsupported state. |

Sources: `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/service.py`, `docs/voice-0-foundation.md`
Tests: `tests/test_voice_availability.py`, `tests/test_voice_events.py`, `tests/test_voice_state.py`

## OpenAI Voice Boundary Law

OpenAI may hear the words and speak the words. Stormhelm decides what the words mean.

STT is a transcript provider. TTS is a speech rendering provider. Realtime in Voice-18 is a transcription bridge; Voice-19 adds speech-to-speech only as an audio surface behind the strict `stormhelm_core_request` bridge. None of these surfaces are command authority. OpenAI STT may convert bounded captured audio into transcript text, OpenAI Realtime may receive bounded active-session audio only after an explicit Realtime session starts, and OpenAI TTS or Realtime audio output may speak only Stormhelm-approved/gated text. Partial Realtime transcripts are provisional status only. Final Realtime command/action/system turns must go through Stormhelm Core, which owns routing, trust, approvals, task state, verification, and result-state truth. L5 streaming TTS still waits for Core-approved spoken text and `speak_allowed=true`; provider/playback prewarm prepares clients and sinks only, without sending final text, starting playback, routing commands, or granting authority. OpenAI must not decide command intent, route commands, execute tools, approve actions, verify outcomes, determine task state, or invent success/verification claims independent of Core.

Sources: `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/bridge.py`
Tests: `tests/test_voice_openai_boundary.py`

## Check Voice Status

Start the core, then query status:

```powershell
.\scripts\run_core.ps1
Invoke-RestMethod http://127.0.0.1:8765/status | Select-Object -ExpandProperty voice
```

Useful fields to inspect:

| Field family | Meaning |
|---|---|
| availability | Whether voice is available and why not. |
| manual input | Whether manual transcript turns are enabled. |
| voice_input | L6 safe input status: enabled gates, microphone availability, providers, wake/push-to-talk gates, current state, active session/capture, last listen result, last transcription result, last Core dispatch result, last spoken result, skip/degraded reason, and raw audio/secret flags. |
| capture | Whether capture is enabled, active, blocked, or recently completed. |
| transcription | Last STT provider/model/result/error state. |
| speech synthesis | Last TTS request/result/artifact state, streaming TTS status, live/artifact formats, provider prewarm state, fallback use, and first-audio timing. |
| playback | Last playback request/result/error state, live stream status, playback prewarm state, partial-playback state, and stop-speaking availability. |
| voice visual meter | Stormforge audio-reactive scalar fields: `voice_visual_energy`, `voice_visual_active`, `voice_visual_source`, `voice_visual_playback_id`, `voice_visual_available`, `voice_visual_disabled_reason`, `voice_visual_sample_rate_hz`, `voice_visual_started_at_ms`, `voice_visual_latest_age_ms`, and `raw_audio_present=false`. |
| interruption | Last interruption request/classification/result, affected output/capture/listen/confirmation surfaces, Core-routed cancellation/correction flags, and invariants that voice did not cancel tasks or mutate Core results directly. |
| wake | Wake config/readiness/provider/backend/device/session/event/Ghost presentation status. Local wake remains disabled unless explicitly configured and available. |
| wake_ghost | Active/last wake-to-Ghost presentation state, including request/session IDs, phrase, timeout, and presentation-only truth flags. |
| post_wake_listen | Active/last post-wake listen-window ID/status/expiry, capture/audio/VAD references, and truth flags that the window is bounded and does not route Core. |
| wake_supervised_loop | Readiness, active loop stage, final status, stopped/failed stage, and one-bounded-request truth flags for the wake-driven loop. |
| vad | VAD config/readiness/provider/session/activity status. Speech activity is not command intent or semantic completion. |
| spoken_confirmation | Confirmation classifier/binding/result status, pending count, freshness/strength settings, and truth flags that confirmation does not execute actions. |
| realtime | Realtime config/readiness/session/transcript/Core-bridge status, including `direct_tools_allowed=false`, `direct_action_tools_exposed=false`, `core_bridge_required=true`, speech mode flags, last Core result state, and response-gating source. |
| runtime_mode | Selected/effective voice mode, readiness, missing requirements, contradictory settings, provider availability, and the next settings fix. |
| runtime_gate_snapshot | Safe startup/current gate snapshot: `.env` loaded, OpenAI key present, OpenAI enabled, voice enabled, spoken responses enabled, playback provider, streaming playback, live format, dev playback, and raw-secret/audio logging flags. |
| last_voice_speak_decision | Last typed-response speech decision: request/session, prompt source, text/spoken-text lengths, speakable/skipped reason, whether the voice service was called, playback provider, streaming posture, completion status, and `user_heard_claimed` only after real speaker playback starts. |
| truth flags | Explicit no-wake-word/no-realtime/no-always-listening style flags. |

Sources: `src/stormhelm/core/container.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/state.py`
Tests: `tests/test_voice_state.py`, `tests/test_voice_diagnostics.py`

## Stormforge Voice-Reactive Renderer Probe

The real environment probe exercises the production Core, UI, Stormforge Ghost, local playback fixture, bridge, QML binding path, and Anchor renderer diagnostics. It logs only scalar energy, timing, and visual-drive fields.

```powershell
python scripts\run_voice_reactive_real_environment_probe.py --stormforge --fog on --clear-cache --spoken-prompt "Testing one, two, three. Anchor sync check." --audible --use-local-pcm-voice-fixture --timeout-seconds 24
```

AR4 renderer selection:

- Default: `legacy_blob_reference`, with `legacy_blob` kept as a compatibility alias. This is the approved organic blob look and keeps the scalar PCM voice chain.
- Candidate: `legacy_blob_fast_candidate`, selected with `STORMHELM_STORMFORGE_ANCHOR_RENDERER=legacy_blob_fast_candidate` or `--anchor-renderer legacy_blob_fast_candidate`. It is for visual parity/performance review only and is not promoted until the reference look is manually accepted.
- Candidate: `legacy_blob_qsg_candidate`, selected with `STORMHELM_STORMFORGE_ANCHOR_RENDERER=legacy_blob_qsg_candidate` or `--anchor-renderer legacy_blob_qsg_candidate`. It uses the cached static frame plus a scene-graph/Shape clone of the official legacy blob aperture. It remains opt-in until the visual parity artifacts are accepted.
- Experiment: `ar3_split`, selected with `STORMHELM_STORMFORGE_ANCHOR_RENDERER=ar3_split` or `--anchor-renderer ar3_split`, for future performance work only.

Key AR3/AR4 fields:

| Field | Meaning |
|---|---|
| `effectiveAnchorRenderer` | Active renderer: `legacy_blob_reference` by default, `legacy_blob_fast_candidate` for AR4 parity review, `legacy_blob_qsg_candidate` for AR5 visual-parity/performance review, or `ar3_split` for explicit experiments. |
| `anchorRequestPaintFpsDuringSpeaking` | Coalesced dynamic paint requests during speaking. |
| `anchorPaintFpsDuringSpeaking` / `dynamicCorePaintFpsDuringSpeaking` | Actual dynamic Anchor paint cadence. Target is at least 30 FPS while visible/speaking. |
| `staticFramePaintFpsDuringSpeaking` | Should stay low; static frame should not repaint on every voice-energy frame. |
| `blobScaleDrive`, `blobDeformationDrive`, `radianceDrive`, `ringDrive` | Scalar visual drives proving the organic blob/radiance/fragments still respond to voice energy. |
| `visualAmplitudeCompressionRatio` / `visualAmplitudeLatencyMs` | Bounded expression and timing checks between received voice energy and visual drive. |
| `pcm_to_finalSpeakingEnergy`, `pcm_to_blobScaleDrive` | Best-lag audible PCM-to-visual alignment estimates. If direct correlation is weak, AR4 falls back to scalar stage latency such as `pcm_to_paint_estimated` instead of guessing from sparse rows. |
| `perceptual_sync_status` | `aligned`, `visual_late`, `visual_early`, or `inconclusive` for real audible-path sync. |
| `midSpeechSpeakingVisualFalseRows`, `midSpeechAnchorIdleRows`, `anchorStatusGlitchDetected` | Production-path counters for the anchor dropping back to idle or non-speaking after speaking has already started. |

Visual artifacts can be regenerated without live audio:

```powershell
python scripts\run_stormforge_anchor_ar3_visual_artifacts.py
python scripts\run_stormforge_anchor_legacy_blob_visual_artifacts.py
python scripts\run_stormforge_anchor_ar4_visual_parity_artifacts.py
```

AR3 split artifacts land under `.artifacts\voice_ar3_visual_equivalence`. AR3-R legacy blob artifacts land under `.artifacts\voice_ar3r_visual_revert`. AR4 parity artifacts land under `.artifacts\voice_ar4_visual_parity` and include side-by-side reference/candidate idle, low/high speaking, state-set, and blob-sequence captures. They do not contain raw audio.

## Runtime Modes

Voice-I1 adds a backend-owned runtime mode readiness report. It does not enable new voice powers; it explains whether the selected mode is actually coherent with the enabled providers and subcomponents.

Supported runtime modes:

| Mode | Requires | Expected off posture | Common blocker |
|---|---|---|---|
| `disabled` | Voice disabled. | Everything inactive. | None; this is the safe default. |
| `manual_only` | Voice enabled and manual input enabled. | Capture/wake/Realtime can remain off. | Manual input disabled. |
| `output_only` | Voice enabled, spoken responses enabled, OpenAI TTS available, local playback enabled and available. | Capture, wake, post-wake listen, VAD, and Realtime disabled. | `output_voice_configured_but_playback_disabled` or `output_voice_configured_but_playback_unavailable`. |
| `push_to_talk` | Capture enabled and available; OpenAI STT available. | Wake/post-wake/Realtime disabled. | Capture or STT unavailable. |
| `wake_supervised` | Local wake, post-wake listen, capture, OpenAI STT, and Core bridge available. | Realtime disabled. | Wake, post-wake, capture, STT, or Core bridge unavailable. |
| `realtime_transcription` | Realtime enabled in transcription bridge mode and Core bridge available. | Direct Realtime tools disabled. | Realtime unavailable or direct tools enabled. |
| `realtime_speech_core_bridge` | Realtime enabled in speech Core-bridge mode with audio output and Core bridge available. | Direct Realtime tools disabled. | Speech flags, Realtime provider, or Core bridge unavailable. |

The report is available in `voice.runtime_mode` and is also carried into Ghost/Deck payloads. `selected_mode` is the configured mode; `effective_mode` is what Stormhelm can actually evaluate after `voice.enabled`; `status` is `ready`, `degraded`, `blocked`, or `disabled`; `next_fix` is the most direct settings change.

Artifact persistence is deliberately separate from live playback. `voice.openai.persist_tts_outputs=true` can keep a generated file for debugging, but it never satisfies output-only live speech. If output-only mode is selected and playback is disabled or unavailable, Stormhelm reports that it cannot speak live.

Streaming TTS is also separate from artifact persistence. `voice.openai.stream_tts_outputs=true` asks the provider layer for chunks in `voice.openai.tts_live_format` such as `pcm`; `voice.openai.tts_artifact_format` remains the optional file/debug format. L5.1 selects `VoiceService.stream_core_approved_spoken_text` for normal `/chat/send` assistant voice output and capture play-response when both streaming TTS and streaming playback are enabled. OpenAI provider output is labeled `true_http_stream` for the HTTP streaming path and `buffered_chunk_projection` when a buffered helper is chunked for compatibility. `voice.openai.streaming_fallback_to_buffered` and `voice.playback.streaming_fallback_to_file` make fallback explicit in status and latency metadata. Fallback must not hide the original streaming failure or create duplicate speech.

First-audio metrics live in voice status and latency summaries:

- `core_result_to_tts_start_ms`
- `tts_start_to_first_chunk_ms`
- `first_chunk_to_playback_start_ms`
- `first_chunk_to_sink_accept_ms`
- `core_result_to_first_audio_ms`
- `core_result_to_first_output_start_ms`
- `request_to_first_audio_ms`
- `first_output_start_ms`
- `null_sink_first_accept_ms`
- `sink_kind`
- `first_audio_available`
- `first_audio_budget_exceeded`
- `partial_playback`
- `user_heard_claimed` (`false` for mock/null sinks; `true` only after the real local speaker sink starts output)

L5.1 adds transport and normal-path proof fields:

- `streaming_transport_kind` / `voice_streaming_transport_kind`
- `first_chunk_before_complete`
- `voice_stream_used_by_normal_path`
- `voice_streaming_miss_reason`
- `streaming_tts_status`
- `live_playback_status`

L5.3 adds live-proof and null-sink fields:

- `sink_kind` / `voice_sink_kind`
- `first_chunk_to_sink_accept_ms`
- `first_output_start_ms` / `voice_first_output_start_ms`
- `null_sink_first_accept_ms` / `voice_null_sink_first_accept_ms`
- `live_openai_voice_smoke_run`
- `wake_loop_streaming_output_used`
- `wake_loop_streaming_miss_reason`
- `realtime_deferred_to_l6`

The null sink is a timing sink, not a speaker. `null_stream` proves the pipeline accepted the first safe audio chunk; it does not prove audible output or user hearing. The Windows local speaker sink is selected with playback provider `local` or smoke `--sink-kind speaker`; it accepts progressive PCM chunks and reports playback start only after the output device accepts audio.

L5.2 adds a backend-owned visual contract for the Ghost voice anchor:

- `voice_anchor.state` is one of `dormant`, `idle`, `wake_detected`, `listening`, `transcribing`, `thinking`, `confirmation_required`, `preparing_speech`, `speaking`, `interrupted`, `muted`, `continuing_task`, `blocked`, or `error`.
- `speaking_visual_active=true` only follows output/playback/first-audio evidence. `preparing_speech` is not speaking.
- `audio_reactive_source` is one of `playback_output_envelope`, `streaming_chunk_envelope`, `precomputed_artifact_envelope`, `synthetic_fallback_envelope`, or `unavailable`.
- `synthetic_fallback_envelope` is allowed for useful motion, but it is labeled and `audio_reactive_available=false`.
- `user_heard_claimed` remains part of the payload. It is false for mock/null paths and true only after the real local speaker sink starts output. Anchor motion is not completion, verification, command authority, or proof from an independent human-heard sensor.

Playback started means a playback provider accepted audio. It does not change Core result state, task completion, or verification. The `user_heard_claimed` flag remains false for mock/null sinks and becomes true only for the real speaker sink after output starts.

For a deterministic no-sound first-audio smoke, run:

```powershell
python scripts\voice_first_audio_smoke.py --mode mock-stream --output-dir .artifacts\voice-first-audio-smoke
```

The smoke writes `voice_first_audio_smoke_summary.json`, `voice_first_audio_smoke_events.jsonl`, and `voice_first_audio_smoke_report.md` with sanitized timing rows and no audio bytes. `--mode openai-stream` is an opt-in live check and reports skipped unless the required environment gates are set. Check the local gates without revealing the key:

```powershell
python scripts\voice_first_audio_smoke.py --print-env-gates
```

For a broader runtime check, including `.env` loading, speaker backend posture,
and the fact that normal app runtime does not require the live-smoke gate, run:

```powershell
python scripts\voice_doctor.py
```

For a live OpenAI-to-Windows-speaker smoke, use:

```powershell
python scripts\voice_first_audio_smoke.py --mode openai-stream --sink-kind speaker --output-dir .artifacts\voice_progressive_speaker_smoke
```

Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/visualizer.py`, `src/stormhelm/ui/voice_surface.py`, `assets/qml/components/VoiceCore.qml`
Tests: `tests/test_voice_runtime_modes.py`, `tests/test_voice_readiness.py`, `tests/test_voice_ui_state_payload.py`, `tests/test_latency_l51_voice_streaming_reality.py`, `tests/test_latency_l52_voice_anchor_motion.py`

## Enable For Development

Voice availability depends on both voice settings and OpenAI settings.

```powershell
$env:STORMHELM_OPENAI_ENABLED = "true"
$env:OPENAI_API_KEY = "<your key>"
$env:STORMHELM_VOICE_ENABLED = "true"
$env:STORMHELM_VOICE_MODE = "manual"
$env:STORMHELM_VOICE_MANUAL_INPUT_ENABLED = "true"
$env:STORMHELM_VOICE_PUSH_TO_TALK_ENABLED = "true"
$env:STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED = "true"
$env:STORMHELM_VOICE_DEBUG_MOCK_PROVIDER = "false"
$env:STORMHELM_VOICE_INPUT_ENABLED = "true"
$env:STORMHELM_VOICE_MICROPHONE_ENABLED = "true"
$env:STORMHELM_VOICE_CAPTURE_PROVIDER = "local"
$env:STORMHELM_VOICE_WAKE_ENABLED = "false"
$env:STORMHELM_VOICE_STT_PROVIDER = "openai"
$env:STORMHELM_VOICE_INPUT_LANGUAGE = "en"
$env:STORMHELM_VOICE_VAD_ENABLED = "true"
$env:STORMHELM_VOICE_ENDPOINT_SILENCE_MS = "700"
$env:STORMHELM_VOICE_MAX_UTTERANCE_SECONDS = "20"
$env:STORMHELM_VOICE_OPENAI_STREAM_TTS_OUTPUTS = "true"
$env:STORMHELM_VOICE_OPENAI_TTS_LIVE_FORMAT = "pcm"
$env:STORMHELM_VOICE_PLAYBACK_ENABLED = "true"
$env:STORMHELM_VOICE_PLAYBACK_PROVIDER = "local"
$env:STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK = "true"
$env:STORMHELM_VOICE_PLAYBACK_STREAMING_ENABLED = "true"
.\scripts\run_core.ps1
```

The same values can live in the local `.env`; `.env` is ignored by git. OpenAI-backed STT/TTS also uses `voice.openai.*` settings from `config/default.toml`.

To hear typed Stormhelm responses through Windows speakers:

1. Put the enablement values above in your local `.env`, including `STORMHELM_VOICE_PLAYBACK_PROVIDER=local` and `STORMHELM_VOICE_OPENAI_TTS_LIVE_FORMAT=pcm`.
2. Run `python scripts\voice_doctor.py` and confirm `OPENAI_API_KEY=present`, OpenAI/voice/playback gates are enabled, `speaker_backend_available=true`, and `raw_secret_logged=false`.
3. Launch the normal app stack with `.\scripts\run_core.ps1` and `.\scripts\run_ui.ps1`.
4. Type a prompt in the UI. The text response is still shown normally; when speech is allowed, the approved spoken response is sent to `VoiceService.stream_core_approved_spoken_text`, streamed through OpenAI TTS, and fed to the Windows local speaker sink progressively.
5. Stop active speech from the UI stop-speaking action or with `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/output/stop-speaking -ContentType 'application/json' -Body '{}'`.

To run the full manual voice conversation loop, launch the normal core/UI stack with the same gates, then press the Ghost or Deck `Listen` voice action. The action path is `UiBridge.listenAndSubmitTurn` -> `StormhelmCoreClient.listen_and_submit_voice_turn` -> `POST /voice/capture/listen-turn` -> `VoiceService.listen_and_submit_turn`.

The runtime then:

1. Stops current speech first if a manual listen starts while Stormhelm is speaking.
2. Opens the default microphone through `LocalCaptureProvider` and `SoundDeviceWavCaptureBackend`.
3. Records one utterance without logging or persisting raw audio by default.
4. Uses amplitude/silence endpointing to stop on speech end, max duration, cancel, no speech, or mic error.
5. Transcribes the captured audio with the configured OpenAI STT model only after the explicit listen session is active.
6. Submits the transcript as `source=voice` through `VoiceService.submit_voice_core_request`, which calls the same Core bridge used by typed chat.
7. Shows the transcript and Core result in voice status/UI payloads.
8. Speaks the Core-approved spoken response through streaming TTS plus Windows local speaker playback when speech/playback gates allow it.

The live-smoke gate `STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE=1` is required only for explicit smoke scripts that spend OpenAI credits. Normal app runtime uses `OPENAI_API_KEY`, `STORMHELM_OPENAI_ENABLED=1`, and the voice/playback gates above; it does not require the smoke gate.

To exercise the normal typed Core path instead of only the lower-level voice backend, run:

```powershell
python scripts\voice_typed_response_smoke.py --prompt "what time is it" --speak --sink-kind speaker --output-dir .artifacts\voice_typed_response_speaker_smoke
```

This sends a real `/chat/send` request, waits for the voice decision/status to settle, and writes `voice_typed_response_smoke.json` with `text_response_received`, `approved_spoken_text_present`, `voice_service_called`, first-chunk/first-speaker-output timings, `skipped_reason`, `user_heard_claimed`, and raw-secret/audio flags. It does not print secrets or audio bytes.

## Typed Response Speech Troubleshooting

If the UI shows the text response but you do not hear speech, check `/status` or `/snapshot` under `voice.runtime_gate_snapshot` and `voice.last_voice_speak_decision`, or inspect recent `voice.speak_decision` events. The event message is `VOICE_SPEAK_DECISION` and contains no response text beyond lengths.

| Symptom | What to inspect | Typical fix |
|---|---|---|
| Text appears but no `last_voice_speak_decision` | Core process may be stale or not running the current source. | Restart Core with `.\scripts\run_core.ps1`; verify `/health` PID changed if needed. |
| `env_loaded=false` | Normal runtime did not find the local `.env`. | Launch from the Stormhelm source/runtime root or fix project-root discovery. |
| `openai_key_present=false` | `.env` or environment lacks `OPENAI_API_KEY`. | Add the key locally; never commit or print it. |
| `openai_enabled=false` | OpenAI is configured off. | Set `STORMHELM_OPENAI_ENABLED=1`. |
| `voice_enabled=false` or `spoken_responses_enabled=false` | Voice or spoken responses are off. | Set `STORMHELM_VOICE_ENABLED=1` and `STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED=1`. |
| `playback_enabled=false` or `playback_provider` is not `local` | Playback is disabled or routed to a non-speaker sink. | Set `STORMHELM_VOICE_PLAYBACK_ENABLED=1` and `STORMHELM_VOICE_PLAYBACK_PROVIDER=local`. |
| `speaker_backend_available=false` | Windows speaker backend/device is unavailable. | Check default output device and `STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK=1`. |
| `approved_spoken_text_present=false` or `skipped_reason=empty_spoken_text` | The response had no user-facing speakable text. | Fix the route response shape; normal visible answers should set content or `micro_response`. |
| `voice_service_called=false` with `skipped_reason=voice_output_disabled` | A gate blocked speech before TTS. | Inspect `disabled_reasons` in the decision. |
| `voice_service_status=failed` | TTS/playback failed after scheduling. | Inspect `voice_service_error_code`, `voice.tts.last_streaming_error`, and `voice.playback.degraded_reason`. |
| `current_response_suppressed=true` or muted | Stop-speaking/suppress/mute state is active. | Use `/voice/output/unmute` or clear suppression by starting a new response. |

Playback start does not mutate Core result state, task completion, trust, or verification. `user_heard_claimed=true` only means the real Windows speaker sink accepted/started output; mock and `null_stream` keep it false.

## Stormforge Voice Visual Meter

Voice-AR0 resets Stormforge audio-reactive Anchor motion to one backend-owned scalar. `VoiceVisualMeter` consumes PCM chunks from the playback path, computes RMS/peak energy, normalizes it to `0.0..1.0`, smooths it with attack/release, and emits at `[voice.visual_meter].sample_rate_hz` up to 60 Hz. The production source name is `pcm_stream_meter`.

The meter starts during the playback startup preroll. The default `startup_preroll_ms=350` lets the first visual frames be primed before audible playback starts; `max_startup_wait_ms=800` prevents a dead wait if the stream does not provide enough PCM promptly. Stop-speaking still interrupts playback promptly; preroll must not become a second output queue.

`[voice.visual_meter].visual_offset_ms` is available as a bounded AR4 calibration knob and defaults to `0`. Values are clamped to `-300..300`; negative values mean the visual is intentionally led, positive values mean it is intentionally delayed. The default remains zero until real audible-path evidence supports a non-zero offset.

The UI receives only scalar fields: `voice_visual_energy`, `voice_visual_active`, `voice_visual_source`, `voice_visual_playback_id`, `voice_visual_available`, `voice_visual_disabled_reason`, `voice_visual_sample_rate_hz`, `voice_visual_started_at_ms`, `voice_visual_latest_age_ms`, and `raw_audio_present=false`. Raw PCM, raw audio bytes, and large envelope timelines are not serialized, logged, or sent to QML.

Stormforge Anchor production motion uses `voice_visual_energy` when `voice_visual_active=true` and `voice_visual_source="pcm_stream_meter"`. Idle organic motion, shimmer, ring fragments, fog, and the shared animation clock remain separate. Diagnostic visual modes are limited to `off`, `procedural_test`, `pcm_stream_meter`, and optional `constant_test_wave`; the old envelope timeline, playback-envelope warming, alignment gate, and source-switching paths are deprecated for production.

Voice-AR-DIAG adds an end-to-end scalar proof harness for the same path:

```powershell
python scripts\run_voice_reactive_chain_probe.py --mode closed-loop
python scripts\run_voice_reactive_chain_probe.py --mode local-playback
```

The probe uses deterministic synthetic PCM: 0.5 seconds of silence, 1.0 second of low sine, 1.0 second of high sine, 1.0 second of syllable-like pulses, and 0.5 seconds of silence. It records expected scalar energy, backend meter energy, UI payload energy, QML-received energy, `finalSpeakingEnergy`, and paint/frame timing when available. Reports are written to `.artifacts/voice_reactive_chain/voice_reactive_chain_report.json`, `.artifacts/voice_reactive_chain/voice_reactive_chain_report.md`, and `.artifacts/voice_reactive_chain/energy_timeline.csv`.

Interpret the classification this way:

| Classification | Meaning | Next check |
|---|---|---|
| `backend_meter_flat` | Expected PCM varies but the backend meter does not. | Inspect `VoiceVisualMeter` PCM feed, RMS/peak windowing, and smoothing. |
| `payload_handoff_flat` | Backend meter varies but the UI payload does not. | Inspect `voice_surface`/bridge payload mapping. |
| `qml_receive_flat` | UI payload varies but QML receives a flat value. | Inspect `voiceState` binding into `StormforgeAnchorHost/Core`. |
| `anchor_mapping_flat` | QML receives varying energy but `finalSpeakingEnergy` is flat. | Inspect Anchor scalar mapping and speaking-active truth gates. |
| `qml_paint_missing` | `finalSpeakingEnergy` varies but Canvas/frame paint did not update. | Inspect the render host/window path and paint coalescing. |
| `latency_too_high` | Values correlate but stage latency exceeds the threshold. | Calibrate timing rather than changing visual art. |
| `sample_drop_detected` | A measured stage missed rows compared with upstream stages. | Inspect event cadence and bridge/QML update frequency. |
| `correlation_poor` | Values vary but do not correlate well across a stage. | Check clipping, compression, stale values, or timebase mismatch. |
| `chain_pass` | The scalar signal survived the measured chain with bounded latency. | Use the report numbers before deciding on any tuning pass. |

Recommended thresholds for the diagnostic harness are intentionally conservative: stage correlations should stay above roughly `0.45`, stage latency should stay below roughly `350 ms`, scalar values must remain bounded in `0.0..1.0`, and reports must keep `raw_audio_present=false`. The CSV is scalar-only; it must not contain PCM samples, audio bytes, base64 audio, or raw sample arrays.

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/voice_visual_meter.py`, `src/stormhelm/core/voice/reactive_chain_probe.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/visualizer.py`, `src/stormhelm/ui/voice_surface.py`, `scripts/run_voice_reactive_chain_probe.py`
Tests: `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_stt_provider.py`, `tests/test_voice_tts_provider.py`, `tests/test_latency_l55_windows_voice_runtime.py`, `tests/test_voice_visual_meter.py`, `tests/test_voice_reactive_chain_probe.py`, `tests/test_voice_ui_state_payload.py`, `tests/test_stormforge_voice_visual_meter_contract.py`

## Push-To-Talk Controls

Capture is explicit. There is no background microphone loop. The normal one-shot user flow is `listen-turn`; the lower-level start/stop/submit controls remain available for debugging and tests.

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/capture/listen-turn -ContentType 'application/json' -Body '{"mode":"ghost","play_response":true}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/capture/start -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/capture/stop -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/capture/cancel -ContentType 'application/json' -Body '{}'
```

To allow local capture during development:

```powershell
$env:STORMHELM_VOICE_CAPTURE_ENABLED = "true"
$env:STORMHELM_VOICE_CAPTURE_ALLOW_DEV_CAPTURE = "true"
```

If capture is disabled, unavailable, already active, or missing dependencies, the response should say that instead of pretending Stormhelm listened.

Manual verification commands:

```powershell
python scripts\voice_doctor.py
python scripts\voice_input_smoke.py --mode openai-stt --listen --output-dir .artifacts\voice_input_smoke
python scripts\voice_conversation_smoke.py --listen --speak --output-dir .artifacts\voice_conversation_smoke
```

`voice_doctor.py` reports `.env` loading, key presence as present/missing only, OpenAI/voice/microphone/playback gates, selected/default input device, provider names, speaker availability, wake posture, `.env` git tracking, and `raw_audio_logged=false` / `raw_secret_logged=false`. The microphone/STT smoke opens the mic, endpoints, transcribes, and prints timing fields without dispatching Core. The conversation smoke uses the real container so the transcript enters the normal Core path and the response uses the normal spoken-response pipeline.

Sources: `src/stormhelm/core/api/app.py`, `src/stormhelm/core/api/schemas.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`
Tests: `tests/test_voice_l6_manual_conversation.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_capture_provider.py`, `tests/test_voice_bridge_controls.py`

## Wake Foundation Controls

Voice-10 added backend wake readiness and mock wake event seams. Voice-11 adds the local provider boundary behind the same service contract. It remains disabled by default, does not use OpenAI or cloud services for wake detection, does not start capture, and does not route Core.
Voice-12 lets an accepted wake session surface Ghost presentation state. This is visual/status attention only: it does not capture request audio, transcribe, route Core, synthesize speech, or play audio.
Voice-13R backfills the dedicated post-wake listen-window layer. A listen window is one bounded request-capture opportunity tied to an accepted wake session and Ghost presentation. It may start the existing capture boundary and may be finalized by VAD/manual stop/timeout, but it does not understand, transcribe, route, or execute anything by itself.
Voice-15 composes that presentation state with the Voice-13R listen window and one bounded capture turn. It may submit the resulting audio through the existing STT -> Voice/Core bridge -> spoken response -> TTS -> playback path, then it stands down. It is not a continuous loop.

Voice-14/15/16 were revalidated after Voice-13R. VAD events now carry `listen_window_id` when a post-wake listen window owns the capture opportunity. Wake-loop STT/Core/spoken-response events preserve the same listen-window correlation. Spoken confirmation may arrive through a post-wake transcript, but `listen_window_id` is provenance only; confirmation still requires a fresh, bound, scoped, unconsumed trust prompt and sufficient phrase strength.

```powershell
Invoke-RestMethod http://127.0.0.1:8765/voice/wake/readiness
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/wake/start -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/wake/stop -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/wake/simulate -ContentType 'application/json' -Body '{"confidence":0.92}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/wake/cancel -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/wake/expire -ContentType 'application/json' -Body '{}'
Invoke-RestMethod http://127.0.0.1:8765/voice/wake/ghost
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/wake/ghost/cancel -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/wake/loop -ContentType 'application/json' -Body '{"wake_session_id":"wake-session-id","synthesize_response":true,"play_response":true}'
```

Mock wake simulation requires explicit development gates:

```powershell
$env:STORMHELM_VOICE_WAKE_ENABLED = "true"
$env:STORMHELM_VOICE_WAKE_ALLOW_DEV_WAKE = "true"
$env:STORMHELM_VOICE_WAKE_PROVIDER = "mock"
```

Wake detected means only that a wake event was represented. Wake-to-Ghost means Ghost presentation was requested/shown. Voice-15 can run one bounded supervised request after an accepted wake session, but wake itself still does not mean capture started, transcription succeeded, Core understood intent, or an action was requested.
Post-wake listen active means only that one bounded request-capture window is open. It is not command understanding, not STT, and not Core routing.

Sources: `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py`
Tests: `tests/test_voice_wake_config.py`, `tests/test_voice_wake_service.py`, `tests/test_voice_local_wake_provider.py`, `tests/test_voice_wake_ghost_service.py`, `tests/test_voice_wake_ghost_payload.py`, `tests/test_voice_post_wake_listen.py`

## VAD / End-Of-Speech Controls

L6 uses simple amplitude/silence endpointing inside the Windows local microphone capture backend for explicit manual listen sessions. It starts only after the user triggers listening, reports speech start from safe PCM level metadata, and stops on `speech_ended`, `max_duration`, `cancelled`, `no_speech_detected`, or `mic_error`.

Voice-14's provider-abstracted VAD foundation remains available for isolated VAD/wake-window tests. VAD is disabled by default outside explicit capture/listen windows. Speech stopped means audio activity likely stopped; it does not mean the request is complete, understood, confirmed, approved, routed, or executed.

```powershell
Invoke-RestMethod http://127.0.0.1:8765/voice/vad/readiness
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/vad/speech-started -ContentType 'application/json' -Body '{"capture_id":"voice-capture-id"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/vad/speech-stopped -ContentType 'application/json' -Body '{"capture_id":"voice-capture-id"}'
```

Mock VAD simulation requires explicit development gates:

```powershell
$env:STORMHELM_VOICE_VAD_ENABLED = "true"
$env:STORMHELM_VOICE_VAD_ALLOW_DEV_VAD = "true"
```

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py`
Tests: `tests/test_voice_vad_config.py`, `tests/test_voice_vad_provider.py`, `tests/test_voice_vad_service.py`, `tests/test_voice_vad_status_payload.py`

## Realtime Transcription Bridge

Voice-18 adds OpenAI Realtime as a disabled-by-default transcription bridge. It is not full Realtime speech-to-speech, not continuous conversation, not wake detection, and not command authority. Realtime can provide partial transcript previews and final transcript events for an explicitly started bounded session. A partial transcript updates status only. A final transcript is submitted through the existing VoiceTurn/Core bridge, so Stormhelm Core still owns routing, trust, approvals, task state, verification, and result-state truth.

```powershell
Invoke-RestMethod http://127.0.0.1:8765/voice/realtime/readiness
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/realtime/start -ContentType 'application/json' -Body '{"source":"test"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/realtime/partial -ContentType 'application/json' -Body '{"transcript":"open the"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/realtime/final -ContentType 'application/json' -Body '{"transcript":"open the docs"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/realtime/stop -ContentType 'application/json' -Body '{}'
```

Mock Realtime simulation requires explicit development gates:

```powershell
$env:STORMHELM_VOICE_REALTIME_BRIDGE_ENABLED = "true"
$env:STORMHELM_VOICE_REALTIME_ALLOW_DEV_REALTIME = "true"
$env:STORMHELM_VOICE_REALTIME_PROVIDER = "mock"
```

When enabled with a real OpenAI provider in a later provider completion pass, bounded active-session audio may be sent to OpenAI for Realtime transcription. Dormant wake audio remains local and is never sent to OpenAI. Realtime receives no direct tools, no approval authority, no verification authority, and no speech output role in Voice-18.

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py`
Tests: `tests/test_voice_realtime_transcription_bridge.py`

## Realtime Speech Core Bridge

Voice-19 adds `mode="speech_to_speech_core_bridge"` as a disabled-by-default Realtime speech surface. This mode may represent natural audio I/O for an active bounded session, but command/action/system requests must call exactly one bridge function: `stormhelm_core_request`. Realtime receives no direct action tools. Stormhelm Core result fields govern what may be spoken.

Development setup requires explicit gates:

```powershell
$env:STORMHELM_VOICE_REALTIME_BRIDGE_ENABLED = "true"
$env:STORMHELM_VOICE_REALTIME_ALLOW_DEV_REALTIME = "true"
$env:STORMHELM_VOICE_REALTIME_PROVIDER = "mock"
$env:STORMHELM_VOICE_REALTIME_MODE = "speech_to_speech_core_bridge"
$env:STORMHELM_VOICE_REALTIME_SPEECH_TO_SPEECH_ENABLED = "true"
$env:STORMHELM_VOICE_REALTIME_AUDIO_OUTPUT_FROM_REALTIME = "true"
```

Response gating rules:

- `requires_confirmation` speaks the Core confirmation prompt only.
- `blocked` speaks the block reason or next safe step only.
- `attempted_not_verified` must not become `done` or `verified`.
- `failed` must not become success.
- `speak_allowed=false` blocks Realtime speech content.
- direct tool attempts are blocked and audited as Realtime direct-tool attempts, not tool executions.

Spoken confirmations still use Voice-16 binding and freshness rules. Interruption still uses Voice-17: `stop talking` stops output only, `cancel task` routes through Core/task/trust, and corrections route as normal Core turns. Active Realtime speech audio may go to OpenAI only when this mode is explicitly enabled and active; dormant wake audio remains local.

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/ui/voice_surface.py`
Tests: `tests/test_voice_realtime_speech_core_bridge.py`

## Voice Release Hardening

Voice-20 is a release-hardening layer, not a new authority layer. It adds a structured evaluator in `src/stormhelm/core/voice/evaluation.py` that runs mock/fake scenarios across push-to-talk, wake-loop, Realtime transcription, Realtime speech-to-speech Core bridge, spoken confirmation, interruption, correction, provider fallback, privacy/redaction, and authority-boundary cases.

The evaluator records a deterministic `VoiceLatencyBreakdown` for wake, Ghost, listen window, capture, VAD, STT, Realtime partial/final transcript, Core bridge, spoken rendering, TTS, playback start, Realtime response gating, and total elapsed time. Latency budgets are diagnostics only unless a test explicitly asserts a budget; they do not change voice authority or user-facing claims.

Release-hardening audits check that:

- direct Realtime action tools stay disabled;
- `stormhelm_core_request` remains the only Realtime command/action/system bridge;
- partial transcripts do not route Core;
- blocked or attempted-not-verified Core results are not strengthened into success;
- spoken confirmation and interruption laws still apply;
- raw audio, generated audio bytes, secrets, and unbounded transcripts do not appear in events/status/UI payloads;
- Ghost/Deck/status copy avoids always-listening, cloud wake, direct-tools-active, generic assistant, and premature done/verified claims.

Release matrix:

| Capability | Implemented | Default | Authority Boundary | Release Posture |
|---|---:|---|---|---|
| Wake local-only | Yes | Disabled | Local wake only; no command authority | Hardened |
| Push-to-talk capture | Yes | Disabled | Bounded audio only | Hardened |
| Post-wake listen window | Yes | Disabled | Bounded opportunity only; no Core routing | Hardened |
| VAD/end-of-speech | Yes | Disabled | Audio activity only | Hardened |
| STT | Yes | Disabled | Transcript only | Hardened |
| Core bridge | Yes | Voice turns | Core owns meaning/trust/result state | Hardened |
| TTS | Yes | Disabled | Approved text only | Hardened |
| Playback | Yes | Disabled | Playback does not prove user heard | Hardened |
| Stop-speaking | Yes | Contextual | Output stop only | Hardened |
| Spoken confirmation | Yes | Enabled | Fresh scoped trust binding only | Hardened |
| Interruption/correction | Yes | Enabled | Core/task/trust for task semantics | Hardened |
| Realtime transcription bridge | Yes | Disabled | Final transcript routes through Core | Hardened |
| Realtime speech Core bridge | Yes | Disabled | `stormhelm_core_request` only; no direct tools | Hardened |
| Privacy/redaction | Yes | Always | No raw audio/secrets in payloads | Hardened |
| Event correlation | Yes | Always | Stage IDs preserve trace truth | Hardened |
| Provider fallback | Yes | Always | Truthful unavailable states | Hardened |
| Latency instrumentation | Yes | Diagnostic | Diagnostics only; no authority | Hardened |

Sources: `src/stormhelm/core/voice/evaluation.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/ui/voice_surface.py`
Tests: `tests/test_voice_release_evaluation.py`, `tests/test_voice_latency_instrumentation.py`, `tests/test_voice_release_hardening.py`

## Output-Only Live Playback

Voice-LP1 backfills real local playback for generated TTS audio. Voice-I1 makes output-only mode treat that live playback path as a requirement, not an optional nice-to-have. The backend remains provider-owned: UI/API calls `VoiceService`, `VoiceService` creates a playback request, and the local provider plays the file or transient in-memory TTS bytes through the configured local device. Playback still only means the provider started/completed/stopped output delivery; it never proves the user heard the response, mutates Core result state, executes tools, or bypasses trust.

For an output-only voice test, use local playback and keep every input path disabled:

```powershell
$env:STORMHELM_OPENAI_ENABLED = "true"
$env:OPENAI_API_KEY = "<your key>"
$env:STORMHELM_VOICE_ENABLED = "true"
$env:STORMHELM_VOICE_MODE = "output_only"
$env:STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED = "true"
$env:STORMHELM_VOICE_DEBUG_MOCK_PROVIDER = "false"
$env:STORMHELM_VOICE_PLAYBACK_ENABLED = "true"
$env:STORMHELM_VOICE_PLAYBACK_PROVIDER = "local"
$env:STORMHELM_VOICE_PLAYBACK_DEVICE = "default"
$env:STORMHELM_VOICE_PLAYBACK_VOLUME = "1.0"
$env:STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK = "true"
$env:STORMHELM_VOICE_CAPTURE_ENABLED = "false"
$env:STORMHELM_VOICE_WAKE_ENABLED = "false"
$env:STORMHELM_VOICE_POST_WAKE_ENABLED = "false"
$env:STORMHELM_VOICE_VAD_ENABLED = "false"
$env:STORMHELM_VOICE_REALTIME_ENABLED = "false"
```

If `voice.openai.persist_tts_outputs=false`, playback can still use transient TTS bytes; those bytes are private request data and are not included in events/status payloads. If the Windows MCI backend or device is unavailable, status reports a typed reason such as `local_playback_platform_unsupported`, `local_playback_dependency_missing`, or `device_unavailable` instead of silently falling back to artifact-only output.

After startup, check the runtime mode report:

```powershell
(Invoke-RestMethod http://127.0.0.1:8765/status).voice.runtime_mode
```

For a no-sound, no-OpenAI mock smoke:

```powershell
.\.venv\Scripts\python.exe scripts\voice_output_smoke.py
```

For the opt-in live output-only smoke, verify your output device first, then set the explicit live flag:

```powershell
$env:STORMHELM_RUN_LIVE_VOICE_SMOKE = "1"
.\.venv\Scripts\python.exe scripts\voice_output_smoke.py --live
```

Sources: `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `config/default.toml`
Tests: `tests/test_voice_playback_service.py`, `tests/test_voice_playback_provider.py`, `tests/test_voice_runtime_modes.py`

## Playback Controls

TTS artifact generation and audio playback are separate. A generated speech artifact does not mean playback occurred.

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/playback/stop -ContentType 'application/json' -Body '{}'
```

To allow local playback during development:

```powershell
$env:STORMHELM_VOICE_PLAYBACK_ENABLED = "true"
$env:STORMHELM_VOICE_PLAYBACK_PROVIDER = "local"
$env:STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK = "true"
```

Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/api/app.py`
Tests: `tests/test_voice_playback_service.py`, `tests/test_voice_playback_provider.py`, `tests/test_voice_playback_diagnostics_events.py`

## Interruption And Barge-In

Voice-17 extends stop-speaking into a context-sensitive interruption layer. The classifier is deterministic and conservative: `stop talking` stops output only; `cancel this request` during a post-wake listen/capture window cancels that bounded listen/capture path; `no` or `cancel that` during a pending confirmation goes through the Voice-16 confirmation binding path; `cancel the task` routes a cancellation request through Core/task/trust instead of cancelling directly; `actually...` routes as a correction/new voice turn through the normal Core bridge.

Stop-speaking still only affects voice output. It does not cancel Core tasks, mutate Core results, undo actions, or prove the user heard audio. Capture/listen cancellation does not cancel a task. Confirmation rejection does not cancel a task. Core task state changes only when the Core/task layer says so.

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/output/stop-speaking -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/output/suppress-current-response -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/output/mute -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/output/unmute -ContentType 'application/json' -Body '{}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/interruption/handle -ContentType 'application/json' -Body '{"transcript":"cancel the task"}'
```

Expected wording is short and specific: `Stopped.`, `Playback stopped.`, `Capture cancelled.`, `Confirmation rejected.`, `I routed that cancellation through Core.`, or `The task state is unchanged.` Text/Core state remains available separately.

Sources: `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/bridge.py`
Tests: `tests/test_voice_interruption_service.py`, `tests/test_voice_interruption_bridge.py`, `tests/test_voice_barge_in_interruption.py`

## Spoken Confirmation

Voice-16 lets Stormhelm process phrases such as `yes`, `confirm`, `do it`, `no`, `cancel`, `show me the plan`, and `repeat that` only when they bind to a current pending confirmation from the trust layer.

```powershell
Invoke-RestMethod http://127.0.0.1:8765/voice/confirmation/status
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/confirmation/submit -ContentType 'application/json' -Body '{"transcript":"confirm","pending_confirmation_id":"approval-id","task_id":"task-id"}'
```

`Yes` is not global permission. Confirmation must be fresh, task-bound, payload-bound where applicable, risk-appropriate, and consumed once. Confirmation accepted means the pending trust prompt was accepted; it does not mean the action completed, the result was verified, or Core task state changed. OpenAI STT may transcribe the phrase, but Stormhelm Core/trust decides whether it confirms anything.

Sources: `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/voice_surface.py`
Tests: `tests/test_voice_spoken_confirmation.py`, `tests/test_trust_service.py`

## Safety And Privacy

| Boundary | Current behavior |
|---|---|
| Local-first posture | Voice state, routing, diagnostics, capture controls, and UI state are local. |
| External API | OpenAI STT/TTS requires OpenAI enabled and an API key. |
| Secrets | API keys come from `.env` or environment variables; do not commit keys. |
| Audio retention | Captured and generated audio are not persisted by default. |
| Capture | Capture is explicit and gated. Wake/VAD do not create command authority. |
| Wake | Local wake is disabled by default and reports dependency/platform/device/permission state. Dormant wake audio is not sent to OpenAI or cloud services. |
| Post-wake listen | Opens one bounded request window between wake-Ghost and capture. Expire/cancel paths do not submit STT or route Core. |
| Wake-driven loop | Runs one bounded post-wake listen/capture request through existing STT/Core/TTS/playback boundaries and then stands down. |
| VAD | Disabled by default. VAD status/events expose audio activity metadata only and do not include raw audio. |
| Voice visual meter | Stormforge audio-reactive visuals receive only scalar `voice_visual_energy` and meter status fields. Raw PCM/audio is not exposed to QML, events, logs, or status payloads. |
| Realtime | Disabled by default. Voice-18 transcription bridge remains available. Voice-19 speech mode is explicit and Core-bridged; direct tools remain disabled and responses are gated by Core result state. |
| Command authority | Voice providers do not execute tools; speech-derived requests go through the core bridge. |
| Interruption | Stop-speaking stops output only. Capture/listen cancel stops the bounded audio path only. Confirmation rejection rejects only the pending prompt. Task cancellation/correction phrases are routed through Core. |
| Trust | Voice does not bypass approval, adapter, or safety rules. Spoken confirmation must bind to a current pending trust prompt and is consumed once. |

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/trust/service.py`, `src/stormhelm/core/safety/policy.py`
Tests: `tests/test_voice_config.py`, `tests/test_voice_core_bridge_contracts.py`, `tests/test_trust_service.py`, `tests/test_safety.py`

## Troubleshooting

| Symptom | Likely cause | Debug command | Fix |
|---|---|---|---|
| Voice unavailable | `voice.enabled=false`, `voice.mode=disabled`, OpenAI disabled, missing key, or missing model config. | `Invoke-RestMethod http://127.0.0.1:8765/status` | Enable the required settings and restart core. |
| Capture blocked | `voice.capture.enabled=false`, dev capture gate false, unsupported provider, or active capture conflict. | Check `status.voice.capture`. | Enable capture gates only for development or cancel active capture. |
| STT fails | OpenAI disabled/key missing, audio too large/long, provider error, timeout. | Check `status.voice.transcription`. | Verify `voice.openai.*` limits and provider config. |
| TTS fails | Spoken responses disabled, text too long, provider error, unsupported voice/format. | Check `status.voice.speech_synthesis`. | Adjust TTS settings or shorten text. |
| Playback does nothing | Playback disabled, dev playback gate false, unsupported local playback backend. | Check `status.voice.playback`. | Enable playback gates only for development and verify dependencies. |
| Stop speaking says no active playback | Nothing is currently playing, or playback already completed. | Check `status.voice.interruption`. | No action needed unless a UI still shows stale playback. |
| Speech stays muted | Session-scoped speech output mute is active. | Check `status.voice.interruption.spoken_output_muted`. | Call `/voice/output/unmute`. |
| `cancel the task` does not immediately cancel a task | Voice-17 routes task cancellation language through Core/task/trust; the voice layer does not pull task state directly. | Check `status.voice.interruption.core_cancellation_requested` and Core/task status. | Wait for Core/task result or use the existing task controls. |
| Wake simulation blocked | Wake is disabled, dev wake is not allowed, provider is not mock, or cooldown is active. | Check `status.voice.wake` or `/voice/wake/readiness`. | Enable only the mock/dev wake gates or wait for cooldown. |
| Local wake unavailable | Local wake backend dependency, platform, device, permission, or configuration is unavailable. | Check `status.voice.wake.unavailable_reason`, `wake_backend`, `device_available`, and `permission_state`. | Keep wake disabled or install/configure a supported local backend explicitly. |
| Post-wake listen blocked | Post-wake listen is disabled, dev post-wake is not allowed, the wake session expired, or Ghost presentation is unavailable. | Check `status.voice.post_wake_listen` and `status.voice.wake_supervised_loop.missing_capabilities`. | Enable only the bounded post-wake gates for tests/operator trials. |
| VAD unavailable | VAD is disabled, dev VAD is not allowed, provider unsupported, or no capture/listen window is active. | Check `status.voice.vad` or `/voice/vad/readiness`. | Enable mock/dev VAD only for tests or use manual stop/timeout fallback. |
| Realtime unavailable | Realtime is disabled, dev Realtime is not allowed, OpenAI config is missing for a real provider, or speech mode was requested without `speech_to_speech_enabled` and `audio_output_from_realtime`. | Check `status.voice.realtime` or `/voice/realtime/readiness`. | Use the mock/dev gates for tests, or configure the real provider explicitly when that provider is ready. |
| Realtime partial transcript does not route Core | This is expected. Partial transcripts are provisional status only. | Check `status.voice.realtime.partial_transcript_preview`. | Wait for a final transcript event. |
| Spoken `yes` does nothing | No fresh matching pending confirmation exists, or the phrase strength/risk/binding check failed. | Check `status.voice.spoken_confirmation` or `/voice/confirmation/status`. | Re-open the current confirmation prompt or use the required explicit phrase. |
| UI shows stale voice state | Bridge did not refresh status after action or event stream is stale. | `Invoke-RestMethod http://127.0.0.1:8765/snapshot` | Refresh UI/core status and run bridge tests if developing. |

Sources: `src/stormhelm/core/voice/diagnostics.py`, `src/stormhelm/core/voice/state.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`
Tests: `tests/test_voice_diagnostics.py`, `tests/test_voice_state.py`, `tests/test_voice_ui_state_payload.py`

## Related Docs

| Need | Page |
|---|---|
| Developer-level voice foundation and phase boundaries | [voice-0-foundation.md](voice-0-foundation.md) |
| Full settings reference | [settings.md](settings.md#voice) |
| UI voice surfaces | [ui-surfaces.md](ui-surfaces.md#voice-surfaces) |
| Current roadmap boundaries | [roadmap.md](roadmap.md) |
