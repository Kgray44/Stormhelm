# Stormhelm Phase 2B Memory and Context Design

## Goal

Add a practical active-work context layer to Stormhelm so it can resolve follow-up references, use clipboard and selection inputs intelligently, and continue ongoing work without forcing the operator to restate everything on every turn.

This phase should make Stormhelm:

- aware of recent work instead of relying on raw chat replay
- capable of using clipboard contents as a typed input surface
- capable of using Stormhelm-owned selections as a typed input surface
- better at resolving `this`, `that`, `it`, `what I copied`, and `what I selected`
- more natural at `continue`, `resume`, and `what was I just doing` flows

## Scope

This pass includes:

- a structured short-horizon active-work memory model
- explicit clipboard snapshot capture and classification
- explicit selection snapshot capture and classification for Stormhelm-owned surfaces
- deterministic context resolution that feeds the existing planner and tool stack
- context-aware follow-up routing for deictic references and active-work commands
- context-aware task extraction, workspace saves, and Logbook saves where already supported
- bounded recency and decay so stale context does not dominate indefinitely
- debugging visibility for context updates and resolution choices

This pass explicitly excludes:

- Ghost redesign
- Deck redesign
- orchestrator replacement
- a giant permanent personal-memory system
- broad clipboard-history product work
- universal OS-wide arbitrary selected-text capture from every app
- later-phase judgment / situational-mode systems

## Decision

Implement Phase 2B as a deterministic context layer that sits between the user's phrasing and Stormhelm's existing execution stack.

The planner should remain authoritative for routing. The new context layer should improve target and source resolution before execution rather than replacing deterministic routing with prompt-only improvisation.

## Architectural Overview

Phase 2B adds four new concepts:

- **ActiveContextService**
  - stores and updates short-horizon active-work memory
  - synthesizes workspace posture, recent tool results, recent actions, and current UI input context

- **ClipboardSnapshot / Clipboard classifier**
  - captures the current clipboard payload at send time
  - classifies it into typed, actionable content

- **SelectionSnapshot / Selection classifier**
  - captures active selection from Stormhelm-owned surfaces at send time
  - classifies it into typed, actionable content

- **ContextResolver**
  - resolves follow-up references like `this`, `that`, `what I copied`, and `continue that`
  - returns a structured result with source, confidence, and normalized payload

These concepts plug into:

- the UI bridge and main controller for snapshot capture
- the `/chat/send` API payload
- the assistant orchestrator for context updates and provider payload shaping
- the deterministic planner for routing decisions
- the existing workspace and notes services for context-backed actions

## Active Context Model

Active-work memory should be represented explicitly rather than inferred from raw transcript text alone.

Suggested fields:

- `active_goal`
- `workspace`
- `workspace_topic`
- `focused_app`
- `focused_window`
- `active_entities`
- `recent_entities`
- `last_action`
- `last_action_result`
- `recent_search_results`
- `recent_workflow_chain`
- `current_problem_domain`
- `pending_next_steps`
- `recent_target_resolutions`
- `clipboard`
- `selection`
- `updated_at`

Design rules:

- update context after successful, meaningful actions
- do not aggressively update context from failed or ambiguous actions
- treat workspace posture as a strong context source when active
- keep recent entities bounded and recency-ordered
- allow stale entries to decay rather than sticking forever

## Context Sources and Priority

When Stormhelm needs to resolve `this`, `that`, `it`, or similar follow-up phrasing, it should use a structured priority order:

1. active explicit selection
2. current clipboard when explicitly referenced or clearly implied
3. focused Stormhelm item or focused system window
4. active workspace posture
5. recent successful target resolution
6. recent search result or recent active entity
7. clarification when ambiguity still matters

Resolution should remain conservative:

- use strong evidence when acting directly
- allow light assumptions when low-risk and confidence is high
- clarify when ambiguity materially affects execution

## Clipboard Intelligence

Clipboard capture should happen at message-send time in the UI layer and travel to the core as structured input context.

Clipboard classification should distinguish at least:

- plain text
- code
- URL
- single file path
- multiple file paths
- image reference or image-available flag where cheap to detect
- unknown text payload

The clipboard layer should expose:

- raw text when safely available
- normalized type
- normalized value or parsed list
- short preview
- metadata such as line count, character count, or path count where useful

This pass should prioritize the current clipboard, not a full history product.

## Selection-Aware Actions

Selection support in this phase should focus on Stormhelm-owned surfaces and other low-risk, already-accessible UI context.

Selection classification should distinguish at least:

- plain text
- code
- URL
- file path
- selected item reference
- unknown

High-value commands enabled by selection:

- summarize this
- explain this
- rewrite this
- rewrite this shorter
- turn this into notes
- turn this into tasks
- save this to Logbook
- add this to the workspace
- search this
- open related docs for this

If there is no usable selection, Stormhelm should fail briefly and honestly instead of pretending it found one.

## Planner Integration

The planner remains deterministic-first and should use the context layer before execution.

Expected flow:

1. normalize phrasing
2. apply understanding/alias shortcuts from Phase 2A
3. inspect explicit clipboard / selection references
4. consult active context for deictic resolution
5. decide whether the request is:
   - direct context action
   - contextual transform
   - contextual search/action
   - contextual resume/restore
6. choose deterministic execution or concise clarification

Examples:

- `open what I copied` with a clipboard URL -> direct open action
- `open what I copied` with a file path -> direct file open action
- `summarize this` with an active selection -> reasoner-backed transform with explicit source
- `turn this into tasks` with selected text -> deterministic task extraction from the resolved source
- `continue where I left off` -> workspace/context restore flow

## Deterministic vs Reasoner-backed Work

Some context-enabled actions should stay deterministic:

- inspect current context
- open clipboard URL
- open clipboard file path
- add resolved content to workspace
- save resolved content to Logbook
- extract tasks from resolved text
- restore recent context

Some actions can remain reasoner-backed as long as source resolution is deterministic and explicit:

- summarize this
- explain this
- rewrite this
- rewrite this shorter

The key rule is that the context source must be explicitly resolved before a transform request reaches the language model.

## Memory Update Rules

Update active context when:

- a workspace is opened, restored, assembled, or switched
- a file, page, or item is opened successfully
- a search result is selected or opened
- a workflow or repair flow starts or completes meaningfully
- a clipboard/selection action succeeds
- a context inspection command returns meaningful context

Avoid or limit updates when:

- the action failed
- the resolution was weak or ambiguous
- the context source was malformed or unavailable
- the user clearly pivoted away to a different topic

## UI and API Changes

The UI already sends `workspace_context` with each message. Extend that path with a new `input_context` payload that includes:

- `clipboard`
- `selection`
- optional focused Stormhelm surface metadata if helpful

The core API should accept this payload, hand it to the assistant orchestrator, and let the active-context service merge it with workspace posture and recent action state.

This avoids building a parallel IPC channel for clipboard and selection.

## Capability and Failure Behavior

Stormhelm should explicitly report limits such as:

- clipboard access unavailable
- no active selection
- clipboard type unsupported for requested action
- not enough recent context
- context too stale to reuse safely

Failure behavior must stay concise and factual:

- `No active selection.`
- `Clipboard access isn't available here.`
- `The clipboard doesn't contain a usable file path.`
- `I don't have enough recent context for that.`

## Observability

Phase 2B should add debug-friendly visibility for:

- active context contents
- context updates
- clipboard and selection classification
- chosen resolution source
- resolution confidence and fallback path
- capability checks
- stale-context rejection

This makes context quality tunable instead of opaque.
