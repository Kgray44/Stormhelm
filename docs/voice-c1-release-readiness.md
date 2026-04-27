# Stormhelm Voice C1 Release Readiness

Voice-C1 consolidates the implemented Voice-0 through Voice-20 stack into a reviewable release-readiness record. It does not add voice capability. It records what exists, how it is gated, how authority is preserved, what can be dogfooded, and what still needs live-provider validation.

Current posture:

- Voice implementation tests are green in the current known baseline: focused Voice-20 `8 passed`, Realtime plus Voice-20 slice `26 passed`, all voice tests `251 passed`, trust/task slice `14 passed`.
- Full regression is not repo-green: current known baseline is `55 failed / 1202 passed`, with the known failures in non-voice planner/orchestrator/routing areas.
- Voice remains disabled by default. Live OpenAI, local capture, local wake, playback, and Realtime paths require explicit configuration or opt-in smoke testing.
- OpenAI may hear bounded active-session audio and may speak approved/gated text. Stormhelm Core remains command authority.

## Phase Inventory

| Phase | Implemented capability | Primary files/modules | Key tests | Default | Live dependency | Authority boundary | Release posture |
|---|---|---|---|---|---|---|---|
| Voice-0 foundation | Config, availability, state, provider contracts, diagnostics/events, spoken renderer scaffold. | `config/default.toml`, `src/stormhelm/config/models.py`, `src/stormhelm/core/voice/*` | `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_state.py` | Off | None for mocks | Foundation only; no command authority. | Stable scaffold. |
| Voice-1 manual turn | Manual transcript enters existing Core bridge as voice-originated turn. | `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/bridge.py` | `tests/test_voice_manual_turn.py`, `tests/test_voice_core_bridge_contracts.py` | Voice off; manual flag true | Core/orchestrator | Transcript routes through Core. | Safe for dev use. |
| Voice-2 STT bridge | Controlled bounded audio can be transcribed then routed through VoiceTurn/Core. | `src/stormhelm/core/voice/providers.py`, `service.py` | `tests/test_voice_audio_turn.py`, `tests/test_voice_stt_provider.py` | Off | OpenAI STT when enabled | STT produces transcript only. | Mock-tested; live smoke required. |
| Voice-3 TTS | Core-approved text can produce controlled speech artifact. | `speech_renderer.py`, `providers.py`, `service.py` | `tests/test_voice_tts_provider.py`, `tests/test_voice_tts_from_turn_result.py` | Off | OpenAI TTS when enabled | TTS speaks approved text only. | Mock-tested; live smoke required. |
| Voice-4 playback | Playback and stop controls behind provider gates. | `providers.py`, `service.py` | `tests/test_voice_playback_service.py`, `tests/test_voice_playback_provider.py` | Off | Local playback provider | Playback state is not proof user heard audio. | Mock/stub safe. |
| Voice-5 push-to-talk | Explicit start/stop/cancel/submit capture boundary. | `core/api/app.py`, `service.py` | `tests/test_voice_capture_service.py`, `tests/test_voice_bridge_controls.py` | Off | Local capture if enabled | Capture is not command authority. | Bounded, dev-gated. |
| Voice-6A capture provider | Guarded local capture provider boundary. | `providers.py`, `service.py` | `tests/test_voice_capture_provider.py`, `tests/test_voice_capture_service.py` | Off | Local mic backend if configured | Real mic never runs without explicit capture. | Needs live smoke. |
| Voice-6B UI controls | Ghost/Deck push-to-talk controls mapped to backend actions. | `src/stormhelm/ui/bridge.py`, `client.py`, `voice_surface.py` | `tests/test_voice_bridge_controls.py`, `tests/test_voice_ui_state_payload.py` | UI visible only from backend state | Core API | UI does not invent voice state. | Backend-owned. |
| Voice-7 readiness | Readiness/reporting, pipeline summary, truth flags. | `service.py`, `events.py`, `ui/voice_surface.py` | `tests/test_voice_diagnostics.py`, `tests/test_voice_pipeline_summary.py` | Diagnostic | None | Readiness is descriptive, not authority. | Stable. |
| Voice-8 evaluator | Supervised push-to-talk evaluation and hardening. | `src/stormhelm/core/voice/evaluation.py` | `tests/test_voice_evaluation.py` | Diagnostic | Mocks by default | Evaluation preserves stage truth. | Mock-safe. |
| Voice-9 stop speaking | Output-only stop/mute/suppression semantics. | `service.py`, `providers.py` | `tests/test_voice_stop_speaking.py`, `tests/test_voice_playback_service.py` | Off | Playback provider when active | Stop speaking does not cancel Core tasks. | Stable boundary. |
| Voice-10 wake foundation | Wake config, mock provider, readiness, sessions, events. | `models.py`, `providers.py`, `service.py` | `tests/test_voice_wake_config.py`, `tests/test_voice_wake_service.py` | Off | Mock only by default | Wake detection is local/presentation only. | Safe foundation. |
| Voice-11 local wake | Real local wake provider boundary, disabled by default. | `providers.py`, `service.py` | `tests/test_voice_local_wake_provider.py` | Off | Optional local wake backend | No OpenAI/cloud wake. | Needs live local smoke. |
| Voice-12 wake-to-Ghost | Accepted wake can request Ghost presentation and expire/cancel. | `models.py`, `service.py`, `ui/voice_surface.py` | `tests/test_voice_wake_ghost_service.py`, `tests/test_voice_wake_ghost_payload.py` | Off | Wake session | Presentation only; no capture/STT/Core. | Stable. |
| Voice-13R listen window | Backfilled explicit post-wake bounded listen window. | `models.py`, `service.py`, `ui/voice_surface.py` | `tests/test_voice_post_wake_listen.py`, `tests/test_voice_post_wake_revalidation.py` | Off | Wake/session/capture if enabled | Listen window is opportunity to capture only. | Stable seam. |
| Voice-14 VAD | End-of-speech foundation with mock/stub provider. | `models.py`, `providers.py`, `service.py` | `tests/test_voice_vad_config.py`, `tests/test_voice_vad_provider.py`, `tests/test_voice_vad_service.py` | Off | Mock/dev by default | VAD detects audio activity only. | Mock-safe. |
| Voice-15 wake loop | One bounded wake -> Ghost -> listen -> capture -> STT -> Core -> TTS -> playback loop. | `models.py`, `service.py`, `core/api/app.py` | `tests/test_voice_wake_supervised_loop.py` | Off | Multiple explicit gates | Composes existing authority boundaries. | Mock-safe; live smoke needed. |
| Voice-16 confirmation | Spoken confirmation/rejection/show-plan/repeat with fresh scoped binding. | `models.py`, `service.py`, `core/api/app.py` | `tests/test_voice_spoken_confirmation.py` | Enabled but inert without pending prompt | Trust service | Trust owns approval; voice cannot execute. | Stable safety layer. |
| Voice-17 interruption | Context-sensitive output/capture/listen/confirmation/Core-routed interruption. | `service.py`, `core/api/app.py`, `ui/voice_surface.py` | `tests/test_voice_interruption_service.py`, `tests/test_voice_interruption_bridge.py`, `tests/test_voice_barge_in_interruption.py` | Off/contextual | Active voice context | Interruption is not task cancellation. | Stable hardening. |
| Voice-18 Realtime transcription | Disabled OpenAI Realtime transcription bridge with partial/final transcripts. | `providers.py`, `service.py`, `core/api/app.py` | `tests/test_voice_realtime_transcription_bridge.py` | Off | OpenAI Realtime if enabled | Partial status only; final transcript routes through Core. | Mock-tested; live smoke needed. |
| Voice-19 Realtime speech | Speech-to-speech surface through strict `stormhelm_core_request` bridge. | `models.py`, `providers.py`, `service.py`, `ui/voice_surface.py` | `tests/test_voice_realtime_speech_core_bridge.py` | Off | OpenAI Realtime if enabled | Realtime is ears/mouth; Core is command authority. | Mock-tested; live smoke needed. |
| Voice-20 release hardening | Release evaluator, latency diagnostics, fallbacks, redaction, authority tripwires, event/UI truth. | `evaluation.py`, `service.py`, tests | `tests/test_voice_release_evaluation.py`, `tests/test_voice_latency_instrumentation.py`, `tests/test_voice_release_hardening.py` | Diagnostic | Mocks by default | Hardening only; no new authority. | Release-readiness evidence. |

