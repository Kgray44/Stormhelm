# Stormhelm Voice System — Acceptance and Test Book

## 1. Purpose

This document defines how Stormhelm's Voice and Speaking Pipeline is judged. It is the anti-nonsense book: if the implementation cannot pass these expectations, it is not done, no matter how cool the waveform looks.

Voice is dangerous because it feels magical. Therefore the tests must be boring, explicit, typed, and mean. The goblin may sing, but it will be audited.

## 2. Universal Acceptance Principles

Voice is acceptable only if it preserves these laws:

1. Voice does not bypass Stormhelm Core.
2. Voice does not bypass planner routing.
3. Voice does not bypass trust/approvals.
4. Voice does not execute local actions directly.
5. Voice is disabled if OpenAI is disabled.
6. No cloud audio is sent before wake.
7. Raw audio is not persisted by default.
8. Spoken output is persona-shaped, not raw text dumping.
9. Sensitive actions require bound confirmation.
10. Failure states are truthful.
11. UI renders backend state; UI does not own voice logic.
12. Voice behavior remains Stormhelm, not generic assistant theater.

## 3. Acceptance Categories

### 3.1 Config and Availability

Pass conditions:

- `voice.enabled=false` disables voice.
- `openai.enabled=false` disables voice.
- missing API key disables OpenAI voice provider without crashing.
- unavailable input/output device produces degraded/unavailable status.
- provider status is visible in diagnostics.
- voice cannot enter listening/capture state when unavailable.

Fail conditions:

- Voice appears ready when OpenAI is disabled.
- Voice tries network calls without credentials.
- UI says “ready” while backend says unavailable.
- Voice silently falls back to an unconfigured provider.

### 3.2 Wake and Privacy

Pass conditions:

- wake detection is local or mocked locally.
- no cloud audio before wake.
- wake event moves state toward Ghost Mode/listening.
- wake timeout returns to Dormant.
- mute disables capture.
- listening indicator is visible when capture is active.

Fail conditions:

- OpenAI receives audio while Dormant.
- wake events are not inspectable.
- capture continues after mute.
- Stormhelm appears to listen without indicator.

### 3.3 Transcription / Speech Input

Pass conditions:

- recognized transcript is attached to a `VoiceTurn`.
- low-confidence transcript is marked honestly.
- failed transcription does not submit a guessed command.
- transcript enters Core through the same boundary as typed input.
- source metadata survives: `source=voice`, turn ID, confidence.

Fail conditions:

- voice provider calls tools directly.
- transcript is silently rewritten beyond normalization.
- low-confidence sensitive command proceeds without clarification/approval.
- failed transcription sends a random best guess into Core. This is not innovation; this is chaos with a microphone.

### 3.4 Core Routing

Pass conditions:

- voice transcript routes through planner/orchestrator.
- typed and voice requests have equivalent routing when text is equivalent.
- voice source metadata is preserved for audit.
- voice requests can start tasks using the same task graph path.
- voice requests can be rejected/clarified by planner normally.

Fail conditions:

- voice route bypasses planner.
- voice uses a separate ad hoc router.
- voice lowers trust requirements.
- voice response claims a route/tool/action that did not occur.

### 3.5 Spoken Response Rendering

Pass conditions:

- simple actions speak concise confirmations.
- detailed answers are summarized for speech.
- Deck/Ghost text preserves details while speech stays short.
- persona is calm, precise, restrained, Stormhelm-like.
- uncertainty is spoken honestly.
- errors are spoken calmly with next state/action if applicable.

Fail conditions:

- Stormhelm reads long tables/code/logs aloud by default.
- Stormhelm speaks generic assistant fluff.
- Stormhelm says “done” when only planned/attempted.
- Stormhelm over-apologizes or uses pirate parody.

### 3.6 TTS and Playback

Pass conditions:

- OpenAI TTS request uses configured model/voice.
- playback state is tracked.
- streaming playback begins when available.
- stop/interruption halts playback.
- TTS failure leaves visible text response.
- playback failure is reported truthfully.

Fail conditions:

