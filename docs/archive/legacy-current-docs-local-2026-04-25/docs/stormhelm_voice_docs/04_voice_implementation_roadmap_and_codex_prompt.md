# Stormhelm Voice System — Implementation Roadmap and Codex Prompt

## 1. Purpose

This document defines the phased implementation plan for Stormhelm's Voice and Speaking Pipeline and includes a Codex-ready implementation prompt.

The goal is to build voice like a real Stormhelm subsystem: scoped, typed, testable, provider-gated, and Core-owned. No “let's just connect a mic and hope the kraken is friendly” engineering.

## 2. Rollout Philosophy

Voice should be implemented in phases:

1. Build the state/contracts first.
2. Prove transcript-to-Core routing with mocks.
3. Add OpenAI STT/TTS in a manual voice path.
4. Add spoken renderer/persona hardening.
5. Add local wake detection.
6. Add realtime transcription/VAD.
7. Add interruption/barge-in.
8. Add Command Deck diagnostics and evaluation.
9. Only then consider full realtime speech-to-speech with Core bridge.

This preserves the existing Stormhelm law:

```text
Voice is an input/output surface, not a bypass.
```

## 3. Recommended Phase Breakdown

## Phase Voice-0 — Foundations, Config, and State Spine

### Mission

Create the Voice subsystem skeleton with typed config, availability, state, events, provider interfaces, and tests. No real microphone/OpenAI calls yet.

### Build Now

- `voice.enabled` config.
- `openai.enabled` dependency check.
- voice mode enum.
- voice availability snapshot.
- voice state machine.
- provider interfaces:
  - wake provider;
  - audio input provider;
  - STT provider;
  - TTS provider;
  - playback provider.
- mock providers for tests.
- voice diagnostics snapshot.
- core event emissions.
- basic UI/bridge status surface.

### Non-Scope

- real microphone capture;
- real OpenAI calls;
- wake word engine;
- realtime sessions;
- actual playback;
- direct actions.

### Acceptance

- Voice disabled if OpenAI disabled.
- Voice disabled if voice disabled.
- UI sees truthful voice status.
- Voice request cannot bypass Core.
- Tests prove state transitions.

## Phase Voice-1 — Manual Push-to-Talk Transcript to Core

### Mission

Prove that a voice-like transcript enters the same Core/planner/orchestrator boundary as typed input.

### Build Now

- manual voice request endpoint or internal event;
- mock transcript submission;
- `VoiceCoreRequest` metadata;
- source = voice;
- Core response returned;
- Ghost Mode compact voice response state;
- tests for route preservation.

### Non-Scope

- real audio;
- TTS;
- wake word;
- realtime.

### Acceptance

- “open downloads” as voice routes the same as typed request.
- sensitive requests still require approval.
- route family and source metadata are preserved.

## Phase Voice-2 — OpenAI Speech-to-Text Provider

### Mission

Add OpenAI transcription for short captured utterances in manual mode.

### Build Now

- short audio capture from selected/default mic;
- local temp audio handling;
- OpenAI transcription provider;
- configurable model;
- transcript confidence handling where available;
- failure states;
- privacy posture: raw audio not persisted by default.

### Non-Scope

- wake word;
- realtime streaming;
- TTS;
- semantic VAD;
- barge-in.

### Acceptance

- captured speech becomes transcript;
- transcript submits to Core;
- failed transcription does not send guessed command;
- raw audio deleted unless debug enabled.

## Phase Voice-3 — Spoken Response Renderer and OpenAI TTS

### Mission

Make Stormhelm speak responses using persona-shaped spoken text and OpenAI TTS.

### Build Now

- `SpokenResponseRenderer`;
- mode-aware speech length rules;
- OpenAI TTS provider;
- voice config;
- streaming playback if practical;
- playback state;
- stop-speaking action;
- TTS failure fallback to visible text.

### Non-Scope

- local wake word;
- realtime speech-to-speech;
- long-form narration;
- custom voice cloning.

### Acceptance

- simple action speaks one concise line;
- long response summarizes aloud and leaves details in Deck/Ghost text;
- TTS failure does not claim speech succeeded;
- persona tests reject generic assistant chatter.

## Phase Voice-4 — Trust-Aware Spoken Confirmations

### Mission

Voice can capture confirmation for existing approval prompts without weakening trust.

### Build Now