## Config Matrix

| Area | Default | Safe state | What enables it | Must never imply |
|---|---|---|---|---|
| `voice.enabled` | `false` | Voice stack inert except diagnostics/manual config state. | Set true in config/env. | Always-listening, mic capture, or command authority. |
| `voice.provider` | `openai` | Provider name only. | Provider-specific gates and API key. | Provider is active or trusted to route commands. |
| `voice.mode` | `disabled` | No automatic audio mode. | Explicit mode selection by config. | Realtime or continuous listening. |
| `voice.manual_input_enabled` | `true` | Manual transcript path exists while voice runtime stays off. | Use manual voice API/action. | Audio was captured. |
| OpenAI STT | `gpt-4o-mini-transcribe`; bounded limits | No calls unless audio path enabled and submitted. | `OPENAI_API_KEY`, OpenAI enabled, voice/STT path enabled. | Command meaning, trust, approval, or execution. |
| OpenAI TTS | `gpt-4o-mini-tts`, voice `cedar`, persistence off | No calls unless approved text is synthesized. | TTS config, OpenAI enabled, speech request. | Text generation authority or proof user heard audio. |
| Playback | `enabled=false`, `provider=local`, dev gate false | No audio playback. | Playback enabled and provider available. | Core result mutation or user-heard proof. |
| Capture | `enabled=false`, `provider=local`, push-to-talk, persistence off | No mic capture. | Capture enabled, explicit start/stop/submit. | Wake, STT, or command execution. |
| Wake | `enabled=false`, `provider=mock`, phrase `Stormhelm`, local backend unavailable | No monitoring. | Wake enabled plus allowed provider/backend. | Cloud wake, capture, STT, or Core routing. |
| Post-wake listen | `enabled=false`, `8000ms`, auto capture/submit true | No listen window. | Accepted wake plus post-wake enabled. | Understanding, routing, or continuous listening. |
| VAD | `enabled=false`, `provider=mock`, `silence_ms=900` | No detection. | VAD enabled and bound to capture/listen. | Semantic completion or command intent. |
| Confirmation | `enabled=true`, `30000ms`, consume once, reject mismatches | Inert until pending confirmation exists. | Pending trust confirmation plus matching spoken response. | Global approval, action completion, or task cancellation. |
| Interruption | Contextual service state only | No effect without active output/capture/listen/prompt/Core route. | Spoken/control request in active context. | Direct Core task cancellation or tool execution. |
| Realtime transcription | `enabled=false`, `mode=transcription_bridge`, direct tools false, Core bridge required | No session. | Realtime enabled, dev/live gate, explicit session. | Speech-to-speech, direct tools, wake, or command authority. |
| Realtime speech | `speech_to_speech_enabled=false`, `audio_output_from_realtime=false` | Not active. | Explicit speech mode plus audio output gate and provider availability. | Autonomous assistant, direct tools, or result strengthening. |
| Live provider gates | `allow_dev_* = false` for wake/capture/VAD/Realtime/playback | Mock/stub or unavailable by default. | Explicit dev/live config and credentials/dev hardware. | Silent live calls. |
| Mock/dev gates | `debug_mock_provider=true`, provider-specific mock modes | Deterministic tests without live providers. | Test/dev configuration. | Release claim that a live provider was exercised. |

