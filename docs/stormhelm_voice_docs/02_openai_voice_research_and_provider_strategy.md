# Stormhelm Voice System — OpenAI Research and Provider Strategy

## 1. Purpose

This document records the OpenAI implementation research for Stormhelm's Voice and Speaking Pipeline and converts it into concrete provider strategy.

This is intentionally written before code implementation. The goal is to prevent the classic engineering disease where somebody says “we'll just use the API” and then three days later the architecture is a haunted accordion full of blocking audio calls and questionable confidence thresholds.

## 2. Official OpenAI Capabilities Relevant to Stormhelm

### 2.1 Speech-to-Text / Transcription API

OpenAI's Audio API provides two speech-to-text endpoints: `transcriptions` and `translations`. Historically those were backed by `whisper-1`, and the current docs list newer transcription model snapshots including:

- `gpt-4o-mini-transcribe`
- `gpt-4o-transcribe`
- `gpt-4o-transcribe-diarize`

The same docs state that supported uploaded audio file formats include `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `wav`, and `webm`, with file uploads currently limited to 25 MB.

### 2.2 Realtime Transcription

OpenAI's Realtime transcription mode supports real-time transcription using microphone input or file input. In transcription-only sessions, the model does not generate responses; this is useful when Stormhelm wants transcript streaming while keeping Stormhelm Core responsible for response generation.

Important Realtime transcription fields:

- input audio format such as 24 kHz mono PCM;
- optional input noise reduction;
- transcription model selection;
- language hint;
- turn detection;
- optional logprobs for confidence calculation.

Relevant session concepts:

```json
{
  "type": "transcription",
  "audio": {
    "input": {
      "format": { "type": "audio/pcm", "rate": 24000 },
      "noise_reduction": { "type": "near_field" },
      "transcription": {
        "model": "gpt-4o-transcribe",
        "language": "en"
      },
      "turn_detection": {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 500
      }
    }
  }
}
```

### 2.3 Realtime VAD / Turn Detection

OpenAI Realtime supports voice activity detection. The docs describe server events for `input_audio_buffer.speech_started` and `input_audio_buffer.speech_stopped`, which can be used to manage speech turns.

The docs describe two VAD modes:

- `server_vad`: chunks audio based on periods of silence.
- `semantic_vad`: chunks audio when the model believes the user has completed the utterance.

Stormhelm should support configuration for both, but should begin with server VAD because it is more mechanically predictable and easier to test.

### 2.4 Text-to-Speech API

OpenAI's TTS endpoint provides speech generation from text and supports streaming audio so playback can begin before the entire audio file is generated.

The docs list built-in voices:

- `alloy`
- `ash`
- `ballad`
- `coral`
- `echo`
- `fable`
- `nova`
- `onyx`
- `sage`
- `shimmer`
- `verse`
- `marin`
- `cedar`

Stormhelm auditioned `cedar`, `marin`, `onyx`, `ash`, `echo`, `sage`, and `verse`; `onyx` is the selected default voice.

### 2.5 Realtime Speech-to-Speech

OpenAI Realtime models support low-latency text/audio input and text/audio output over Realtime transports such as WebRTC, WebSocket, and SIP depending on model and environment.

The current model catalog includes `gpt-realtime-1.5` as a flagship audio-in/audio-out model and `gpt-realtime-mini` as a cost-efficient realtime model. The docs indicate realtime models can support function calling, though Stormhelm must not use provider function calling as authority to execute local actions outside the Core.

## 3. Recommended Stormhelm Provider Modes

Stormhelm should implement voice in two provider modes.

### 3.1 Mode A — Transcribe → Core → TTS

This is the recommended first production path.

```text
wake/manual capture
  -> capture utterance
  -> OpenAI transcription
  -> transcript enters Stormhelm Core
  -> planner/routes/tools/trust respond
  -> SpokenResponseRenderer creates speech text
  -> OpenAI TTS streams audio
  -> playback manager speaks
```

Advantages:

- Easy to test.
- Keeps Core as the single command authority.
- Easy to log transcripts, confidence, route family, task ID, approval ID.
- Easier to preserve existing typed request flow.
- Lower risk than speech-to-speech tool bridging.
- Clean fallback: if TTS fails, text response remains valid.

Disadvantages:

- More latency than full Realtime speech-to-speech.
- Requires separate STT and TTS calls or sessions.
- Less natural interruption unless playback manager is well-built.

This mode should be the first implementation target.

### 3.2 Mode B — Realtime Transcription Session → Core → TTS

This is the better streaming input path.

```text
wake/manual capture
  -> realtime transcription session
  -> transcript deltas shown in Ghost Mode
  -> VAD commits turn
  -> final transcript enters Core
  -> Core response
  -> TTS output
