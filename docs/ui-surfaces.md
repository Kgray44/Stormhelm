# UI Surfaces

Stormhelm's UI is a PySide6/QML shell. It presents backend-owned state from `UiBridge` and sends actions back through `CoreApiClient` or local controller methods. UI presentation must not become backend authority.

Sources: `src/stormhelm/ui/app.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/controllers/main_controller.py`, `assets/qml/Main.qml`
Tests: `tests/test_ui_bridge.py`, `tests/test_main_controller.py`, `tests/test_qml_shell.py`

## Authority Rule

| Surface | May own | Must not own |
|---|---|---|
| QML components | Layout, visual state, local interaction signals. | Route truth, safety decisions, success claims. |
| `UiBridge` | QML property shaping, local UI state, action dispatch to client/controller. | Core execution authority. |
| `CoreApiClient` | HTTP/SSE transport and parsing. | Business logic or safety policy. |
| Core services | Routing, trust, execution, persistence, verification. | QML layout decisions. |

Sources: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/core/container.py`, `src/stormhelm/core/safety/policy.py`
Tests: `tests/test_ui_bridge_authority_contracts.py`, `tests/test_ui_client_streaming.py`

## Visual Variants

Stormhelm UI-P0.5 preserves the current Ghost Mode and Command Deck appearance as the `classic` visual variant and adds a separate `stormforge` lane for future polish. Both variants consume the same `UiBridge` properties and emit the same local QML signals; there is no second backend path, bridge model, planner route, or command-routing contract.

Current shell entry points:

- `assets/qml/Main.qml` is the QML application shell.
- `assets/qml/components/VariantGhostShell.qml` selects the Ghost visual variant.
- `assets/qml/components/VariantCommandDeckShell.qml` selects the Command Deck visual variant.

Classic baseline files:

- `assets/qml/variants/classic/ClassicGhostShell.qml`
- `assets/qml/variants/classic/ClassicCommandDeckShell.qml`

Stormforge files safe for future visual polish:

- `assets/qml/variants/stormforge/StormforgeGhostShell.qml`
- `assets/qml/variants/stormforge/StormforgeCommandDeckShell.qml`

Stormforge UI-P1 foundation files:

- `assets/qml/variants/stormforge/StormforgeTokens.qml` holds Stormforge color, opacity, spacing, typography, radius, elevation, animation, z-layer, and state-style constants.
- `assets/qml/variants/stormforge/StormforgeGlassPanel.qml`
- `assets/qml/variants/stormforge/StormforgeCard.qml`
- `assets/qml/variants/stormforge/StormforgeButton.qml`
- `assets/qml/variants/stormforge/StormforgeIconButton.qml`
- `assets/qml/variants/stormforge/StormforgeStatusChip.qml`
- `assets/qml/variants/stormforge/StormforgeResultBadge.qml`
- `assets/qml/variants/stormforge/StormforgeSectionHeader.qml`
- `assets/qml/variants/stormforge/StormforgeEmptyState.qml`
- `assets/qml/variants/stormforge/StormforgeLoadingState.qml`
- `assets/qml/variants/stormforge/StormforgeErrorState.qml`
- `assets/qml/variants/stormforge/StormforgeDivider.qml`
- `assets/qml/variants/stormforge/StormforgeRail.qml`
- `assets/qml/variants/stormforge/StormforgeListRow.qml`
- `assets/qml/variants/stormforge/StormforgeMetricLabel.qml`
- `assets/qml/variants/stormforge/StormforgeActionStrip.qml`

Stormforge currently wraps the preserved Classic Ghost and Deck shells and adds only small foundation markers to prove the token/component layer loads. Future UI-P2/UI-P3 polish should prefer changing Stormforge files or adding Stormforge-only helpers before touching shared `assets/qml/components/*` files. Shared components remain appropriate for backend-state rendering, bridge contract support, and visual behavior intentionally shared by both variants.

State styling lives in `StormforgeTokens.qml` through the `normalizeState`, `stateAccent`, `stateFill`, `stateStroke`, `stateGlow`, and `stateText` helpers. Supported state tones include `idle`, `active`, `listening`, `thinking`, `acting`, `speaking`, `planned`, `running`, `blocked`, `failed`, `stale`, `verified`, `unverified`, `approval_required`, `recovery`, `mock/dev`, and `unavailable`.

Known remaining Stormforge polish gaps:

- Ghost still inherits the Classic layout and needs a dedicated Stormforge composition pass.
- Command Deck still inherits the Classic layout and needs a dedicated Stormforge workspace pass.
- The component set is construction-smoked, not yet rolled through every panel.
- Automated visual screenshot baselines remain future work.

Switching:

- Default: `config/default.toml` has `[ui] visual_variant = "classic"`.
- Config override: set `[ui] visual_variant = "stormforge"` in the active user or portable config.
- Environment override: set `STORMHELM_UI_VARIANT=stormforge` before launching `scripts/run_ui.ps1`.
- Invalid values fall back to `classic` and log a warning from `stormhelm.config.loader`.

## Ghost Mode

- What it shows: Quick command strip, Ghost messages, primary command card, action strip, corner readouts, adaptive placement/style, brief status labels.
- What state feeds it: `UiBridge.mode`, `ghostMessages`, `ghostPrimaryCard`, `ghostActionStrip`, `ghostCornerReadouts`, `ghostAdaptiveStyle`, `ghostPlacement`, `ghostCaptureActive`, chat/stream/status payloads.
- What actions it exposes: Begin/cancel capture, draft editing, submit message, local surface actions, mode toggle.
- What it must not own: Route decisions, trust approvals, action success, persisted state.
- Source files: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/ghost_input.py`, `src/stormhelm/ui/ghost_adaptive.py`, `assets/qml/components/VariantGhostShell.qml`, `assets/qml/variants/classic/ClassicGhostShell.qml`, `assets/qml/variants/stormforge/StormforgeGhostShell.qml`, `assets/qml/components/SignalStrip.qml`, `assets/qml/components/CommandSurfaceCard.qml`
- Tests: `tests/test_ghost_input.py`, `tests/test_ghost_adaptive.py`, `tests/test_ui_bridge.py`, `tests/test_qml_shell.py`

## Command Deck

- What it shows: Command spine, command rail, prompt composer, workspace canvas, opened item strip, route inspector, transcript, panels, status strips, browser/file/network surfaces.
- What state feeds it: `deckModules`, `activeDeckModule`, `deckSupportModules`, `deckPanels`, `hiddenDeckPanels`, `deckPanelCatalog`, `workspaceSections`, `workspaceCanvas`, `openedItems`, `routeInspector`, `requestComposer`, `statusStripItems`.
- What actions it exposes: Send prompt, switch module/section, activate/close opened items, save notes, pin/collapse/hide/restore panels, save/reset/auto-arrange deck layout, perform local surface actions.
- What it must not own: Backend truth, route scoring, adapter execution, destructive action permission.
- Source files: `assets/qml/components/VariantCommandDeckShell.qml`, `assets/qml/variants/classic/ClassicCommandDeckShell.qml`, `assets/qml/variants/stormforge/StormforgeCommandDeckShell.qml`, `assets/qml/components/CommandSpine.qml`, `assets/qml/components/CommandRail.qml`, `assets/qml/components/DeckPanelWorkspace.qml`, `assets/qml/components/WorkspaceCanvas.qml`, `src/stormhelm/ui/bridge.py`
- Tests: `tests/test_main_controller.py`, `tests/test_main_controller_batch2_contracts.py`, `tests/test_ui_bridge_batch2_contracts.py`, `tests/test_qml_shell.py`

## Bridge Surfaces

- What it shows: The bridge is not directly visible; it supplies properties to every QML surface.
- What state feeds it: Health, status, snapshot, chat, event stream, settings, local UI interactions, Ghost adaptive manager.
- What actions it exposes: `sendMessage`, `saveNote`, `setMode`, `activateModule`, `performLocalSurfaceAction`, workspace/deck layout methods, tray/window methods, selection/clipboard context methods.
- What it must not own: Tool execution, provider calls, final verification, approval grants.
- Source files: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`
- Tests: `tests/test_ui_bridge.py`, `tests/test_ui_bridge_batch3_contracts.py`, `tests/test_bridge_authority.py`

## Command Surface Cards

- What it shows: Result state, route labels, chips, provenance, trace, support info, invalidations, actions, memory/runtime/continuity summaries.
- What state feeds it: Route state, trust state, active request state, latest status snapshot, task status, command surface context.
- What actions it exposes: Reveal/continue/approve/deny style command actions as text or local actions.
- What it must not own: The actual approval decision or action execution.
- Source files: `src/stormhelm/ui/command_surface_v2.py`, `assets/qml/components/CommandSurfaceCard.qml`, `assets/qml/components/CommandStationPanel.qml`, `assets/qml/components/CommandActionStrip.qml`
- Tests: `tests/test_command_surface.py`, `tests/test_ui_bridge_software_contracts.py`

## Route Inspector

- What it shows: Route family, stage/result state, route confidence, selected route/winner, trace/provenance/support entries, invalidations.
- What state feeds it: `UiBridge.routeInspector` built from core response metadata and command surface model.
- What actions it exposes: UI inspection only; actions are routed through bridge command surface controls.
- What it must not own: Planner scoring or route correction.
- Source files: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/command_surface_v2.py`, `assets/qml/components/RouteInspectorSurface.qml`
- Tests: `tests/test_ui_bridge.py`, `tests/test_command_surface.py`

## Browser Surfaces

- What it shows: Browser/opened web content or fallback external-open state.
- What state feeds it: Opened item models and `embeddedBrowserPreviewEnabled`.
- What actions it exposes: Activate/close item, local surface actions, external/browser target opens through controller.
- What it must not own: URL resolution, safety/trust decisions, route family choice.
- Source files: `assets/qml/components/BrowserSurface.qml`, `assets/qml/components/BrowserSurfaceEmbedded.qml`, `src/stormhelm/ui/controllers/main_controller.py`, `src/stormhelm/core/orchestrator/browser_destinations.py`, `src/stormhelm/core/tools/builtins/workspace_actions.py`
- Tests: `tests/test_browser_destination_resolution.py`, `tests/test_main_controller.py`, `tests/test_qml_shell.py`

## File Viewer Surfaces

- What it shows: Text/markdown/image/PDF opened item previews where supported.
- What state feeds it: Opened item models from bridge/workspace actions.
- What actions it exposes: Activate/close item, save note from content where available.
- What it must not own: File read allowlists or external file-open safety decisions.
- Source files: `assets/qml/components/FileViewerSurface.qml`, `src/stormhelm/core/tools/builtins/workspace_actions.py`, `src/stormhelm/core/tools/builtins/file_reader.py`, `src/stormhelm/core/safety/policy.py`
- Tests: `tests/test_safety.py`, `tests/test_qml_shell.py`

## Workspace Rail And Canvas

- What it shows: Workspace modules, sections, active workspace canvas, opened items, saved/active workspace hints.
- What state feeds it: `workspaceRailItems`, `workspaceSections`, `workspaceCanvas`, `openedItems`, workspace service/tool state.
- What actions it exposes: Activate sections/items, close items, route workspace commands.
- What it must not own: Durable task truth or persisted workspace writes.
- Source files: `assets/qml/components/WorkspaceRail.qml`, `assets/qml/components/WorkspaceCanvas.qml`, `assets/qml/components/OpenedItemsStrip.qml`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/core/workspace/service.py`
- Tests: `tests/test_workspace_service.py`, `tests/test_ui_bridge.py`

## Approval Prompts

- What it shows: Pending approval/blocked/needed state and suggested actions inside command surface/route cards.
- What state feeds it: Trust decision state from core response metadata and `TrustService.attach_request_state`.
- What actions it exposes: Approval/deny utterance or command action that returns to the backend.
- What it must not own: Grant creation, scope selection truth, audit record creation.
- Source files: `src/stormhelm/core/trust/service.py`, `src/stormhelm/ui/command_surface_v2.py`, `src/stormhelm/ui/bridge.py`
- Tests: `tests/test_trust_service.py`, `tests/test_ui_bridge_software_contracts.py`

## Recovery Surfaces

- What it shows: Software recovery summaries, unresolved/uncertain result state, route switch candidates, verification gaps.
- What state feeds it: Software recovery response metadata, software control traces, command surface support/invalidations.
- What actions it exposes: Follow-up requests or route-switch continuation through backend.
- What it must not own: Retry execution or final recovery success claims.
- Source files: `src/stormhelm/core/software_recovery/service.py`, `src/stormhelm/core/software_control/service.py`, `src/stormhelm/ui/command_surface_v2.py`
- Tests: `tests/test_software_recovery.py`, `tests/test_ui_bridge_software_contracts.py`

## Debug / Watch Views

- What it shows: Systems/watch/status state, event stream state, network/telemetry/lifecycle snapshots, route traces, jobs.
- What state feeds it: `/status`, `/snapshot`, `/events/stream`, operational awareness, network monitor, hardware telemetry, lifecycle status.
- What actions it exposes: Mostly inspection; lifecycle controls route through API/client.
- What it must not own: Health truth, stream replay cursor truth, lifecycle mutation decisions.
- Source files: `src/stormhelm/core/container.py`, `src/stormhelm/core/events.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/bridge.py`, `assets/qml/components/NetworkHealthSurface.qml`, `assets/qml/components/TopStatusStrip.qml`
- Tests: `tests/test_operational_awareness.py`, `tests/test_network_monitor.py`, `tests/test_ui_client_streaming.py`, `tests/test_ui_bridge_batch3_contracts.py`

## Tray And Window Behavior

- What it shows: Tray presence and window show/hide behavior.
- What state feeds it: UI config, bridge hide-to-tray state, lifecycle shell presence.
- What actions it exposes: Hide/show window, backend shutdown request, shell detached reporting.
- What it must not own: Core lifecycle truth or startup registration truth.
- Source files: `src/stormhelm/ui/tray.py`, `src/stormhelm/ui/main_window.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/controllers/main_controller.py`
- Tests: `tests/test_ui_tray.py`, `tests/test_main_controller_lifecycle.py`

## Voice Surfaces

- What it shows: Compact voice availability, capture/listening/thinking/speaking/warning state, provider/capture truth flags, last transcription/Core/TTS/playback summaries, and a Command Deck voice capture station when the bridge has voice state.
- What state feeds it: `/status` voice diagnostics, voice action responses from `/voice/*`, `UiBridge.voiceState`, `voiceCoreState`, `voiceAvailabilityLabel`, `voiceSummary`, and the command-station payload built from backend status.
- What actions it exposes: Start push-to-talk capture, stop capture, cancel capture, submit captured audio, run capture-and-submit, and stop playback. These actions route through `UiBridge`, `CoreApiClient`, `MainController`, and the FastAPI voice endpoints.
- What it must not own: Wake word, microphone permission policy, STT/TTS provider calls, playback truth, command execution, trust decisions, or claims that audio was heard. UI state is presentation only; `VoiceService` owns runtime truth.
- Source files: `assets/qml/components/VoiceCore.qml`, `assets/qml/components/GhostShell.qml`, `assets/qml/components/CommandDeckShell.qml`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/controllers/main_controller.py`, `src/stormhelm/ui/voice_surface.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py`
- Tests: `tests/test_qml_shell.py`, `tests/test_ui_bridge.py`, `tests/test_voice_bridge_controls.py`, `tests/test_voice_ui_state_payload.py`, `tests/test_voice_capture_service.py`
- Status note: Implemented but limited in the current worktree. Voice is disabled by default, and wake word, always-listening, VAD, Realtime, full interruption, and direct provider-owned command execution remain unavailable.
