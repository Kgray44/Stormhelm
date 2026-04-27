# Stormhelm Phase 2B Memory and Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a practical active-work context layer with clipboard and selection intelligence, then wire it into the current planner and execution path without destabilizing the existing Phase 1 and Phase 2A foundations.

**Architecture:** Add a bounded `core.context` subsystem that stores active-work state, classifies clipboard and selection snapshots, and resolves deictic references before the planner chooses deterministic execution. Extend the existing UI-to-core message payload path rather than building a separate channel.

**Tech Stack:** Python 3.12, PySide6, FastAPI, SQLite-backed preferences, pytest

---

### Task 1: Context Models and Service

**Files:**
- Create: `src/stormhelm/core/context/models.py`
- Create: `src/stormhelm/core/context/service.py`
- Create: `src/stormhelm/core/context/resolver.py`
- Create: `src/stormhelm/core/context/__init__.py`
- Update: `src/stormhelm/core/orchestrator/session_state.py`
- Create: `tests/test_context_service.py`

- [ ] Define structured models for active-work memory, clipboard snapshots, selection snapshots, and context resolution results.
- [ ] Extend `ConversationStateStore` with active-context persistence and bounded recent-resolution storage.
- [ ] Implement an `ActiveContextService` that merges workspace posture, recent tool results, focused window info, and current input context.
- [ ] Add tests for classification, recency ordering, bounded storage, and safe update rules.

### Task 2: UI Input Context Capture

**Files:**
- Update: `src/stormhelm/ui/bridge.py`
- Update: `src/stormhelm/ui/controllers/main_controller.py`
- Update: `src/stormhelm/ui/client.py`
- Update: `src/stormhelm/core/api/schemas.py`
- Update: `src/stormhelm/core/api/app.py`
- Create: `tests/test_main_controller.py`
- Update: `tests/test_ui_bridge.py`

- [ ] Add a structured `input_context` payload alongside the existing `workspace_context`.
- [ ] Capture current clipboard content in the UI at send time and classify it enough for downstream use.
- [ ] Capture current selection from Stormhelm-owned surfaces at send time when available.
- [ ] Add tests that confirm the controller ships clipboard and selection context through the API path.

### Task 3: Assistant and Provider Integration

**Files:**
- Update: `src/stormhelm/core/orchestrator/assistant.py`
- Update: `src/stormhelm/core/container.py`
- Update: `src/stormhelm/core/tools/base.py`
- Update: `tests/test_assistant_orchestrator.py`

- [ ] Inject the active-context service into the container and tool context.
- [ ] Update the assistant orchestrator to receive `input_context`, update active context, and pass it into planning.
- [ ] Include resolved active context in reasoner payloads for transform-style commands.
- [ ] Add tests for context update behavior, provider payload shaping, and recent-context restore flows.

### Task 4: Planner Routing and Deictic Resolution

**Files:**
- Update: `src/stormhelm/core/orchestrator/planner.py`
- Update: `tests/test_planner.py`

- [ ] Add explicit routing for clipboard, selection, and active-context commands.
- [ ] Use structured source-priority resolution for `this`, `that`, `it`, `what I copied`, `what I selected`, and `continue that`.
- [ ] Keep deterministic routing intact for direct actions and only escalate transforms after explicit source resolution.
- [ ] Add red-green coverage for clipboard open, selection summarize, task extraction, and recent-context continuation.

### Task 5: Context-backed Builtin Actions

**Files:**
- Create: `src/stormhelm/core/tools/builtins/context_actions.py`
- Update: `src/stormhelm/core/tools/builtins/__init__.py`
- Update: `src/stormhelm/core/workspace/service.py`
- Update: `tests/test_tool_registry.py`

- [ ] Add builtin context tools for inspecting active context, opening resolved clipboard targets, saving resolved content to Logbook, adding resolved content to workspace, and extracting tasks from resolved text.
- [ ] Reuse the existing notes and workspace services instead of building a second storage path.
- [ ] Add tests for tool registration and supported context actions.

### Task 6: Verification and Fit with Existing Surfaces

**Files:**
- Update: any touched files as required by prior tasks

- [ ] Run focused tests for the new context service, planner routing, assistant orchestration, UI bridge, controller, and tool registry.
- [ ] Run a broader regression slice to confirm the existing Phase 1A/1B/1C and recent UI work remain intact.
- [ ] Summarize supported commands, limits, and the recommended Phase 2C follow-up based on what actually landed.