- backend marks speech complete before playback succeeds.
- TTS error swallows the response.
- playback blocks the Core event loop.
- output continues after user says stop.

### 3.7 Trust-Aware Confirmations

Pass conditions:

- sensitive actions require existing trust approval.
- spoken confirmation is bound to approval/task/action/target.
- stale confirmation is rejected.
- low-confidence confirmation is rejected for sensitive actions.
- consumed confirmation cannot be reused.
- audit records include voice source.

Fail conditions:

- “yes” confirms an old task.
- “yes” confirms the wrong route family.
- “sure” from a low-confidence transcript deletes or sends something.
- spoken confirmation bypasses approval subsystem.

### 3.8 Barge-In / Interruption

Pass conditions:

- “stop” stops speech playback.
- “cancel” cancels pending not-yet-executed request where supported.
- “sleep” returns to Dormant.
- “mute” disables configured voice path.
- “actually...” begins correction flow.
- already-executed actions are not falsely undone.

Fail conditions:

- interruption is ignored.
- “stop” cancels an action unexpectedly.
- “cancel” claims to undo completed work.
- new speech corrupts active approval state.

### 3.9 UI / Ghost / Deck Surface

Pass conditions:

Ghost Mode:

- shows central voice state;
- shows listening/speaking/thinking compactly;
- shows short transcript/current response;
- shows confirmation card when needed;
- remains low-density.

Command Deck:

- shows voice diagnostics;
- shows transcript/event timeline;
- shows provider status;
- shows confirmation state;
- shows task/source metadata.

Fail conditions:

- Ghost Mode becomes a voice dashboard.
- UI owns voice logic.
- visual state contradicts backend state.
- provider debug details are dumped into Ghost Mode by default.

### 3.10 Persona Consistency

Pass conditions:

Stormhelm voice copy should be:

- concise;
- direct;
- composed;
- slightly mythic;
- restrained nautical/instrumentation vocabulary;
- never fake pirate;
- never chirpy.

Sample pass:

```text
Bearing acquired.
Opening Downloads.
The core is not responding. I’m attempting to reconnect.
I found two likely matches. I need one more bearing before acting.
```

Sample fail:

```text
Hey there! What can I do for you today?
Ahoy matey, I be installing yer software!
Oopsie! Something went wrong lol.
Great news!!! I think maybe it worked!
```

## 4. Required Test Families

## Family A — Config Gating

Test cases:

- voice disabled by config;
- OpenAI disabled;
- OpenAI key missing;
- input device missing;
- TTS disabled but typed output still works;
- voice provider unavailable.

Assertions:

- correct availability reason;
- no capture/provider calls;
- UI status truthful.

## Family B — State Machine

Test cases:

- disabled -> unavailable;
- dormant -> wake_detected -> listening;
- listening -> capturing -> transcribing -> thinking -> speaking;
- timeout returns to Dormant;
- error returns to Dormant/unavailable;
- mute blocks capture.

Assertions:

- legal transitions only;
- emitted events match transitions;
- invalid transitions rejected or ignored safely.

## Family C — Mock Transcript Routing

Test cases:

- “open downloads” routes like typed input;
- “what time is it” routes like typed input;
- “install Minecraft” routes to software/trust path if present;
- “send this to Baby” routes to relay/deictic path if present;
- ambiguous transcript triggers clarification.

Assertions:

- source=voice;
- route family expected;
- no direct tool execution from voice layer;
- trust/approval preserved.

## Family D — Transcription Failure

Test cases:

- provider timeout;
- empty audio;
- noise-only audio;
- low-confidence transcript;
- provider returns error;
- transcript alternatives conflict.

Assertions:

- no guessed command submitted;
- UI shows retry/clarification;
- event log includes failure reason;
- privacy flags remain correct.

## Family E — Spoken Renderer

Test cases:

- simple success;
- planned but not executed;
- blocked by policy;
- failed action;
- requires confirmation;
- long technical response;
- uncertainty;
- no speech requested.

Assertions:

- spoken text length appropriate;
- no overclaim;
- persona rules pass;
- detailed data remains visual.