- approval-bound voice confirmation model;
- transcript confidence threshold for confirmations;
- exact current approval binding;
- stale confirmation rejection;
- consumed-once confirmation behavior;
- spoken confirmation prompts;
- tests for cross-task leakage.

### Non-Scope

- new trust policy;
- broad permission redesign;
- relaxed approvals.

### Acceptance

- “yes” only confirms current fresh approval.
- Low-confidence “yes” does not confirm destructive actions.
- Stale confirmations expire.
- Approval audit records include source=voice.

## Phase Voice-5 — Local Wake Word Provider

### Mission

Add local wake-word detection and transition from Dormant to Ghost Mode.

### Build Now

- wake provider interface implementation;
- mock wake provider for tests;
- optional real local wake engine behind config;
- wake timeout;
- wake response;
- no cloud audio before wake;
- Ghost Mode wake animation/state hooks.

### Non-Scope

- streaming OpenAI before wake;
- always-on cloud capture;
- multiple user voice ID.

### Acceptance

- Wake event enters Ghost Mode.
- No audio is sent to OpenAI before wake.
- Wake timeout returns to Dormant.
- Hard mute stops wake/capture.

## Phase Voice-6 — Realtime Transcription and VAD

### Mission

Move from batch utterance transcription to Realtime transcription with turn detection.

### Build Now

- OpenAI Realtime transcription provider;
- transcript deltas;
- final transcript events;
- VAD state mapping;
- server VAD config;
- optional semantic VAD config;
- event ordering handling;
- reconnection handling.

### Non-Scope

- full speech-to-speech agent;
- provider-owned tool execution;
- broad audio analytics.

### Acceptance

- partial transcript appears while speaking.
- `speech_started` and `speech_stopped` drive UI state.
- final transcript submits once.
- reconnect failure degrades truthfully.

## Phase Voice-7 — Barge-In and Interruption

### Mission

Allow the user to interrupt Stormhelm while it speaks or while a voice-initiated task is pending.

### Build Now

- stop playback;
- cancel pending voice request;
- hold/pause task if supported;
- sleep/mute commands;
- interruption event taxonomy;
- tests for “stop,” “cancel,” “never mind,” “actually.”

### Non-Scope

- cancellation of already-completed actions;
- unsafe rollback claims;
- full workflow undo.

### Acceptance

- “stop” stops speech only.
- “cancel” cancels pending not-yet-executed task.
- Already executed actions are not falsely undone.

## Phase Voice-8 — Command Deck Diagnostics and Evaluation

### Mission

Expose the voice system for debugging and harden it with tests.

### Build Now

- voice diagnostics panel/state;
- transcript confidence display;
- provider status;
- event timeline;
- test corpus for voice utterances;
- latency metrics;
- persona regression tests;
- privacy regression tests.

### Non-Scope

- new user-facing voice studio;
- dashboard bloat;
- raw audio browser by default.

### Acceptance

- Watch/Systems can inspect voice state.
- Tests cover major voice routes/failures.
- Latency and confidence are measured.

## Phase Voice-9 — Realtime Speech-to-Speech Core Bridge

### Mission

Optional future premium mode. Use OpenAI Realtime conversation for natural voice, while all actions remain Core-owned.

### Build Now

- Realtime conversation session;
- narrow tool bridge to Core request submission;
- no direct action tools;
- persona/system prompt;
- interruption improvements;
- result-to-speech bridge.

### Non-Scope

- provider executes local actions;
- provider bypasses planner/trust;
- broad custom assistant outside Stormhelm.

### Acceptance

- Provider can converse, but actions still route through Core.
- Sensitive actions still require approval.
- Tool bridge is narrow and audited.

## 4. Recommended First Codex Sprint

Implement **Phase Voice-0 and Voice-1 only** in the first Codex run.

Why:

- establishes architecture;
- does not require hardware/audio debugging;
- proves Core-owned routing;
- creates typed seams for OpenAI providers;
- avoids mixing design, audio drivers, API calls, and UI all in one flaming cauldron.

The first implementation should be boring in the best engineering way. Boring foundations are sexy. Exploding demos are not.

## 5. Codex Packet Order

Send Codex these documents in this order:

1. Stormhelm Design Book v1 or newer
2. Stormhelm Layout Spec v1 or newer
3. Stormhelm Next Addition 7 Book — Voice and Speaking Pipeline, if available
4. `01_stormhelm_voice_master_book.md`
5. `02_openai_voice_research_and_provider_strategy.md`
6. `03_voice_architecture_and_data_contracts.md`
7. `04_voice_implementation_roadmap_and_codex_prompt.md`
8. `05_voice_acceptance_and_test_book.md`
9. Current repo notes with actual paths for planner, assistant, core API, config, bridge, event streaming, trust, task graph, UI state.

