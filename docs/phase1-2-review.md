# Stormhelm Phase 1.2 Architecture Review

## Brutally Honest Findings

### 1. Runtime path ownership was too implicit

Phase 1 blurred together:

- source-tree root
- packaged install directory
- PyInstaller resource bundle directory
- user data directory

That worked in local development, but it was the biggest packaging risk in the whole repo. UI assets, config loading, and core launch behavior all depended on source-layout assumptions.

### 2. IPC was functional but too chatty and too thin

Local HTTP is still a reasonable Phase 1 choice, but the UI was polling many separate endpoints every cycle and had very little runtime/protocol metadata. That creates unnecessary traffic, fragile startup logic, and poor version mismatch visibility.

### 3. Job concurrency looked bounded without actually being bounded

The queue worker count was capped, but synchronous tools still ran via `asyncio.to_thread()`, which uses the event loop's default thread pool. That meant the effective sync execution boundary was less explicit than the architecture claimed.

### 4. Job lifecycle state would become a scalability problem

Finished jobs and completion futures were retained indefinitely. Queue submission also blocked when full instead of failing clearly. That is survivable in a tiny MVP and exactly the sort of issue that becomes painful once real automation or high-frequency tools arrive.

### 5. Safety was conceptually right but operationally thin

The read-only/action split was present, but the policy layer did not yet give rich operational detail. File safety was mostly enforced in the tool, not surfaced as part of a broader runtime contract.

### 6. Packaging readiness was mostly placeholders

The folder structure was right, but the PyInstaller specs, release scripts, and Inno Setup scaffolding were not yet honest enough to support a real release workflow.

### 7. Versioning had drift risk

The project version lived in multiple places. That is a classic release-readiness problem because installers, UI labels, API health, and package metadata eventually stop matching.

### 8. Logging and first-run behavior were too soft

The core logged, but the UI did not establish its own process log or exception hook. There was also no explicit runtime state file or first-run marker, which made packaged startup less inspectable than it should be for a background-first assistant.

## Improvements Implemented In Phase 1.2

### Runtime and packaging

- Added explicit runtime discovery in `src/stormhelm/shared/runtime.py`.
- Split install root, resource root, source root, user config path, state path, and bundled assets/config paths in config.
- Updated config loading so bundled defaults, portable overrides, and user overrides can coexist cleanly.

### Version and release identity

- Promoted `src/stormhelm/version.py` to the single source of truth for application version and protocol version.
- Switched `pyproject.toml` to dynamic version loading from the Python package.
- Added version display in the UI and richer version/runtime metadata in core status and health responses.

### Startup and IPC

- Improved the UI bootstrap path so it launches the sibling packaged core executable when frozen.
- Added a `/snapshot` endpoint to reduce fragmented polling and provide a more coherent UI bootstrap surface.
- Added runtime state files for first-run and current core process metadata.

### Concurrency and jobs

- Replaced implicit sync execution with an explicit bounded `ThreadPoolExecutor`.
- Added queue-full failure behavior instead of silent backpressure.
- Added finished-job pruning and future cleanup to avoid indefinite in-memory growth.

### Logging and observability

- Added process-specific log paths for core and UI.
- Added shared exception logging hooks.
- Added first-run/runtime metadata files for better diagnostics.

### Developer ergonomics and release workflow

- Updated dev scripts to prefer the workspace virtual environment and `PYTHONPATH=src`.
- Replaced placeholder portable packaging script with a real release assembly workflow.
- Upgraded the Inno Setup scaffold to consume portable build output with version parameters.

## Remaining Architectural Risks

### 1. HTTP polling is still polling

The `/snapshot` endpoint is cleaner than many small polls, but it is still polling. Phase 2 should move log/job/status updates toward streaming or push-style delivery.

### 2. Tool execution still lacks dependency graphs and priorities

The bounded job model is now more honest, but it is still a flat queue. Future automation will want:

- prioritization
- job dependencies
- richer cancellation semantics
- durable resumability for long-running tasks

### 3. Safety policy will need richer approval states

Phase 1.2 preserves strict defaults, but future action tools will need per-tool approval strategies, audit reasons, and possibly explicit user approvals flowing through the UI.

### 4. Portable build verification still needs an unsandboxed pass

The build scripts and specs are now real, but PyInstaller resource mutation is blocked in this shell environment. A normal Windows terminal should be used for final binary verification.