## Family F — OpenAI TTS Provider

Test cases:

- normal TTS success;
- streaming begins;
- model unavailable;
- voice unavailable;
- network failure;
- playback error;
- stop during playback.

Assertions:

- playback state truthful;
- errors surfaced;
- visible text remains;
- Core not blocked.

## Family G — Spoken Confirmation

Test cases:

- current approval, high-confidence yes;
- stale approval yes;
- wrong task yes;
- low-confidence yes;
- “no” rejects/cancels approval;
- confirmation consumed once;
- confirmation after route changed.

Assertions:

- only valid current approval accepted;
- audit source=voice;
- no cross-task leakage.

## Family H — Wake Privacy

Test cases:

- manual wake;
- mock local wake;
- wake timeout;
- wake while muted;
- wake disabled;
- cloud-before-wake assertion.

Assertions:

- no OpenAI audio call before wake;
- wake event visible;
- Dormant remains quiet.

## Family I — Realtime Transcription / VAD

For later phases.

Test cases:

- `speech_started` event;
- `speech_stopped` event;
- transcript deltas;
- final transcript;
- server VAD timeout;
- semantic VAD enabled;
- reconnect after disconnect.

Assertions:

- final transcript submitted once;
- partial transcript shown but not acted on;
- event ordering handled.

## Family J — Barge-In

For later phases.

Test cases:

- user says stop during TTS;
- user says cancel before action;
- user says sleep after wake;
- user says actually/correction;
- user interrupts confirmation prompt.

Assertions:

- playback stops;
- task state truthful;
- confirmation state not corrupted.

## Family K — UI Surface

Test cases:

- voice disabled state in UI;
- Dormant status;
- Listening status;
- Thinking status;
- Speaking status;
- confirmation card;
- TTS failure text fallback;
- Deck diagnostics panel.

Assertions:

- UI state comes from backend;
- Ghost remains low-density;
- Deck shows deeper state.

## Family L — Persona Regression

Test cases:

- wake response;
- quick action;
- warning;
- uncertainty;
- failure;
- workspace escalation;
- confirmation prompt.

Assertions:

- no banned phrases;
- no fake pirate dialect;
- no chirpy exclamation spam;
- concise by default.

## 5. Scenario Matrix

| Scenario | Expected Behavior |
|---|---|
| “Stormhelm.” | Wake, short acknowledgement, listening. |
| Wake then silence | Timeout to Dormant. |
| “Open Downloads.” | Submit transcript to Core, execute/plan existing route, speak concise confirmation. |
| “What is this?” | Submit to Core; screen-awareness resolves context if available; do not invent visual context. |
| “Install Minecraft.” | Route to software control; require trust confirmation before mutation. |
| “Yes.” after current approval | Confirm only if fresh, bound, confident. |
| “Yes.” after timeout | Reject stale confirmation. |
| TTS provider fails | Show text, report speech failure. |
| STT low confidence on destructive command | Ask clarification, do not execute. |
| “Stop.” while speaking | Stop playback only. |
| “Cancel.” before execution | Cancel pending request if possible, report truthfully. |
| OpenAI disabled | Voice unavailable; typed Core may remain. |

## 6. Metrics

Track:

- wake-to-listening latency;
- utterance end-to-transcript latency;
- transcript-to-Core submission latency;
- Core response latency;
- TTS first-audio latency;
- playback completion;
- STT failure rate;
- low-confidence rate;
- TTS failure rate;
- false confirmation rejection count;
- barge-in success latency;
- false success / overclaim count.

## 7. Truthfulness Tests

Voice must distinguish:

- heard vs not heard;
- transcribed vs guessed;
- planned vs attempted;
- attempted vs completed;
- completed vs verified;
- spoken vs displayed;
- stopped speaking vs cancelled action;
- wake detected vs consent granted.

Failure phrases to reject in tests unless evidence supports them:

- `That worked.`
- `Done.`
- `Installed.`
- `Sent.`
- `Deleted.`
- `Fixed.`
- `I verified it.`

Preferred truthfulness phrases:

- `I heard the request.`
- `I have the transcript.`
- `I can prepare that.`
- `Confirmation is required.`
- `I started the request.`
- `The output is visible, but I cannot verify completion yet.`
- `The speech output failed; the response is still visible.`

## 8. Privacy Tests

Required assertions:

- raw audio is not stored by default;
- no cloud request before wake;
- debug audio requires config flag;
- debug audio has retention limit;
- transcript logging follows existing message policy;
- sensitive transcripts are not dumped into debug logs by accident;
- voice diagnostics does not expose secrets.

## 9. Security Tests

Required assertions:

- OpenAI API key is never logged;
- authorization headers are never logged;
- voice cannot call tool executor directly;
- confirmation cannot cross task/action/target;
- malicious transcript like “ignore approvals” has no effect;
- wake word is not treated as approval.

## 10. Performance / Responsiveness Tests

Initial loose targets:

- manual transcript routing mock: under 200 ms excluding Core work;
- availability snapshot: under 50 ms;
- state/event dispatch: under 50 ms;
- TTS failure fallback visible immediately after failure;
- stop playback reaction: under 250 ms after command recognized, ideally faster.

OpenAI-dependent latency targets should be measured but not made brittle early because network/model latency varies.

## 11. Acceptance by Phase

### Voice-0 / Voice-1 Done When

- config exists;
- availability exists;
- state machine exists;
- providers are mocked;
- manual transcript enters Core;
- source metadata preserved;
- tests pass;
- no real audio/OpenAI required.

### Voice-2 Done When

- OpenAI STT provider works;
- transcript failure handled;
- raw audio privacy enforced;
- manual short capture works;
- no guessed commands.

### Voice-3 Done When

- spoken renderer works;
- TTS provider works;
- playback state works;
- failure fallback works;
- persona tests pass.

### Voice-4 Done When

- spoken confirmation is bound;
- stale/cross-task confirmations fail;
- audit source records voice;
- trust is not weakened.

### Voice-5 Done When

- local wake provider works or mock/real provider seam exists;
- no cloud before wake proven;
- wake moves to Ghost Mode;
- timeout/mute works.

### Voice-6 Done When

- Realtime transcription works;
- VAD events map to state;
- transcript deltas visible;
- final transcript submitted once.

### Voice-7 Done When

- stop/cancel/sleep/mute interruption works;
- no false undo claims;
- playback interruption reliable.

### Voice-8 Done When

- diagnostics panel/snapshot exists;
- voice test corpus exists;
- latency/confidence metrics exist;
- regression suite covers major failure modes.

### Voice-9 Done When

- Realtime speech-to-speech mode still submits actions through Core;
- no provider-owned local actions;
- trust/approval preserved;
- persona remains consistent.

## 12. Rejection Conditions

Reject implementation if any of these are true:

- OpenAI disabled but voice appears enabled.
- Voice provider directly executes tools/actions.
- UI owns voice command interpretation.
- Raw audio is persisted by default.
- Cloud audio is sent before wake.
- Sensitive spoken command executes without approval.
- “Yes” can confirm a stale/wrong approval.
- TTS failure hides the response.
- Voice speaks generic assistant or pirate-parody language.
- Tests are mostly skipped or only manual.
- Realtime is implemented before foundational contracts.

## 13. Required Completion Report

Every Codex voice pass must report:

1. Phase implemented.
2. Files added/changed.
3. Voice state/config/contracts added.
4. Provider behavior added.
5. Core integration path.
6. Privacy posture.
7. Trust/approval behavior.
8. UI/bridge state behavior.
9. Tests added/updated.
10. Focused test results.
11. Full regression results or precise reason not run.
12. Known limitations.
13. Explicit deferred work.
14. Any assumptions.

## 14. Final Acceptance Statement

Stormhelm Voice is acceptable when it is calm, useful, truthful, private by default, OpenAI-backed only after configuration allows it, and fully subordinate to Stormhelm Core.

A voice feature that sounds impressive but bypasses the command spine is not a feature. It is a mutiny with good diction.