## Authority Boundary Matrix

| Surface | Permitted role | Authority owner | Release guard |
|---|---|---|---|
| OpenAI STT | Transcribe bounded captured audio. | Stormhelm Core decides meaning. | No raw audio in events/status; no Core route on STT failure/empty transcript. |
| OpenAI TTS | Synthesize approved/gated spoken text. | Spoken renderer/Core result decide text. | TTS cannot invent content or claim user heard output. |
| Realtime transcription | Partial/final transcripts and turn timing in explicit session. | Final transcript becomes VoiceTurn through Core bridge. | Partial transcripts never route Core. |
| Realtime speech | Active-session ears/mouth through `stormhelm_core_request`. | Core owns route/result/trust/verification. | No direct tools; response gating blocks unsafe speech. |
| Wake | Local wake detection/session only. | Voice service owns wake/session state. | No cloud wake and no dormant audio to OpenAI. |
| Wake-to-Ghost | Presentation/attention state. | Backend voice status. | Does not start capture, STT, or Core routing. |
| Post-wake listen | One bounded opportunity to capture a request. | Voice listen/capture pipeline. | Expire/cancel emits no STT/Core success. |
| VAD | Audio activity boundary only. | Capture/listen service decides finalization. | No semantic completion or command intent. |
| Confirmation | Fresh scoped spoken response binding. | Trust/approval system. | Once-only, task/payload/session/risk checks. |
| Interruption | Stop output, cancel capture/listen, reject prompt, or route cancel/correction. | Voice/Trust/Core/task systems by context. | Stop speaking is not task cancellation. |
| Core | Command meaning, routing, trust, task state, verification. | Stormhelm Core/planner/orchestrator/trust/task graph. | Voice never bypasses Core. |
| Task/trust systems | Approval and task cancellation authority where applicable. | Existing trust/task APIs. | Voice may request routing only; no direct tool execution. |

