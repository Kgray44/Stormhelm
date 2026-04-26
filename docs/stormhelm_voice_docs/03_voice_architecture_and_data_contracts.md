# Stormhelm Voice System — Architecture and Data Contracts

## 1. Purpose

This document defines the concrete architecture, state model, typed data contracts, event flow, and integration seams for Stormhelm's Voice and Speaking Pipeline.

It is intended for implementation planning and Codex handoff. It should be treated as design law until superseded by a later Voice hardening document.

## 2. Existing Stormhelm Architecture Assumptions

Stormhelm already follows a service-first pattern:

- background Core owns orchestration, jobs, tools, safety, persistence, and logs;
- UI connects to Core over local IPC / local HTTP;
- UI renders state and should not own assistant logic;
- future voice components were already expected to plug into the Core as adapters;
- orchestrator should accept text requests from either typed chat or voice transcription without caring which source produced the text.

Voice must extend this architecture, not collapse it.

Correct ownership:

| Concern | Owner |
|---|---|
| Microphone device access | Voice input provider |
| Wake detection | Local wake provider |
| Speech transcription | OpenAI STT / Realtime provider |
| Request authority | Stormhelm Core |
| Route selection | Planner / orchestrator |
| Safety/trust/approval | Trust subsystem |
| Task continuity | Task graph / durable task state |
| Action execution | Existing tools/adapters/subsystems |
| Verification | Existing verification layer |
| Spoken copy | Voice response renderer |
| Audio generation | OpenAI TTS / Realtime audio provider |
| Playback | Local playback manager |
| Visual state | Ghost Mode / Command Deck UI |

## 3. Module Layout

Recommended package:

```text
src/stormhelm/core/voice/
  __init__.py
  config.py
  models.py
  events.py
  state.py
  service.py
  renderer.py
  privacy.py
  confidence.py
  diagnostics.py
  providers/
    __init__.py
    base.py
    mock.py
    local_wake.py
    audio_input.py
    audio_output.py
    openai_stt.py
    openai_tts.py
    openai_realtime.py
  tests/
    fixtures_audio/
```

Possible UI package additions:

```text
src/stormhelm/ui/voice/
  voice_state_model.py
  voice_core_bridge.py
  voice_settings_panel.py
```

Possible QML additions later:

```text
ui/qml/components/VoiceCore.qml
ui/qml/components/VoiceTranscriptBand.qml
ui/qml/components/VoiceConfirmationCard.qml
ui/qml/components/VoiceProviderStatus.qml
```

## 4. Top-Level Voice Service

`VoiceService` is the coordinator. It does not own all logic directly. It wires providers, state, Core request submission, spoken rendering, and playback.

Responsibilities:

- compute voice availability;
- start/stop voice subsystem;
- manage wake/listen/capture/speak state;
- route audio frames to provider;
- convert final transcript into Core request;
- receive Core response;
- ask renderer for spoken text;
- request audio generation;
- manage playback;
- emit voice events to Core event bus;
- expose status/debug snapshot;
- enforce privacy settings.

Non-responsibilities:

- planning actions;
- executing tools;
- deciding trust policy;
- verifying actions;
- owning UI rendering;
- storing long-term memory directly.

## 5. Core Voice State Machine

Canonical states:

```text
disabled
unavailable
dormant
wake_listening
wake_detected
listening
capturing
speech_detected
turn_committing
transcribing
transcript_ready
submitting_to_core
thinking
awaiting_confirmation
acting
speaking
interrupted
muted
sleeping
error
```

Recommended transition skeleton:

```text
disabled -> unavailable/ready only after config changes
ready -> dormant
dormant -> wake_listening if wake enabled
wake_listening -> wake_detected
wake_detected -> listening
listening -> speech_detected
speech_detected -> capturing
capturing -> turn_committing
turn_committing -> transcribing
transcribing -> transcript_ready
transcript_ready -> submitting_to_core
submitting_to_core -> thinking
thinking -> awaiting_confirmation | acting | speaking | error
awaiting_confirmation -> listening | dormant | expired
speaking -> listening | dormant | interrupted
interrupted -> listening | dormant | cancelled
error -> dormant | unavailable
```

## 6. Voice Mode Types