## 6. Small Wrapper Prompt

```text
You are implementing Stormhelm Voice System Phase Voice-0 and Voice-1.

Treat the attached Stormhelm design, layout, and voice-system documents as governing sources. Voice is a major Stormhelm subsystem, but in this pass you are building only the foundational voice spine and manual transcript-to-Core routing. Do not implement real microphone capture, real OpenAI calls, local wake word, realtime sessions, TTS playback, or speech-to-speech behavior yet unless explicitly required as a tiny mock seam.

Stormhelm voice must remain backend-owned, local-first before wake, OpenAI-gated, privacy-aware, typed, truthful, persona-aligned, and strictly subordinate to the Core/planner/trust/task/tool/verification chain.

Mission:
Build the Voice-0 and Voice-1 foundations:
- typed voice config
- OpenAI dependency gating
- voice availability model
- voice state machine
- voice event taxonomy
- provider interfaces
- mock providers
- manual voice transcript submission
- source-aware VoiceCoreRequest metadata
- Core/planner routing through the same boundary as typed input
- Ghost/Deck-facing status snapshots
- initial spoken-renderer skeleton without real TTS
- tests proving voice cannot bypass Core, trust, or planner

Hard non-scope:
- no real OpenAI network calls
- no real microphone capture
- no wake-word implementation beyond interface/mock
- no TTS playback
- no realtime speech-to-speech
- no direct local actions from voice code
- no cloud audio before wake
- no raw audio persistence
- no UI-owned assistant logic

Acceptance:
- voice is unavailable when OpenAI is disabled or voice is disabled
- voice state is typed and inspectable
- manual transcript input enters the normal Core/planner path
- typed and voice requests share routing behavior except source metadata
- sensitive requests still require existing trust/approval behavior
- UI-facing status can show disabled/unavailable/dormant/listening/thinking/speaking-like states from backend snapshots
- tests cover config gating, state transitions, mock transcript routing, source metadata, and no-bypass constraints

Deliver:
- code changes
- files added/updated
- architecture summary
- tests added
- focused test results
- full regression results or precise explanation if not run
- what was intentionally deferred to Voice-2+
```

## 7. Full Codex Prompt

