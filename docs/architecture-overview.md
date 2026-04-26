# Stormhelm Architecture Overview

## Core Principle

Stormhelm is intentionally split into a long-lived background core and a separate desktop shell. The assistant engine is the product's center of gravity. The UI is a client, not the system itself.

## Major Runtime Pieces

### 1. Background Core Service

Responsibilities:

- own orchestration and sessions
- own tool registration and execution
- enforce safety policy
- persist history, notes, preferences, and tool runs
- publish debug events and logs
- expose a stable local API that other clients can use later

The core is implemented as a local FastAPI service bound to localhost. In Phase 1, the UI polls endpoints for state updates. The service boundary keeps the assistant available even if the UI closes.

### 2. Desktop Control UI

Responsibilities:

- present the chat shell and operational dashboard
- display assistant state and recent job activity
- display logs and notes
- manage tray-friendly user experience
- launch or reconnect to the background core

The UI is built with PySide6 and avoids putting orchestration logic inside widgets. Controllers coordinate API calls and map results into focused UI panels.

## Layered Source Structure

### `stormhelm/config`

- typed configuration models
- config loading from TOML and environment variables
- path resolution for app data, database, and logs

### `stormhelm/shared`

- shared enums and result types
- path helpers
- timestamp helpers

### `stormhelm/core`

Subpackages:

- `api`: local HTTP interface for the UI and future clients
- `jobs`: bounded concurrent job manager
- `memory`: SQLite database and repositories
- `orchestrator`: session-aware assistant layer and text routing
- `safety`: tool gating and allowlist checks
- `tools`: registry, execution engine, and builtin tools

### `stormhelm/ui`

- PySide6 application bootstrap
- network client to talk to the local core
- reusable widgets
- a controller that coordinates polling and user actions
- tray integration

## IPC Choice

Phase 1 uses localhost HTTP instead of named pipes. That choice is deliberate:

- easier to inspect and debug during development
- straightforward for PyInstaller packaging
- cleanly separates core and UI concerns
- easy to extend with WebSocket or SSE later without rewiring the core
- future automation, remote control, or companion clients can reuse the same API

The transport can change later without rewriting the assistant logic because orchestration, jobs, storage, and tools all live behind the core service boundary.

## Concurrency Model

The core uses an `asyncio` job manager with:

- bounded queue
- fixed worker pool sized for at least 8 concurrent jobs
- per-job state tracking
- timeout handling
- cancellation hooks
- per-job logging and history persistence

Sync tools are wrapped safely from the async job system so the architecture can support both async and blocking work without turning the orchestrator into a tangle of special cases.

## Storage Strategy

SQLite stores:

- conversation sessions and messages
- notes
- preferences
- tool execution history

Logs are written to files under the user data directory and mirrored into an in-memory event buffer for the UI debug panel.

This keeps user state local-first and gives a clear seam for future semantic retrieval layers or embeddings tables without replacing the storage foundation.

## Safety Model

Stormhelm assumes unsafe capability growth over time, so the safety layer starts early:

- tools declare metadata and safety classification
- action tools are distinct from read-only tools
- file reads are allowlist-only
- shell execution is disabled by default
- the safety policy is centralized and extendable

## Packaging Posture

The codebase is structured around two entrypoints:

- `stormhelm-core`
- `stormhelm-ui`

That makes Phase 1 packaging-friendly for:

- portable developer bundles
- separate background and UI executables
- future installer logic that can register shortcuts, startup behavior, and tray-first launches