```python
class VoiceMode(str, Enum):
    DISABLED = "disabled"
    MANUAL_PUSH_TO_TALK = "manual_push_to_talk"
    LOCAL_WAKE_TRANSCRIBE_TTS = "local_wake_transcribe_tts"
    REALTIME_TRANSCRIPTION_TTS = "realtime_transcription_tts"
    REALTIME_CONVERSATION_CORE_BRIDGE = "realtime_conversation_core_bridge"
```

## 7. Voice Availability Contract

```python
@dataclass(frozen=True)
class VoiceAvailability:
    available: bool
    reason: str
    openai_enabled: bool
    voice_enabled: bool
    credentials_present: bool
    provider: str
    input_ready: bool
    output_ready: bool
    wake_ready: bool
    transcription_ready: bool
    speech_ready: bool
    realtime_ready: bool
    degraded: bool = False
    degraded_reason: str | None = None
```

Rules:

- `available = false` if OpenAI is disabled.
- `available = false` if voice config is disabled.
- `degraded = true` only when a supported partial mode remains truthful, such as typed output with no TTS.
- Do not show “ready” unless at least one full configured voice mode can work.

## 8. Audio Device Contract

```python
@dataclass(frozen=True)
class AudioDevice:
    id: str
    name: str
    kind: Literal["input", "output"]
    is_default: bool
    sample_rates: list[int]
    channels: list[int]
```

```python
@dataclass(frozen=True)
class AudioCaptureConfig:
    device_id: str | None
    sample_rate: int = 24000
    channels: int = 1
    frame_ms: int = 20
    max_utterance_seconds: float = 30.0
    pre_roll_ms: int = 300
```

## 9. Wake Event Contract

```python
@dataclass(frozen=True)
class WakeWordEvent:
    event_id: str
    detected_at: datetime
    wake_word: str
    provider: str
    confidence: float | None
    audio_sent_to_cloud: bool = False
```

Hard rule:

```text
audio_sent_to_cloud must be false for wake detection.
```

## 10. Speech Turn Contract

```python
@dataclass
class VoiceTurn:
    turn_id: str
    source: Literal["voice"]
    started_at: datetime
    ended_at: datetime | None
    wake_event_id: str | None
    mode: VoiceMode
    transcript: str | None = None
    transcript_confidence: float | None = None
    transcript_alternatives: list[str] = field(default_factory=list)
    language: str | None = "en"
    vad_mode: str | None = None
    noise_reduction: str | None = None
    audio_persisted: bool = False
    raw_audio_path: str | None = None
    rejected_reason: str | None = None
```

## 11. Transcript Confidence Contract

```python
@dataclass(frozen=True)
class TranscriptConfidence:
    confidence: float | None
    source: str
    logprob_available: bool
    low_confidence: bool
    contains_uncertain_tokens: bool
    requires_confirmation: bool
    reason: str | None
```

Confidence handling:

- If logprobs are available, calculate transcript confidence.
- If not, treat confidence as unknown, not high.
- Low confidence does not automatically block harmless questions, but it must block or clarify sensitive actions.
- For sensitive actions, exact or near-exact target matters.

## 12. Core Submission Contract

Voice requests should become normal Core requests with extra source metadata.

```python
@dataclass(frozen=True)
class VoiceCoreRequest:
    request_id: str
    turn_id: str
    text: str
    source: Literal["voice"]
    input_mode: VoiceMode
    transcript_confidence: TranscriptConfidence
    wake_event_id: str | None
    session_id: str | None
    task_id: str | None
    ui_mode: Literal["ghost", "deck", "none"]
    created_at: datetime
```

Core must see this as:

```text
user text + source metadata
```

not as:

```text
provider already decided what to do
```

## 13. Spoken Response Contract

```python
@dataclass(frozen=True)
class SpokenResponseRequest:
    core_response_id: str
    route_family: str | None
    result_state: str
    full_text: str
    structured_cards: list[dict]
    trust_state: str | None
    verification_state: str | None
    ui_mode: Literal["ghost", "deck"]
    user_requested_detail: bool
    max_spoken_sentences: int
```

```python
@dataclass(frozen=True)
class SpokenResponse:
    speech_id: str
    text: str
    voice: str
    priority: Literal["low", "normal", "high", "urgent"]
    interruptible: bool
    should_speak: bool
    reason_if_silent: str | None
    disclosure_required: bool
    associated_core_response_id: str
```

## 14. TTS Request Contract

```python
@dataclass(frozen=True)
class TextToSpeechRequest:
    speech_id: str
    text: str
    model: str
    voice: str
    format: Literal["pcm", "mp3", "wav", "opus"]
    stream: bool
    style_hint: str | None
```