## Release Notes

Implemented:

- Typed voice foundation, manual voice turns, bounded audio STT, TTS artifacts, playback boundary, push-to-talk capture boundary, wake foundation/local wake boundary, wake-to-Ghost presentation, post-wake listen windows, VAD foundation, wake-driven loop, spoken confirmation, interruption/barge-in hardening, Realtime transcription bridge, Realtime speech-to-speech Core bridge, and Voice-20 release hardening.

Disabled by default:

- Voice runtime, capture, playback, wake monitoring, post-wake listen, VAD, Realtime transcription, Realtime speech, live provider behavior, and persisted audio.

Mock/fake-only or mostly mock-tested:

- Wake provider sessions, local wake dependency paths, VAD, Realtime transcription, Realtime speech, release evaluation scenarios, provider fallback cases, and authority tripwires.

Real provider boundary present but not release-proven by default:

- OpenAI STT, OpenAI TTS, OpenAI Realtime, local capture, local wake backend, local playback.

Requires explicit configuration:

- OpenAI credentials and provider enablement, voice runtime enablement, live capture/playback/wake providers, post-wake listen, VAD finalization, Realtime session mode, Realtime speech audio output, and live smoke-test flags.

Safe to dogfood:

- Manual transcript voice turns, mock STT/TTS/capture/playback paths, release evaluator scenarios, authority/redaction tripwire tests, and UI/status truth payloads.

Should not be claimed release-ready yet:

- Full repo regression, because the known baseline remains `55 failed / 1202 passed` outside the voice suite.
- Live OpenAI voice, local microphone capture, local wake, local playback, and Realtime speech behavior until opt-in smoke tests run on the target machine.
- Continuous voice conversation, cloud wake, direct Realtime tools, unrestricted voice automation, and voice-driven direct task cancellation. These are not implemented.

## Opt-In Live Smoke Plan

All live smoke tests are skipped by default. Require an explicit flag such as `STORMHELM_VOICE_LIVE_SMOKE=1`, explicit provider config, harmless test prompts, and local review of what will be sent to providers.

| Smoke | Preconditions | Harmless scenario | Pass criteria | Must not happen |
|---|---|---|---|---|
| OpenAI STT | OpenAI enabled, API key present, bounded test audio fixture. | "What time is it?" or "Show voice status." | Transcript returned, VoiceTurn/Core path only if submitted. | Raw audio logged; direct tool execution from STT. |
| OpenAI TTS | TTS enabled, API key present, approved test text. | "Voice smoke test complete." | Speech artifact generated with bounded metadata. | TTS invents text or persists audio unless configured. |
| Realtime transcription | Realtime enabled, transcription mode, live flag. | Short active-session utterance. | Partial/final transcript events; final transcript can route through Core. | Always-listening, direct tools, cloud wake. |
| Realtime speech Core bridge | Realtime speech/audio flags enabled, live flag. | Harmless no-op route: "Summarize voice status." | `stormhelm_core_request` called; response gated by Core result. | Direct install/send/click/delete/approve/verify tools. |
| Local capture | Capture enabled, dev/live gate, mic permission. | Push-to-talk short utterance. | Capture starts/stops explicitly and produces bounded metadata. | Dormant capture or background streaming. |
| Local wake | Wake enabled, local provider available, dev/live gate. | Say configured wake phrase only. | Local wake session/presentation created. | Dormant wake audio sent to OpenAI. |
| Playback | Playback enabled and provider available. | Play generated smoke artifact. | Playback start/completion/failure reported truthfully. | Claim user heard audio. |

Recommended live smoke guardrails:

- Use harmless transcripts only.
- Do not run destructive commands, sends, installs, deletes, memory writes, or task cancellation.
- Keep Realtime direct tools disabled.
- Route command/action/system turns through a safe mocked Core action or harmless no-op route.
- Record provider availability and errors, not raw payloads.

## Test Commands

Set `PYTHONPATH` explicitly so tests exercise this worktree:

```powershell
$env:PYTHONPATH = "C:\Stormhelm\src"
```

Focused Voice-20 release hardening:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  C:\Stormhelm\tests\test_voice_release_evaluation.py `
  C:\Stormhelm\tests\test_voice_latency_instrumentation.py `
  C:\Stormhelm\tests\test_voice_release_hardening.py -q
