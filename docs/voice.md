# Voice

Stormhelm voice is a bounded input/output surface. It is not an always-listening assistant, and it does not give audio providers authority to run commands. Voice requests enter the same backend-owned core path as typed requests.

Current status: implemented but limited, disabled by default.

Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/bridge.py`, `config/default.toml`
Tests: `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_manual_turn.py`, `tests/test_voice_audio_turn.py`, `tests/test_voice_core_bridge_contracts.py`

## What Works

| Capability | Current behavior | Enabled by default? | Sources | Tests |
|---|---|---:|---|---|
| Manual voice turns | Text treated as a voice-originated turn and sent through the core bridge. | Partly; voice is off by default but manual input config defaults true. | `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/bridge.py` | `tests/test_voice_manual_turn.py`, `tests/test_voice_core_bridge_contracts.py` |
| Controlled audio STT | Bounded file/blob/fixture-style audio metadata can be transcribed through the configured provider path. | No | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_audio_turn.py`, `tests/test_voice_stt_provider.py` |
| TTS artifact generation | Core-approved text or explicit safe test text can be rendered into a controlled speech artifact. | No | `src/stormhelm/core/voice/speech_renderer.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_tts_provider.py`, `tests/test_voice_tts_from_turn_result.py` |
| Push-to-talk capture boundary | Explicit start/stop/cancel/submit actions exist. Local capture is separately gated. | No | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_capture_service.py`, `tests/test_voice_bridge_controls.py` |
| Playback boundary | Playback requests and stop controls exist behind provider/config gates. | No | `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_playback_service.py`, `tests/test_voice_playback_provider.py` |
| Ghost/Deck voice state | The bridge maps backend voice status into compact UI state and voice actions. | UI depends on current worktree files. | `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/controllers/main_controller.py`, `src/stormhelm/ui/voice_surface.py` | `tests/test_voice_ui_state_payload.py`, `tests/test_voice_bridge_controls.py` |

## What Does Not Work Yet

| Request | Current answer |
|---|---|
| Always-listening mode | Not implemented. |
| Wake word | Not implemented. |
| Continuous microphone capture | Not implemented. |
| Realtime voice session | Not implemented. |
| Voice activity detection | Not implemented. |
| Full interruption / barge-in | Not implemented. |
| Voice provider executing tools directly | Not allowed by design. |
| Proof that the user heard audio | Not claimed; playback result is only provider/action state. |

Sources: `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/service.py`, `docs/voice-0-foundation.md`
Tests: `tests/test_voice_availability.py`, `tests/test_voice_events.py`, `tests/test_voice_state.py`

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
| speech synthesis | Last TTS request/result/artifact state. |
| playback | Last playback request/result/error state. |
| truth flags | Explicit no-wake-word/no-realtime/no-always-listening style flags. |

Sources: `src/stormhelm/core/container.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/state.py`
Tests: `tests/test_voice_state.py`, `tests/test_voice_diagnostics.py`

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

## Playback Controls

TTS artifact generation and audio playback are separate. A generated speech artifact does not mean playback occurred.

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/voice/playback/stop -ContentType 'application/json' -Body '{}'
```

To allow local playback during development:

```powershell
$env:STORMHELM_VOICE_PLAYBACK_ENABLED = "true"
$env:STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK = "true"
```

Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/api/app.py`
Tests: `tests/test_voice_playback_service.py`, `tests/test_voice_playback_provider.py`, `tests/test_voice_playback_diagnostics_events.py`

## Safety And Privacy

| Boundary | Current behavior |
|---|---|
| Local-first posture | Voice state, routing, diagnostics, capture controls, and UI state are local. |
| External API | OpenAI STT/TTS requires OpenAI enabled and an API key. |
| Secrets | API keys come from `.env` or environment variables; do not commit keys. |
| Audio retention | Captured and generated audio are not persisted by default. |
| Capture | No always-listening or wake word. Capture is explicit and gated. |
| Command authority | Voice providers do not execute tools; speech-derived requests go through the core bridge. |
| Trust | Voice does not bypass approval, adapter, or safety rules. |

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
