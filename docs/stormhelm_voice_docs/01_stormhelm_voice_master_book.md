# Stormhelm Voice System — Master Book

## 1. Purpose

This document is the source-of-truth product and system book for Stormhelm's Voice and Speaking Pipeline.

Voice is a major Stormhelm subsystem. It is not a microphone button, not a generic dictation feature, not an isolated voice assistant, and not a shortcut around the existing Core. It is the spoken invocation and response layer for Stormhelm's existing command presence.

Stormhelm should be able to:

- remain dormant and quiet until summoned;
- wake through a local wake-word path;
- capture a spoken request after wake;
- detect when the user has finished speaking;
- transcribe or understand the request through the OpenAI voice provider;
- pass the resulting command into Stormhelm Core exactly like a typed request;
- route through planner, trust, approvals, tools, tasks, adapters, recovery, and verification;
- render a spoken answer using Stormhelm's own persona;
- speak through OpenAI TTS or Realtime audio output;
- surface listening/thinking/speaking state through Ghost Mode and Command Deck;
- remain truthful about what was heard, what was understood, what was done, and what still requires confirmation.

The microphone goblin is allowed aboard the vessel. It is not allowed to steer without a captain, a map, a trust gate, and adult supervision.

## 2. Governing Product Doctrine

Stormhelm is an omnipresent naval intelligence: a calm command presence that can either act through the existing desktop in Ghost Mode or unfold into Command Deck for deeper coordination. Voice must reinforce this identity.

Voice must preserve the existing state ladder:

1. Dormant
2. Wake detected
3. Ghost Mode listening
4. Capturing / turn detection
5. Transcribing / understanding
6. Planning / thinking
7. Acting / awaiting confirmation / blocked / failed
8. Speaking
9. Returning to listening or Dormant
10. Escalating to Command Deck when a richer workspace is needed

Stormhelm's design already treats Ghost Mode as the low-friction summoned overlay and Command Deck as the deeper collaborative workspace. Voice should make that feel natural: a short spoken request should stay in Ghost Mode, while long-running, multi-artifact, debugging, research, or planning work can expand into Command Deck.

## 3. Core Principle

Voice is an input/output surface.

Voice must not become a separate assistant.

The correct chain is:

```text
Local wake detector
  -> Stormhelm voice session state
  -> microphone capture
  -> OpenAI STT / Realtime understanding
  -> Stormhelm Core request
  -> planner / trust / tasks / tools / adapters / recovery / verification
  -> response object
  -> spoken response renderer
  -> OpenAI TTS / Realtime audio output
  -> playback manager
  -> Ghost / Deck visible state
```

The wrong chain is:

```text
Microphone
  -> OpenAI model directly decides what to do
  -> tools/actions happen outside Stormhelm's law
```

That second chain is how the goblin gets a fake captain's hat and starts deleting folders because it heard “clean this up” from across the room. Absolutely not.

## 4. OpenAI Dependency Rule

Stormhelm's voice system is an OpenAI-backed subsystem.

Voice availability must be computed from provider readiness:

```text
voice_available = voice.enabled
               && openai.enabled
               && openai.credentials_valid
               && voice.provider == "openai"
               && required_models_configured_or_defaultable
```

If OpenAI is disabled, missing credentials, blocked by policy, unavailable, or explicitly disabled in config, voice must be disabled cleanly.

Stormhelm may still support non-voice typed interaction when OpenAI voice is unavailable, but it must not pretend voice is partially available if it cannot capture, understand, and speak through the configured provider.

Required user-facing posture:

- `voice.disabled_config`: Voice disabled by configuration.
- `voice.disabled_openai`: OpenAI provider is disabled.
- `voice.unavailable_credentials`: OpenAI credentials are missing or invalid.
- `voice.unavailable_network`: Voice provider cannot be reached.
- `voice.unavailable_model`: Required voice model is unavailable.
- `voice.ready`: Voice provider ready.

## 5. Local Wake Word Doctrine

The wake word must be local-first.

Stormhelm should not stream idle room audio to OpenAI just to determine whether it was summoned. The privacy/trust boundary is:

```text
Before wake: local wake detection only.
After wake: explicit voice session may use OpenAI audio services.
```

Canonical wake word:

```text
Stormhelm
```

Optional future aliases:

```text
Helm
At the helm
Stormhelm, listen
```

Wake aliases must be explicit, configurable, and inspectable. Do not silently add cute phrases because a demo looked cool. Demos are where goblins learn bad habits.

## 6. Wake Response Doctrine

Stormhelm should acknowledge wake with concise spoken presence. The wake response should feel like signal acquisition, not customer support.

Acceptable wake response families:

- `Ready.`
- `Listening.`
- `Bearing acquired.`
- `Signal acquired.`
- `At the helm.`
- `Go ahead.`

Avoid:

- `Hi! How can I help you today?`
- `Ahoy matey!`
- `What can I do for you?`
- `How may I assist you?`
- overexcited, bubbly, or generic assistant greetings

Stormhelm should not turn into a phone assistant wearing a pirate Halloween costume. The vibe is mythic command intelligence, not “Siri found a sextant.”