```python
@dataclass(frozen=True)
class TextToSpeechResult:
    speech_id: str
    ok: bool
    audio_stream_id: str | None
    audio_file_path: str | None
    duration_ms: int | None
    error: str | None
```

## 15. Playback Contract

```python
@dataclass(frozen=True)
class PlaybackState:
    speech_id: str | None
    state: Literal["idle", "buffering", "playing", "paused", "stopped", "failed"]
    started_at: datetime | None
    ended_at: datetime | None
    interrupted_by_user: bool
    error: str | None
```

Playback manager responsibilities:

- play streaming audio;
- stop immediately on barge-in / stop;
- report playback errors;
- not block Core event loop;
- expose current speaking state to UI;
- never claim speech completed if playback failed.

## 16. Voice Event Taxonomy

Recommended event names:

```text
voice.availability.changed
voice.wake.listening_started
voice.wake.detected
voice.wake.timeout
voice.capture.started
voice.capture.speech_started
voice.capture.speech_stopped
voice.capture.turn_committed
voice.transcript.delta
voice.transcript.completed
voice.transcript.low_confidence
voice.transcript.failed
voice.core.submitted
voice.core.response_received
voice.speech.rendered
voice.tts.requested
voice.tts.stream_started
voice.tts.completed
voice.tts.failed
voice.playback.started
voice.playback.completed
voice.playback.interrupted
voice.confirmation.requested
voice.confirmation.heard
voice.confirmation.rejected
voice.muted
voice.unmuted
voice.error
```

Each event should include:

- timestamp;
- voice session ID;
- turn ID if applicable;
- provider;
- UI mode;
- task ID if applicable;
- privacy posture if relevant;
- error code if relevant.

## 17. Confirmation Contract

```python
@dataclass(frozen=True)
class VoiceConfirmationCandidate:
    transcript: str
    transcript_confidence: float | None
    approval_id: str
    task_id: str | None
    action_summary: str
    target_summary: str
    created_at: datetime
    expires_at: datetime
    accepted: bool
    rejected_reason: str | None
```

Acceptance rules:

- Must match current pending approval.
- Must not be stale.
- Must not be already consumed.
- Must meet transcript confidence threshold for sensitive actions.
- Must be bound to task/action/target.
- Must not apply across route families.

## 18. Privacy Contract

```python
@dataclass(frozen=True)
class VoicePrivacyPosture:
    cloud_audio_before_wake: bool
    raw_audio_persisted: bool
    transcript_persisted: bool
    visible_capture_indicator: bool
    debug_audio_enabled: bool
    debug_audio_retention_seconds: int
```

Hard defaults:

```python
cloud_audio_before_wake = False
raw_audio_persisted = False
visible_capture_indicator = True
debug_audio_enabled = False
```

## 19. Diagnostics Snapshot

```python
@dataclass(frozen=True)
class VoiceDiagnosticsSnapshot:
    available: bool
    state: str
    mode: str
    provider: str
    wake_provider: str
    input_device: str | None
    output_device: str | None
    transcription_model: str | None
    tts_model: str | None
    realtime_model: str | None
    last_wake_at: datetime | None
    last_turn_id: str | None
    last_transcript_confidence: float | None
    last_error: str | None
    active_speech_id: str | None
    muted: bool
    raw_audio_persisted: bool
```

This should feed Watch / Systems / Command Deck debug surfaces.

## 20. Ghost Mode UI State Contract

```python
@dataclass(frozen=True)
class GhostVoiceState:
    voice_state: str
    core_text: str | None
    partial_transcript: str | None
    final_transcript: str | None
    compact_response: str | None
    confirmation_card: dict | None
    provider_status: str
    muted: bool
    listening_visible: bool
    speaking_visible: bool
    route_family: str | None
    result_state: str | None
```

Ghost Mode should show only the minimum needed state. If this object starts looking like a cockpit made of JSON soup, it belongs in Command Deck.

## 21. Command Deck UI State Contract

```python
@dataclass(frozen=True)
class DeckVoicePanelState:
    voice_state: str
    session_id: str | None
    active_turn: VoiceTurn | None
    recent_turns: list[VoiceTurn]
    provider_snapshot: VoiceDiagnosticsSnapshot
    events: list[dict]
    pending_confirmation: dict | None
    spoken_response_preview: str | None
    transcript_confidence: TranscriptConfidence | None
    settings_summary: dict
```