```

Realtime authority and Voice-20 slice:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  C:\Stormhelm\tests\test_voice_realtime_transcription_bridge.py `
  C:\Stormhelm\tests\test_voice_realtime_speech_core_bridge.py `
  C:\Stormhelm\tests\test_voice_release_evaluation.py `
  C:\Stormhelm\tests\test_voice_latency_instrumentation.py `
  C:\Stormhelm\tests\test_voice_release_hardening.py -q
```

All voice tests:

```powershell
$voiceTests = Get-ChildItem -Path C:\Stormhelm\tests -File -Filter "test_voice_*.py" | ForEach-Object { $_.FullName }
.\.venv\Scripts\python.exe -m pytest @voiceTests -q
```

Trust/task slice:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  C:\Stormhelm\tests\test_trust_service.py `
  C:\Stormhelm\tests\test_task_graph.py -q
```

Full regression:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Diff hygiene:

```powershell
git diff --check
```

Optional live smoke tests:

```powershell
$env:STORMHELM_VOICE_LIVE_SMOKE = "1"
# Run only the explicit live smoke test module or marker after verifying provider config.
.\.venv\Scripts\python.exe -m pytest -m voice_live_smoke -q
```

## Dirty Worktree And Commit Hygiene

Recommended voice implementation staging group:

- `config/default.toml`
- `src/stormhelm/config/loader.py`
- `src/stormhelm/config/models.py`
- `src/stormhelm/core/api/app.py`
- `src/stormhelm/core/api/schemas.py`
- `src/stormhelm/core/container.py`
- `src/stormhelm/core/voice/__init__.py`
- `src/stormhelm/core/voice/events.py`
- `src/stormhelm/core/voice/models.py`
- `src/stormhelm/core/voice/providers.py`
- `src/stormhelm/core/voice/service.py`
- `src/stormhelm/core/voice/evaluation.py`
- `src/stormhelm/ui/bridge.py`
- `src/stormhelm/ui/client.py`
- `src/stormhelm/ui/controllers/main_controller.py`
- `src/stormhelm/ui/voice_surface.py`
- `tests/test_voice_*.py`
- `docs/voice.md`
- `docs/voice-0-foundation.md`
- `docs/voice-c1-release-readiness.md`

Recommended external docs update group:

- `C:\Users\kkids\Documents\Stormhelm\stormhelm_voice_docs\06_voice_c1_consolidation_release_notes.md`
- `C:\Users\kkids\Documents\Stormhelm\stormhelm_voice_docs\README.md`

Keep separate from the voice commit unless intentionally bundling planner/routing debt:

- `docs/commands.md`
- `docs/features.md`
- `docs/security-and-trust.md`
- `docs/settings.md`
- `src/stormhelm/core/orchestrator/command_eval/corpus.py`
- `src/stormhelm/core/orchestrator/command_eval/runner.py`
- `src/stormhelm/core/orchestrator/intent_frame.py`
- `src/stormhelm/core/orchestrator/planner.py`
- `src/stormhelm/core/orchestrator/planner_v2.py`
- `src/stormhelm/core/orchestrator/route_family_specs.py`
- `tests/test_planner_v2_stabilization_1.py`
- `tests/test_planner_v2_stabilization_2.py`
- untracked planner cleanup tests

Exclude generated/transient artifacts:

- `.pytest_cache/`
- `__pycache__/`
- `.artifacts/` unless a specific artifact is intentionally part of a report
- generated audio/capture files
- logs, temp files, secrets, provider responses, or local live-smoke outputs

## Known Non-Voice Failures

The current full regression baseline is not release-green. The known baseline is `55 failed / 1202 passed`, and the failures are classified as non-voice planner/orchestrator/routing debt. Voice-specific suites are green in the current known baseline, but the repository as a whole should not be described as release-green until the non-voice failures are resolved or explicitly accepted for a release candidate.

Voice release language should distinguish:

- Voice-green: focused voice suites and trust/task slices pass.
- Repo-red: full regression still has known non-voice failures.
- Live-unproven: live OpenAI/local mic/wake/playback smoke tests are opt-in and not run by default.

## Release Posture

Voice-C1 does not change runtime capability. It makes the review and release posture explicit:

- The voice stack is architecturally complete through Voice-20 in mock/fake and disabled-by-default provider modes.
- The most important safety gates have permanent tests: no direct Realtime tools, Core bridge required, response gating, result-state preservation, Voice-16 confirmation, Voice-17 interruption, no always-listening wording, local-only dormant wake, and raw-audio redaction.
- Live provider dogfooding can start only with explicit configuration and the smoke plan above.
- Voice-20 is a hardening milestone, not a promise that every live audio provider path has been exercised on this machine.