## 7. Speech Input Doctrine

Stormhelm must support these input modes, phased over time:

### 7.1 Push-to-talk / manual capture

Early implementation mode. The user triggers listening manually. This avoids wake-word complexity and proves the speech-to-Core pipeline.

### 7.2 Wake-word capture

Dormant local detector hears the wake word, moves into Ghost Mode, and begins capture.

### 7.3 Streaming Realtime capture

Low-latency streaming audio using OpenAI Realtime transcription or speech-to-speech session.

### 7.4 Fallback batch transcription

Short captured utterance saved locally in memory or temp file, sent to OpenAI Speech-to-Text endpoint, transcript returns to Core.

## 8. End-of-Speech / Turn Detection Doctrine

Stormhelm must distinguish wake detection from turn completion.

Wake detection answers:

```text
Should Stormhelm start listening?
```

Turn detection answers:

```text
Has the user finished this request?
```

Turn detection may be local or provider-assisted, but the recommended higher-quality path is OpenAI Realtime turn detection with VAD. Stormhelm should support both silence-based and semantic turn detection where provider capabilities allow.

Important states:

- `speech_started`
- `speech_stopped`
- `turn_committed`
- `transcript_delta`
- `transcript_final`
- `turn_rejected_noise`
- `turn_rejected_empty`
- `turn_rejected_low_confidence`

## 9. Speech Output Doctrine

Stormhelm should not simply read raw text answers aloud.

Text response and spoken response are different render targets.

The Core may produce:

```text
- full response text
- structured result cards
- provenance
- warnings
- tool traces
- task state
- verification state
- follow-up affordances
```

The spoken renderer should produce:

```text
- concise spoken answer
- short status confirmation
- next required action
- warning or confirmation prompt if needed
```

Example:

Text / Deck response:

```text
I found three Java paths:
1. C:\Program Files\Java
2. C:\Program Files\Eclipse Adoptium
3. C:\Users\Kato\AppData\Local\Programs\Java

JAVA_HOME points to Eclipse Adoptium, so that appears to be the active runtime.
```

Spoken response:

```text
I found three Java paths. Eclipse Adoptium appears active; JAVA_HOME points there.
```

Stormhelm speaks the bearing, not the whole nautical chart unless asked.

## 10. Persona and Voice Identity Doctrine

Stormhelm must speak like Stormhelm.

The voice should be:

- mid-to-low register if possible;
- calm;
- smooth;
- deliberate;
- clear;
- composed;
- slightly synthetic if necessary;
- never frantic;
- never cartoonishly robotic;
- never chirpy.

OpenAI voice selection should be treated as a configurable canonical profile:

```toml
[voice.speech]
voice = "cedar"   # candidate default
speed = 0.92       # if supported by provider/client playback layer
style = "stormhelm_default"
```

Candidate voices to audition:

- `cedar`
- `marin`
- `onyx`
- `echo`
- `sage`

Final choice should be made by actual listening tests, not by voice-name astrology. Voice-name astrology is how engineering projects begin wearing crystals.

## 11. Spoken Persona Renderer

Create a `SpokenResponseRenderer` / `VoiceResponseComposer` that converts Core results into speech.

Required inputs:

- Core response text
- route family
- result state
- action state
- trust / approval state
- confirmation requirement
- verification state
- mode: Dormant / Ghost / Deck
- verbosity preference
- user requested detail level
- failure state
- persona profile

Required outputs:

- `speech_text`
- `display_text`
- `speech_priority`
- `can_interrupt`
- `requires_confirmation`
- `confirmation_phrase_set`
- `should_continue_listening`
- `should_return_to_dormant`
- `spoken_disclosure_required`

The renderer should enforce:

- one sentence for simple actions;
- two to three sentences for most spoken answers;
- no long tables or code aloud;
- no unsupported certainty;
- no generic assistant closers;
- no fake pirate dialect;
- no “I did it” unless Core state supports completion or verification.

## 12. Spoken Confirmation Doctrine

Speech creates higher ambiguity than typed input. Confirmation must be stricter.

Sensitive actions require explicit confirmation through existing trust policy. Voice may collect the confirmation, but trust still owns validation.

Sensitive examples:

- installing software
- uninstalling software
- deleting files
- sending messages
- changing startup settings
- changing system settings
- executing commands
- using Discord relay
- clearing memory
- destructive cleanup

Confirmation binding must include:

- `approval_id`
- `task_id`
- `route_family`
- `target_id`
- `action_summary`
- `created_at`
- `expires_at`
- `confirmation_phrase`
- `consumed_once`
- `source = voice`
- `transcript_confidence`

A spoken “yes” must only apply to the currently active, fresh, bound approval prompt. It must not float across tasks like a possessed sticky note.

## 13. Barge-In / Interruption Doctrine

Stormhelm must support interruption.

User speech during playback may mean:

- stop speaking;
- cancel current request;
- pause workflow;
- return to Dormant;
- continue with a correction;
- request detail;
- override with a new command.

Supported interruption intents:

```text
stop
cancel
hold
pause
sleep
mute
never mind
wait
no, I meant...
actually...
```

