# Stormhelm Phase 1 Design

## Goal

Build a modular, production-minded Phase 1 foundation for Stormhelm: a serious local-first Windows desktop assistant built around a background core service and a separate PySide6 control shell.

## Scope

This phase includes:

- background core service
- PySide6 desktop shell
- local HTTP IPC
- SQLite persistence
- safe builtin tools
- bounded concurrent job execution
- logs and debug visibility
- packaging-ready project layout

This phase explicitly excludes:

- voice input or TTS
- unrestricted shell automation
- browser automation
- always-on computer control

## Recommended Approach

### Option A: Localhost API with separate UI client

Pros:

- best separation of concerns
- easy to debug
- future friendly for additional clients and services
- easy to package as dual executables

Cons:

- slightly more infrastructure than a single-process app

### Option B: In-process UI with background threads

Pros:

- fewer moving parts at first

Cons:

- violates the service-first direction
- harder to keep the assistant alive when UI closes
- makes future startup/tray/service behavior messier

### Option C: Windows named pipes from day one

Pros:

- Windows-native IPC

Cons:

- more complexity early
- less transparent for debugging
- not necessary for Phase 1

## Decision

Choose Option A. The product direction clearly benefits from a service boundary now rather than retrofitting one later.

## System Design

### Background Core

The core is the long-lived assistant engine. It owns:

- orchestration
- job scheduling
- tool execution
- safety policy
- persistence
- logs and internal events

The core exposes a localhost API for:

- health and status
- chat requests
- recent conversation history
- recent jobs
- recent events
- notes
- settings summary

### UI

The UI is a PySide6 shell with:

- chat panel
- core status card
- tool activity table
- debug log panel
- notes panel
- settings summary panel
- tray-ready close behavior

The UI never directly owns assistant logic. It talks to the core and renders state.

### Concurrency

The job manager uses:

- bounded queue
- fixed worker pool sized to 8 by default
- per-job timeout
- cancellation hooks
- isolated failure handling
- persisted execution history

That keeps the architecture ready for future prioritization and dependency chaining without prematurely implementing a full DAG scheduler.

### Safety

Builtin tools must declare:

- name
- description
- execution mode
- safety classification
- validation rules

The safety policy checks:

- whether a tool is enabled
- whether an action tool is allowed
- whether a file path is inside allowed directories

### Storage

SQLite holds:

- sessions
- messages
- notes
- tool runs
- preferences

Log files are stored separately under the runtime data directory.

## Testing

Phase 1 should ship with tests covering:

- config loading
- SQLite repository basics
- tool registration and execution
- safety allowlist behavior
- job manager submission and completion

## Voice Integration Notes

Future voice components should plug into the core as adapters:

- audio input provider
- wake-word provider
- speech-to-text provider
- text-to-speech provider

The orchestrator should accept text requests from either the UI chat box or voice-transcribed input without knowing which source produced the text.

## Packaging Notes

Stormhelm should package as two executables later, with install files separate from user data. PyInstaller is the recommended first bundler and Inno Setup is the recommended installer layer.

