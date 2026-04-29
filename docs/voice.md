# Voice

Stormhelm voice is a bounded input/output surface. It is not an always-listening assistant, and it does not give audio providers authority to run commands. Voice requests enter the same backend-owned core path as typed requests.

Current status: implemented but limited, disabled by default.

For the Voice-C1 phase inventory, config matrix, authority boundary matrix, release notes, live-provider smoke plan, test commands, and commit hygiene guidance, see [voice-c1-release-readiness.md](voice-c1-release-readiness.md).

Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/bridge.py`, `config/default.toml`
Tests: `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_manual_turn.py`, `tests/test_voice_audio_turn.py`, `tests/test_voice_core_bridge_contracts.py`

## What Works

| Capability | Current behavior | Enabled by default? | Sources | Tests |
|---|---|---:|---|---|
| Manual voice turns | Text treated as a voice-originated turn and sent through the core bridge. | Partly; voice is off by default but manual input config defaults true. | `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/bridge.py` | `tests/test_voice_manual_turn.py`, `tests/test_voice_core_bridge_contracts.py` |
| Controlled audio STT | Bounded file/blob/fixture-style audio metadata can be transcribed through the configured provider path. | No | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_audio_turn.py`, `tests/test_voice_stt_provider.py` |
| TTS artifact generation | Core-approved text or explicit safe test text can be rendered into a controlled speech artifact. | No | `src/stormhelm/core/voice/speech_renderer.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_tts_provider.py`, `tests/test_voice_tts_from_turn_result.py` |
| Streaming TTS output | Core-approved spoken text can optionally use a chunked TTS contract with redacted chunk metadata and first-audio timing. Streaming never starts from partial transcripts or unapproved filler. | No | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_latency_l5_voice_streaming_first_audio.py` |
| Push-to-talk capture boundary | Explicit start/stop/cancel/submit actions exist. Local capture is separately gated. | No | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_capture_service.py`, `tests/test_voice_bridge_controls.py` |
| Playback boundary | Playback requests and stop controls exist behind provider/config gates. Voice-LP1 adds a real Windows local playback provider for MP3/WAV output while preserving mock/unavailable paths. L5 adds live stream/chunk contracts and prewarm status while keeping artifact persistence separate from live playback truth. | No | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_playback_service.py`, `tests/test_voice_playback_provider.py`, `tests/test_latency_l5_voice_streaming_first_audio.py` |
| Interruption and barge-in hardening | Active playback can be stopped, spoken output muted, capture/listen windows cancelled, pending confirmations rejected, and cancellation/correction phrases routed safely without direct task cancellation. | No; controlled by explicit action or bounded voice context. | `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_interruption_service.py`, `tests/test_voice_interruption_bridge.py`, `tests/test_voice_barge_in_interruption.py` |
| Wake word foundation | Wake config, provider contracts, mock wake events, wake sessions, readiness, diagnostics, and events exist without real wake listening. | No | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py` | `tests/test_voice_wake_config.py`, `tests/test_voice_wake_service.py` |
| Local wake provider boundary | A disabled-by-default `LocalWakeWordProvider` can wrap an optional local backend and report dependency/platform/device/permission state. | Only when explicitly enabled and the local backend is available. | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_local_wake_provider.py` |
| Wake-to-Ghost presentation | Accepted wake sessions can create a backend-owned Ghost presentation request with wake-ready status and timeout/cancel behavior. | Presentation only; no request audio capture. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_wake_ghost_service.py`, `tests/test_voice_wake_ghost_payload.py` |
| Post-wake listen window | Voice-13R backfills the explicit one-utterance listen window between wake-Ghost and capture. It binds to an accepted wake session, can expire/cancel, and does not route Core. | No; it is a bounded opportunity to capture one request. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_post_wake_listen.py` |
| Wake-driven supervised loop | Accepted wake sessions can run one bounded wake -> Ghost -> post-wake listen window -> capture -> STT -> Core -> approved speech/TTS -> playback loop, then stand down. | No; requires explicit wake/listen/capture/STT/TTS/playback gates. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py` | `tests/test_voice_wake_supervised_loop.py` |
| VAD / end-of-speech foundation | Mock/stub voice activity detection can bind to an explicit capture/listen window and optionally finalize capture when speech stops. | No; disabled by default and mock/dev gated. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_vad_config.py`, `tests/test_voice_vad_provider.py`, `tests/test_voice_vad_service.py` |
| Spoken confirmation handling | Short confirmation/rejection/control phrases are classified deterministically and can bind only to a fresh pending trust confirmation. | Yes, but inert without a pending confirmation. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_spoken_confirmation.py` |
| Realtime transcription bridge | OpenAI Realtime can be represented as a disabled-by-default transcription bridge. Mock/dev sessions can produce partial transcript status and final transcripts that become VoiceTurns through the existing Core bridge. | No; disabled and dev-gated by default. | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/api/app.py` | `tests/test_voice_realtime_transcription_bridge.py` |
| Realtime speech-to-speech Core bridge | OpenAI Realtime speech sessions can be represented as a disabled-by-default audio conversation surface. Command/action/system turns must call `stormhelm_core_request`; responses are gated by Core result state and spoken summary. | No; explicit speech/audio flags and dev gates are required. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_realtime_speech_core_bridge.py` |
| Voice release hardening | Voice-20 adds mock/fake release scenarios, deterministic latency diagnostics, provider fallback checks, redaction audits, Realtime authority tripwires, event correlation checks, and Ghost/Deck/status truth checks. | Diagnostic only. | `src/stormhelm/core/voice/evaluation.py` | `tests/test_voice_release_evaluation.py`, `tests/test_voice_latency_instrumentation.py`, `tests/test_voice_release_hardening.py` |
| OpenAI STT/TTS boundary | OpenAI may transcribe bounded audio and synthesize approved speech text only. It is not voice command authority. | No | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_openai_boundary.py` |
| Ghost/Deck voice state | The bridge maps backend voice status into compact UI state and voice actions. | UI depends on current worktree files. | `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/controllers/main_controller.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_ui_state_payload.py`, `tests/test_voice_bridge_controls.py` |

## What Does Not Work Yet

| Request | Current answer |
|---|---|
| Always-listening mode | Not implemented. |
| Continuous post-wake listening | Not implemented. Voice-13R/15 handle one bounded post-wake listen window/request only, then return to idle/Dormant. |
| Continuous microphone capture | Not implemented. |
| Unbounded Realtime conversation | Not implemented. Voice-19 speech mode is bounded, explicitly started, and still Core-bridged. |
| Semantic VAD / request completion | Not implemented. VAD detects audio activity only. |
| OpenAI Realtime direct actions or direct Core task cancellation | Not implemented and not allowed. Voice-19 exposes only `stormhelm_core_request`; cancellation/correction still routes through Core/task/trust. |
| Voice provider executing tools directly | Not allowed by design. |
| Proof that the user heard audio | Not claimed; playback result is only provider/action state. |

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
| capture | Whether capture is enabled, active, blocked, or recently completed. |
| transcription | Last STT provider/model/result/error state. |
| speech synthesis | Last TTS request/result/artifact state, streaming TTS status, live/artifact formats, provider prewarm state, fallback use, and first-audio timing. |
| playback | Last playback request/result/error state, live stream status, playback prewarm state, partial-playback state, and stop-speaking availability. |
| interruption | Last interruption request/classification/result, affected output/capture/listen/confirmation surfaces, Core-routed cancellation/correction flags, and invariants that voice did not cancel tasks or mutate Core results directly. |
| wake | Wake config/readiness/provider/backend/device/session/event/Ghost presentation status. Local wake remains disabled unless explicitly configured and available. |
| wake_ghost | Active/last wake-to-Ghost presentation state, including request/session IDs, phrase, timeout, and presentation-only truth flags. |
| post_wake_listen | Active/last post-wake listen-window ID/status/expiry, capture/audio/VAD references, and truth flags that the window is bounded and does not route Core. |
| wake_supervised_loop | Readiness, active loop stage, final status, stopped/failed stage, and one-bounded-request truth flags for the wake-driven loop. |
| vad | VAD config/readiness/provider/session/activity status. Speech activity is not command intent or semantic completion. |
| spoken_confirmation | Confirmation classifier/binding/result status, pending count, freshness/strength settings, and truth flags that confirmation does not execute actions. |
| realtime | Realtime config/readiness/session/transcript/Core-bridge status, including `direct_tools_allowed=false`, `direct_action_tools_exposed=false`, `core_bridge_required=true`, speech mode flags, last Core result state, and response-gating source. |
| runtime_mode | Selected/effective voice mode, readiness, missing requirements, contradictory settings, provider availability, and the next settings fix. |
| truth flags | Explicit no-wake-word/no-realtime/no-always-listening style flags. |

Sources: `src/stormhelm/core/container.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/state.py`
Tests: `tests/test_voice_state.py`, `tests/test_voice_diagnostics.py`

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

Streaming TTS is also separate from artifact persistence. `voice.openai.stream_tts_outputs=true` asks the provider layer for chunks in `voice.openai.tts_live_format` such as `pcm`; `voice.openai.tts_artifact_format` remains the optional file/debug format. `voice.openai.streaming_fallback_to_buffered` and `voice.playback.streaming_fallback_to_file` make fallback explicit in status and latency metadata. Fallback must not hide the original streaming failure or create duplicate speech.

First-audio metrics live in voice status and latency summaries:

- `core_result_to_tts_start_ms`
- `tts_start_to_first_chunk_ms`
- `first_chunk_to_playback_start_ms`
- `core_result_to_first_audio_ms`
- `request_to_first_audio_ms`
- `first_audio_available`
- `first_audio_budget_exceeded`
- `partial_playback`
- `user_heard_claimed=false`

Playback started means a playback provider accepted audio. It does not prove the user heard it and it does not change Core result state.

Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/ui/voice_surface.py`
Tests: `tests/test_voice_runtime_modes.py`, `tests/test_voice_readiness.py`, `tests/test_voice_ui_state_payload.py`