Implementation should distinguish:

- `audio_stop`: stop playback only
- `request_cancel`: cancel pending / not-yet-executed workflow
- `task_hold`: pause task if task system supports it
- `voice_sleep`: return to Dormant
- `voice_mute`: disable mic or speech output based on context

## 14. Privacy and Trust Doctrine

Voice must feel like invocation, not surveillance.

Requirements:

1. No cloud audio before wake.
2. Visible listening indicator when capture is active.
3. Hard mute disables microphone capture.
4. User can disable wake word.
5. User can disable spoken output.
6. User can view voice provider status.
7. Raw audio is not persisted by default.
8. Transcripts may be stored according to normal message/task memory policy.
9. Debug raw audio is opt-in, time-bounded, and stored locally.
10. Sensitive actions require trust gates.
11. Voice never claims it heard or understood something if the transcript is absent or low confidence.

## 15. Ghost Mode Behavior

Ghost Mode voice should be concise and low-density.

Examples:

```text
User: Stormhelm.
Stormhelm: Bearing acquired.
User: Open Downloads.
Stormhelm: Opening Downloads.
```

```text
User: Stormhelm.
Stormhelm: Listening.
User: What is this error?
Stormhelm: I’m reading the current screen.
Stormhelm: It appears to be a Windows security prompt. I won’t approve it without confirmation.
```

Ghost Mode visible elements:

- central voice core;
- wake/listening/speaking state;
- short transcript line;
- compact response card;
- optional confirmation card;
- optional route/provenance chip;
- no dashboard bloat.

## 16. Command Deck Behavior

Command Deck voice can be more collaborative.

Use Deck when:

- task becomes multi-step;
- files, logs, traces, or browser references matter;
- user asks for a workspace;
- debugging or research requires structure;
- speech would become too long for Ghost Mode;
- confirmation/recovery state needs inspection.

Deck should show:

- transcript history;
- voice session state;
- route and task state;
- approval state;
- tool traces;
- voice event timeline;
- microphone/output provider health;
- spoken renderer preview if debugging.

## 17. Failure Behavior

Voice failures must be truthful.

Examples:

- Wake detected but no speech follows: timeout back to Dormant.
- Low transcript confidence: ask a narrow retry.
- STT fails: state that the signal failed; do not send a guessed command.
- Core fails: show/speak that Core is not responding; try reconnect if allowed.
- TTS fails: show response in Ghost/Deck; do not claim spoken output succeeded.
- Playback fails: emit playback failure and keep text visible.
- OpenAI unavailable: voice unavailable; typed interaction remains available if Core is healthy.
- Network unavailable: local wake may still work, but voice command understanding/speech are disabled or degraded according to provider mode.

## 18. Configuration Doctrine

Recommended configuration skeleton:

```toml
[openai]
enabled = true
api_key_env = "OPENAI_API_KEY"

[voice]
enabled = false
provider = "openai"
mode = "transcribe_then_core_then_tts" # later: realtime_core_bridge
wake_word_enabled = false
wake_word = "stormhelm"
local_wake_provider = "porcupine" # placeholder/provider interface only
manual_push_to_talk_enabled = true
store_transcripts = true
store_raw_audio = false

[voice.input]
device = "default"
sample_rate = 24000
channels = 1
vad_mode = "server_vad"
semantic_vad_enabled = false
noise_reduction = "near_field"
transcription_model = "gpt-4o-transcribe"
confidence_threshold = 0.65

[voice.output]
enabled = true
tts_model = "gpt-4o-mini-tts"
voice = "cedar"
format = "pcm"
streaming = true
interruptible = true

[voice.privacy]
cloud_audio_before_wake = false
show_listening_indicator = true
raw_audio_debug_enabled = false
raw_audio_debug_max_seconds = 20

[voice.trust]
voice_confirmations_enabled = true
confirmation_timeout_seconds = 45
require_exact_sensitive_confirmation = true
```

## 19. Anti-Goals

Do not:

- stream dormant room audio to OpenAI;
- make voice a separate assistant;
- let Realtime function calls bypass Stormhelm Core;
- use OpenAI as the planner authority for local actions;
- speak every debug detail aloud;
- store raw audio by default;
- execute sensitive actions from vague speech;
- claim “sent,” “installed,” “deleted,” or “fixed” without Core evidence;
- make Ghost Mode chatty;
- turn Stormhelm into a pirate caricature;
- bury users in voice settings before the basic pipeline works.

## 20. Recommended Document Stack

This documentation pack is split into:

1. Master Book — product doctrine and system boundaries.
2. OpenAI Research and Provider Strategy — current official API findings and provider choices.
3. Architecture and Data Contracts — backend modules, state machines, events, objects.
4. Implementation Roadmap and Codex Prompt — staged build plan and prompt packet.
5. Acceptance and Test Book — pass/fail law, scenario tests, regression tests.

## 21. Final Master Statement

Stormhelm voice should feel like a command presence surfacing from the system: quiet until summoned, precise when listening, truthful when uncertain, composed when acting, and unmistakably Stormhelm when it speaks.

The microphone goblin may speak only after it has filed its paperwork with the Core.