```text
You are implementing the first Stormhelm Voice System sprint.

Read and follow the attached materials in this priority order:

1. Stormhelm Design Book
   - Governs identity, persona, Ghost Mode, Command Deck, central voice core, and the rule that Stormhelm remains one unified command presence.

2. Stormhelm Layout Spec
   - Governs visible behavior, density, Ghost Mode lightness, Command Deck depth, and voice core UI posture.

3. Stormhelm Voice System — Master Book
   - Governs voice product doctrine, privacy, OpenAI dependency, wake/input/output behavior, confirmations, and anti-goals.

4. Stormhelm Voice System — OpenAI Research and Provider Strategy
   - Provides provider strategy and current OpenAI voice API direction.

5. Stormhelm Voice System — Architecture and Data Contracts
   - Governs typed models, states, events, and integration seams.

6. Stormhelm Voice System — Implementation Roadmap and Codex Prompt
   - This is the direct implementation scope for the current pass.

7. Stormhelm Voice System — Acceptance and Test Book
   - Governs acceptance, test coverage, and rejection conditions.

Current target:
Implement Phase Voice-0 and Voice-1 only.

Phase Voice-0 mission:
Create the voice subsystem foundation: config, availability, typed state, provider interfaces, event taxonomy, mock providers, diagnostics snapshots, and UI/Core-facing status surfaces.

Phase Voice-1 mission:
Add manual transcript-to-Core routing so a mocked voice transcript enters the exact same Core/planner/orchestrator boundary as typed input, while preserving source metadata and existing trust/planner behavior.

Build-now scope:
- voice config models
- OpenAI dependency gating
- voice availability computation
- voice state enum and state transition helpers
- voice events
- provider protocol/interfaces
- mock wake/STT/TTS/playback providers
- manual voice transcript submission endpoint or internal service method
- VoiceCoreRequest source metadata
- Core request integration
- diagnostics snapshot
- UI bridge/status data model additions if the repo has such surfaces
- tests for config gating, state model, mock providers, manual transcript routing, and no-bypass constraints

Explicit non-scope:
- real microphone capture
- real OpenAI transcription
- real OpenAI TTS
- realtime transcription
- local wake-word engine
- speech-to-speech session
- audio playback
- barge-in
- raw audio persistence
- user-facing voice settings UI beyond backend/bridge status stubs
- any direct action execution from voice code

Architecture laws:
- Voice is an input/output surface, not a separate assistant.
- Voice must not bypass Stormhelm Core, planner, trust, task graph, adapters, recovery, or verification.
- Voice code must not directly execute local actions.
- Voice availability must be disabled if OpenAI is disabled or credentials are unavailable.
- No cloud audio before wake may be introduced now or later.
- UI must render backend voice state; UI must not own assistant logic.
- Provider code must stay behind interfaces.
- Mock providers must allow deterministic tests.

Data contracts to implement or prepare:
- VoiceAvailability
- VoiceMode
- VoiceState
- WakeWordEvent
- VoiceTurn
- TranscriptConfidence
- VoiceCoreRequest
- SpokenResponseRequest / SpokenResponse skeleton
- VoiceDiagnosticsSnapshot
- GhostVoiceState or equivalent bridge snapshot

Testing requirements:
- voice disabled when voice.enabled=false
- voice disabled when openai.enabled=false
- missing credentials produce unavailable status, not crash
- mock wake provider emits wake event without cloud audio
- manual transcript submission creates source=voice Core request
- planner receives the transcript text normally
- voice source metadata survives the request path
- sensitive mocked transcript still requires approval according to existing trust rules if trust is available
- voice service cannot directly execute tools/actions
- diagnostics snapshot reports provider/state accurately
- no raw audio persistence flag defaults to false

Completion report must include:
1. What was implemented
2. What files were added/updated
3. What voice states/config/contracts now exist
4. How manual transcript-to-Core routing works
5. How OpenAI gating works
6. What tests were added
7. Focused test results
8. Full regression results or honest reason not run
9. What was intentionally deferred to Voice-2+
10. Any assumptions/caveats

Important:
Build the smallest clean voice foundation that makes later real OpenAI STT/TTS and wake-word work easy. Do not implement impressive demos by violating the architecture.
```

## 8. Follow-Up Prompt for Voice-2 / Voice-3

After Voice-0 and Voice-1 land, use this smaller prompt:

```text
You are implementing Stormhelm Voice-2 and Voice-3 on top of the landed Voice-0/1 foundation.

Voice-2: Add real OpenAI Speech-to-Text for short manual utterance capture.
Voice-3: Add SpokenResponseRenderer + OpenAI TTS output + local playback state.

Preserve all Voice-0/1 architecture. Do not introduce wake word, realtime transcription, or speech-to-speech yet.

Hard rules:
- no cloud audio before wake
- raw audio not persisted by default
- failed STT does not submit guessed commands
- failed TTS leaves visible text and reports failure
- spoken output is generated by Stormhelm's spoken renderer, not raw Core text dumping
- sensitive requests still route through trust/approval

Deliver code, tests, provider config, OpenAI error handling, privacy behavior, and exact deferrals.
```

## 9. Implementation Warnings

Likely traps:

- Accidentally building a second assistant loop inside the voice provider.
- Letting UI submit audio directly to OpenAI instead of Core owning provider config.
- Speaking raw verbose responses instead of voice-rendered summaries.
- Treating “yes” as global permission.
- Persisting raw audio because it is “useful for debugging.” Do not. Debug goblins always say this.
- Mixing wake detection with OpenAI streaming before wake.
- Starting with Realtime speech-to-speech before typed contracts exist.

## 10. Recommended Repo Notes to Add Before Codex

Before sending to Codex, add a short repo note like:

```text
Repo notes:
- Core service/container paths: [path]
- Config models/loader paths: [path]
- Planner/orchestrator entry points: [path]
- Chat/Core request endpoint path: [path]
- Event bus/streaming paths: [path]
- Trust/approval paths: [path]
- Task graph paths: [path]
- UI bridge/status state paths: [path]
- Existing OpenAI provider paths: [path]
- Existing tests path and test command: [command]
```

## 11. Final Roadmap Statement

Do not start voice by chasing the shiniest feature. Start by building the spine. A good voice subsystem is not “audio goes in, vibes come out.” It is wake, state, transcript, Core, trust, response rendering, TTS, playback, and truthful UI state.

The goblin gets a headset only after it learns the chain of command.