Command Deck can expose deeper details for debugging, testing, and tuning.

## 22. Integration with Event Streaming

Voice should publish state changes through the existing push/event streaming system when available.

Important:

- UI should not poll aggressively for waveform/turn state forever.
- High-frequency audio frames should not be pushed into general event logs.
- Publish semantic voice events, not raw audio.

Correct:

```text
voice.capture.speech_started
voice.transcript.delta
voice.transcript.completed
voice.playback.started
```

Incorrect:

```text
voice.audio_frame.000001
voice.audio_frame.000002
voice.audio_frame.000003
```

Please do not turn the event bus into an audio smoothie.

## 23. Integration with Task Graph

Voice turns may start, continue, or cancel tasks.

Voice metadata should attach to task events:

- source = voice;
- turn ID;
- transcript;
- transcript confidence;
- confirmation source;
- spoken response ID.

If a spoken command starts a multi-step task, the task graph owns continuity. Voice only provides a command source and output channel.

## 24. Integration with Trust and Approvals

Voice must call the same approval subsystem used by typed requests.

Voice may:

- present approval prompts;
- speak approval request summaries;
- capture approval confirmations;
- reject stale confirmations;
- show confidence warnings.

Voice may not:

- lower approval requirements;
- auto-confirm from vague speech;
- use “yes” without binding;
- treat wake response as consent.

## 25. Integration with Memory

By default:

- transcript can be stored as normal conversation text;
- raw audio is not stored;
- voice settings/preferences may be stored;
- voice confidence and source metadata may attach to messages/tasks;
- failed transcripts should not become long-term semantic memory unless explicitly useful and safe.

Memory record example:

```json
{
  "source": "voice",
  "transcript": "open downloads",
  "confidence": 0.91,
  "raw_audio_stored": false,
  "turn_id": "voice_turn_..."
}
```

## 26. Integration with Screen Awareness

Voice and screen awareness combine naturally for commands like:

- “What is this?”
- “Click that later”
- “Explain this error”
- “Send this to Baby”
- “What button should I press?”

But voice must not invent screen context. It should submit the spoken request to Core; screen-awareness subsystem resolves deictics like “this” and “that” using its own evidence and truthfulness rules.

## 27. Security and Secrets

OpenAI API keys must remain in environment/config secret handling, not source code.

Voice provider must read credentials through existing secret/config paths.

Never log:

- API keys;
- full Authorization headers;
- raw audio by default;
- sensitive transcripts in debug logs beyond normal configured message logging.

## 28. Error Codes

Recommended voice error codes:

```text
voice_config_disabled
openai_disabled
openai_credentials_missing
openai_auth_failed
input_device_missing
output_device_missing
wake_provider_unavailable
capture_failed
transcription_failed
transcription_low_confidence
tts_failed
playback_failed
provider_timeout
provider_rate_limited
core_unavailable
confirmation_stale
confirmation_low_confidence
confirmation_wrong_task
privacy_policy_blocked
```

## 29. First Implementation Target

The first implementation should create the entire typed spine even if most providers are mocked.

Minimum first pass:

- config models;
- state machine;
- mock wake provider;
- manual push-to-talk seam;
- mock STT provider;
- mock TTS provider;
- spoken renderer skeleton;
- Core submission path;
- UI status snapshot;
- tests.

Second pass:

- OpenAI STT;
- OpenAI TTS;
- short manual audio capture;
- playback.

Third pass:

- realtime transcription;
- VAD;
- barge-in;
- local wake provider.

## 30. Definition of Architectural Done

This architecture is ready for implementation when:

- voice can be enabled/disabled from config;
- provider readiness is explicit;
- voice state is typed;
- voice events are emitted;
- transcript-to-Core path is source-aware;
- spoken response rendering is separate from Core text output;
- TTS/playback result is truthful;
- trust approval binding exists;
- raw audio persistence is off by default;
- UI can render voice state without owning voice logic;
- tests prove voice does not bypass planner/trust.

## 31. Final Architecture Statement

Stormhelm voice is a disciplined signal path: wake locally, hear through OpenAI, think through Stormhelm Core, speak through Stormhelm persona, and act only through existing lawful subsystems.

The voice pipeline is allowed to sound magical. It is not allowed to be architecturally magical. Those are different beasts. One is delightful. The other eats weekends.