```

Advantages:

- Faster transcript display.
- Better end-of-speech handling.
- Better state animation while user speaks.
- Still keeps Stormhelm Core as response authority.

Disadvantages:

- Requires persistent session management.
- Needs careful event ordering.
- Needs reconnection handling.

This should be the second implementation target.

### 3.3 Mode C — Realtime Speech-to-Speech with Core Tool Bridge

This is the premium future path.

```text
wake
  -> realtime session
  -> model receives audio
  -> model may produce spoken response
  -> any action/tool intent must bridge to Stormhelm Core
  -> Core returns structured tool result
  -> realtime model speaks summarized answer
```

Advantages:

- Most natural low-latency interaction.
- Better interruption and conversational flow.
- Best “living presence” feeling.

Risks:

- Easy to accidentally make OpenAI the planner/action authority.
- Tool calls may drift from Stormhelm's typed route-family law.
- Harder to enforce persona, trust, result states, and verification ceilings.

For Stormhelm, this mode should not be Phase 1. It should only land after the transcribe/Core/TTS path has excellent tests.

## 4. Provider Selection Recommendation

### Initial implementation

Use:

- local wake placeholder/manual push-to-talk;
- OpenAI Speech-to-Text or Realtime transcription;
- Stormhelm Core planner;
- OpenAI TTS streaming;
- local playback manager.

### Later implementation

Add:

- local wake-word engine;
- Realtime transcription with VAD;
- semantic VAD option;
- streaming TTS playback;
- barge-in;
- optional Realtime speech-to-speech after Core bridge is proven.

## 5. Model Configuration Recommendations

Recommended defaults:

```toml
[voice.openai]
input_mode = "transcription"        # "transcription", later "realtime_transcription", later "realtime_conversation"
transcription_model = "gpt-4o-transcribe"
transcription_model_fast = "gpt-4o-mini-transcribe"
tts_model = "gpt-4o-mini-tts"
realtime_model = "gpt-realtime-1.5"
realtime_model_fast = "gpt-realtime-mini"
voice = "onyx"
fallback_voice = "marin"
```

Important: exact model availability should be checked by Codex in the repo/config/API environment at implementation time, because model naming and access can change. The config should fail honestly if a configured model is unavailable.

## 6. Wake Word Strategy

OpenAI should not handle wake-word detection while Stormhelm is dormant.

Recommended interface:

```python
class WakeWordProvider(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def set_enabled(self, enabled: bool) -> None: ...
    def events(self) -> AsyncIterator[WakeWordEvent]: ...
```

Recommended providers:

- `manual`: no wake word, only hotkey/push-to-talk.
- `mock`: deterministic test provider.
- `local_keyword`: future Windows/local wake provider.
- `porcupine`/other engine: optional later provider behind adapter boundary.

Stormhelm should not commit to a third-party wake library in the first document pack. It should define the provider seam and use manual/mock first.

## 7. Audio Capture Strategy

Recommended interface:

```python
class AudioInputProvider(Protocol):
    def list_devices(self) -> list[AudioDevice]: ...
    def start_capture(self, config: AudioCaptureConfig) -> None: ...
    def stop_capture(self) -> None: ...
    def frames(self) -> AsyncIterator[AudioFrame]: ...
```

Audio capture should be isolated from OpenAI. The OpenAI provider should receive normalized audio chunks or temporary audio files, not own microphone hardware directly.

This allows:

- mock audio tests;
- future device selection;
- local VAD experimentation;
- wake-word/local capture separation;
- no cloud audio before wake.

## 8. OpenAI Provider Boundary

Recommended modules:

```text
src/stormhelm/core/voice/
  models.py
  config.py
  service.py
  state.py
  events.py
  renderer.py
  providers/
    base.py
    openai_stt.py
    openai_tts.py
    openai_realtime.py
    local_wake.py
    mock.py
```

Provider objects should be dumb transport/AI wrappers. Stormhelm Core owns intent, action, trust, and final state.

Do not let `openai_realtime.py` become `do_everything.py`. That is not a file; that is a workplace incident.

## 9. Prompting Strategy for OpenAI Transcription

For STT, use prompt hints sparingly:

```text
This audio may include Stormhelm command phrases, Windows app names, file names, engineering terms, software package names, route-family names, and nautical-flavored UI labels such as Ghost Mode, Command Deck, Chartroom, Logbook, Watch, Signals, Bearing, Deck, and Core.
```

Do not stuff the full persona bible into STT. Transcription should hear accurately, not become emotionally invested in the ship.

## 10. Prompting Strategy for OpenAI TTS

TTS input should be generated by the SpokenResponseRenderer. It should already be short and persona-aligned.

TTS instructions, if supported by current SDK/model path, should reinforce:

```text
Voice style: calm, composed, deliberate, low-noise, clear diction, restrained warmth, slight gravitas. Avoid chirpy assistant tone, fake pirate dialect, exaggerated emotion, or customer-support cheerfulness.
```

Do not rely on TTS voice alone for persona. Persona belongs in response shaping before TTS.

## 11. Realtime Tool / Function Calling Law

Realtime model function calling may exist, but Stormhelm should treat it as an optional bridge signal only.

Allowed:

```text
Realtime model hears user audio and produces a structured intent event for Stormhelm Core.
Stormhelm Core validates, plans, gates, executes, verifies, and returns result.
Realtime model or TTS speaks the approved result.
```

Disallowed:

```text
Realtime model directly calls OS/app actions outside Stormhelm's planner/trust/adapter layer.
```

Function calls must map to one of these narrow Core-owned operations:

- `submit_voice_transcript`
- `request_core_plan`
- `continue_task`
- `cancel_task`
- `confirm_approval`
- `mute_voice`
- `stop_speaking`

Not:

- `delete_file`
- `send_discord_message`
- `install_software`
- `click_button`

Those belong to Stormhelm subsystems and require normal authority.

## 12. Cost and Latency Strategy

Voice can become expensive if always streamed.

Cost control:

- no cloud audio before wake;
- configurable inactivity timeout;
- stop session when Dormant;
- use transcription-only mode for input where possible;
- short spoken responses;
- no speaking long debug dumps;
- optional fast model for low-risk transcriptions;
- no raw full conversation restatement into every TTS request.

Latency control:

- local wake detection;
- stream transcription deltas to UI;
- use VAD to commit quickly;
- begin TTS streaming playback when audio chunks arrive;
- keep Core response short for voice paths;
- route simple actions through deterministic paths rather than slow generic provider reasoning.

## 13. Provider Failure Matrix

| Failure | Correct Behavior |
|---|---|
| OpenAI disabled | Voice unavailable. UI says provider disabled. |
| API key missing | Voice unavailable. Settings/debug show missing credentials. |
| STT failure | Do not send guessed command. Ask retry or show failure. |
| Low-confidence transcript | Show transcript candidate and ask narrow clarification. |
| TTS failure | Keep text response visible. Emit `speech_output_failed`. |
| Playback failure | Stop speaking state. UI remains truthful. |
| Realtime disconnect | Return to typed/Ghost text state; attempt reconnect only if allowed. |
| Model unavailable | Voice unavailable/degraded; do not silently switch to unknown behavior unless configured. |
| Network loss | Local wake may remain; OpenAI voice unavailable. |

## 14. Recommended First OpenAI Implementation Slice

Build this first:

```text
manual push-to-talk
  -> record short utterance to temp WAV/webm
  -> OpenAI transcription endpoint
  -> transcript to Core
  -> Core response
  -> SpokenResponseRenderer
  -> OpenAI speech endpoint streaming
  -> playback
```

This proves the most important chain without prematurely building a real-time kraken with eight tentacles and invoices.

## 15. OpenAI Source References

Official OpenAI documentation consulted:

- Speech to text: https://developers.openai.com/api/docs/guides/speech-to-text
- Text to speech: https://developers.openai.com/api/docs/guides/text-to-speech
- Realtime transcription: https://developers.openai.com/api/docs/guides/realtime-transcription
- Realtime VAD: https://developers.openai.com/api/docs/guides/realtime-vad
- Realtime WebRTC: https://developers.openai.com/api/docs/guides/realtime-webrtc
- Model catalog / realtime models: https://developers.openai.com/api/docs/models

## 16. Final Provider Strategy

Stormhelm should begin with a disciplined, testable OpenAI path:

```text
local/manual wake -> STT -> Stormhelm Core -> spoken renderer -> TTS
```

Then graduate to:

```text
local wake -> Realtime transcription + VAD -> Stormhelm Core -> streaming TTS
```

Only after that should it consider:

```text
local wake -> Realtime speech-to-speech with Core tool bridge
```

Stormhelm's voice should become alive slowly and legally. No audio goblin receives admiral rank on day one.