## Enable For Development

Voice availability depends on both voice settings and OpenAI settings.

```powershell
$env:STORMHELM_OPENAI_ENABLED = "true"
$env:OPENAI_API_KEY = "<your key>"
$env:STORMHELM_VOICE_ENABLED = "true"
$env:STORMHELM_VOICE_MODE = "manual"
$env:STORMHELM_VOICE_MANUAL_INPUT_ENABLED = "true"
.\scripts\run_core.ps1
```

OpenAI-backed STT/TTS also uses `voice.openai.*` settings from `config/default.toml`.

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/providers.py`
Tests: `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_stt_provider.py`, `tests/test_voice_tts_provider.py`

## Push-To-Talk Controls

Capture is explicit. There is no background microphone loop.

```powershell
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

Sources: `src/stormhelm/core/api/app.py`, `src/stormhelm/core/api/schemas.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`
Tests: `tests/test_voice_capture_service.py`, `tests/test_voice_capture_provider.py`, `tests/test_voice_bridge_controls.py`

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

Voice-14 adds a provider-abstracted VAD foundation. VAD is disabled by default, must be separately gated, and only runs during explicit capture/listen windows. Speech stopped means audio activity likely stopped; it does not mean the request is complete, understood, confirmed, approved, routed, or executed.

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
