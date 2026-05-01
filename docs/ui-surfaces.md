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
- `assets/qml/variants/stormforge/StormforgeAnchorCore.qml`
- `assets/qml/variants/stormforge/StormforgeAnchorHost.qml`

Stormforge Ghost now uses its own UI-P2S stage structure. Stormforge Deck is still the next large layout surface and should be handled in UI-P3. Future polish should prefer changing Stormforge files or adding Stormforge-only helpers before touching shared `assets/qml/components/*` files. Shared components remain appropriate for backend-state rendering, bridge contract support, and visual behavior intentionally shared by both variants.

State styling lives in `StormforgeTokens.qml` through the `normalizeState`, `stateAccent`, `stateFill`, `stateStroke`, `stateGlow`, and `stateText` helpers. Supported state tones include `idle`, `ready/active`, `wake_detected`, `listening`, `capturing`, `transcribing`, `thinking/routing`, `acting/executing`, `speaking`, `planned`, `running`, `blocked/warning`, `failed/error`, `stale`, `verified`, `unverified`, `approval_required`, `recovery`, `mock/dev`, and `unavailable`.

Known remaining Stormforge polish gaps:

- Ghost uses the UI-P2S Stormforge stage composition and UI-P2A Anchor Core, but still needs deeper UI-P4 motion refinement after screenshot and hardware testing.
- Command Deck still inherits the Classic layout and needs a dedicated Stormforge workspace pass.
- The component set is construction-smoked, not yet rolled through every panel.
- Automated visual screenshot baselines remain future work.

UI-P2S Stormforge Ghost stage structure:

- `assets/qml/variants/stormforge/StormforgeGhostShell.qml` owns the Stormforge Ghost composition. It does not import the Classic Ghost shell and routes anchor placement through `StormforgeAnchorHost.qml`.
- `assets/qml/variants/stormforge/StormforgeGhostStage.qml` defines the centered stage and visual layer order for backdrop, atmosphere, instrumentation, anchor, transcript, cards, approval, actions, and future foreground atmosphere.
- `assets/qml/variants/stormforge/StormforgeGhostBackdrop.qml` provides the subtle non-fog translucent command veil and ring/focus treatment.
- `assets/qml/variants/stormforge/StormforgeAnchorHost.qml` defines the central anchor slot, sizing, alignment, z-order, and compatibility boundary for future Deck reuse.
- `assets/qml/variants/stormforge/StormforgeAnchorCore.qml` renders the UI-P2A living nautical instrument: compass/bearing ring, signal core, waveform/ripple response, restrained state halo, and short state text.
- `assets/qml/variants/stormforge/StormforgeGhostStatusLine.qml` renders compact connection/status/time state.
- `assets/qml/variants/stormforge/StormforgeGhostTranscript.qml` renders only the latest two Ghost messages.
- `assets/qml/variants/stormforge/StormforgeGhostCardStack.qml` owns the low-density context-card region and caps visible cards to two.
- `assets/qml/variants/stormforge/StormforgeGhostContextCard.qml` renders compact secondary context cards.
- `assets/qml/variants/stormforge/StormforgeGhostPermissionPrompt.qml` renders approval/blocked/failed prompts with firmer but still lightweight styling.
- `assets/qml/variants/stormforge/StormforgeGhostActionRegion.qml` wraps `StormforgeActionStrip.qml` for backend-provided Ghost actions without adding frontend command authority.

Stormforge Ghost state mapping remains visual only. QML maps existing bridge values such as `voice_current_phase`, `voice_anchor_state`, `speaking_visual_active`, `active_playback_status`, `primaryCard.resultState`, and card text into Stormforge state tones. It does not create route truth, approval truth, action authority, or completion claims.

UI-P2A Anchor Core:

- Purpose: the Anchor Core is Stormhelm's Stormforge presence center in Ghost Mode. It is not a microphone button and it is not a generic glowing orb. It should read as a calm nautical instrument: compass ring, sonar/signal core, bearing ticks, restrained halo, and voice waveform response.
- Properties: `StormforgeAnchorCore.qml` exposes `state`, `voiceState`, `assistantState`, `label`, `sublabel`, `intensity`, `active`, `disabled`, `warning`, `speakingLevel`, `audioLevel`, `progress`, `pulseStrength`, and `compact`.
- Truth boundary: the Anchor Core only derives visual state from existing QML inputs and `UiBridge.voiceState`. It does not start capture, grant approval, verify completion, execute actions, or create a second bridge model.
- State mapping: empty or unavailable backend state resolves to neutral `idle`/`Ready`; wake/ready resolves to an alignment posture; listening/capturing/transcribing require voice/capture state or explicit caller state; synthesizing/requested playback resolves to `thinking`, not `speaking`; speaking requires `speaking_visual_active` or active playback status; executing/acting maps to `acting`; approval/card trust tone maps to `approval_required`; blocked/warning maps to contained amber; failed/error maps to restrained failure; disabled/muted/interrupted maps to `unavailable`; mock/dev maps to a separate development trace.
- Visual language: cyan and sea-green are the primary signal identity; brass/copper appear only for acting, approval, warning, and failure emphasis; amber means approval or warning tension; red/copper is limited to failure. The component uses Stormforge tokens for color, stroke, glow, and timing.
- Animation rules: idle breathes faintly; wake/ready aligns bearing arcs; listening/capturing uses waveform ticks with audio level when available; thinking/routing uses a slow orbital trace; acting/executing emits directional traces; speaking radiates from real bridge audio/envelope drive when present and labels unavailable audio-reactive source honestly; approval/warning/failure use contained halos rather than frantic motion; unavailable mutes animation.
- Text treatment: the Anchor Core shows only a short primary label and optional secondary source/status line. It never shows transcripts or command claims inside the anchor.
- Integration: `StormforgeGhostShell.qml` places `StormforgeAnchorHost.qml` in the central stage layer. The host owns placement and exposes `resolvedState`, `resolvedLabel`, `motionProfile`, `effectiveSpeakingLevel`, and `finalAnchorImplemented` while delegating drawing to `StormforgeAnchorCore.qml`.

UI-P2A.2 Anchor Core presence pass:

- Purpose: UI-P2A.2 is a Stormforge-only visual presence, depth, and premium-motion pass for `StormforgeAnchorCore.qml`. It keeps the Anchor Core as Stormhelm's living nautical identity center rather than a flat icon, microphone button, loading spinner, or generic glowing orb.
- Visual depth: the anchor now exposes `visualTuningVersion: "UI-P2A.2"`, token-backed depth-layer and nautical-detail markers, a layered inner glass disc, depth rim/shadow, etched ring segments, horizon line, quadrant marks, sonar arcs, calmer compass needles, and a restrained signal core.
- Motion calibration: idle is slower and instrument-like; wake/ready uses aligned bearing arcs; listening uses softer receive-wave motion; thinking/routing uses a slower orbital bearing trace; acting emphasizes a directional bearing line; speaking radiance remains tied to supported speaking/playback state; approval/warning/failure use contained bezel accents; unavailable stops motion; mock/dev stays visibly non-production.
- State distinction: approval uses amber/brass firmness, warning uses amber/copper restraint, failure uses limited danger/copper accents, mock/dev uses violet development traces, and unavailable is desaturated and quiet. These distinctions are visual only and do not create command, approval, verification, or completion truth.
- Token hygiene: P2A.2 anchor depth, glass, horizon, sweep, shadow, timing, and motion-restraint constants live in `StormforgeTokens.qml` so future tuning does not scatter magic colors or timing values through the component.
- Fog boundary: UI-P2A.2 does not implement, tune, diagnose, or configure fog. UI-P2VF owns fog activation/proof. The anchor remains readable without fog and expects any fog layer to stay behind the anchor or around its outer edges without obscuring labels, waveform, state halo, or warning/approval/failure readability.
- Classic preservation: Classic Ghost and Deck files remain separate and must not receive Stormforge Anchor Core visuals.
- Known limitations: the pass uses focused QML construction tests plus offscreen screenshot/manual artifacts. It is not a full visual baseline harness and does not replace later hardware/GPU QA.
- Recommended next QA: after UI-P2VF-2 and Ghost layout settle together, run a combined screenshot/hardware pass for anchor-plus-fog readability, animation cadence, and real-GPU rendering.

UI-P2A.3 Anchor signature pass:

- Purpose: UI-P2A.3 strengthens the Anchor Core as Stormhelm's identity mark. It is still a calm instrument rather than a glowing orb, microphone button, loading spinner, pirate wheel, or generic radar disc.
- Signature silhouette: `StormforgeAnchorCore.qml` now exposes `visualTuningVersion: "UI-P2A.3"` and `signatureSilhouette: "helm_crown_aperture"`. The visual signature combines a subtle top helm-crown marker, asymmetric outer cyan/brass clamp arcs, restrained directional notches, and the existing compass/sonar ring system.
- Center core: the center lens now uses a token-backed signal aperture with a deeper glass gradient, small signal point, aperture crescents, and better separation from the outer rings. It is stronger than UI-P2A.2 but intentionally below glowing-blob intensity.
- State geometry: P2A.3 adds `stateGeometrySignature` so states differ by geometry as well as color. Idle is a closed watch crown; wake/ready aligns the heading crown; listening opens the receive aperture; transcribing uses a segmented processing aperture; thinking keeps internal orbit geometry; acting emphasizes a directional helm trace; speaking uses response aperture radiance only when playback/speaking support exists; approval uses a brass clamp bezel; warning uses an amber boundary clamp; failed uses a diagnostic break segment; mock/dev uses synthetic violet aperture traces; unavailable dims the lens.
- Motion rules: motion remains slow and intentional. Idle breath is a powered-instrument glow, listening/transcribing are receptive or processing without spinner semantics, thinking is internal, acting is directional, speaking is outward response energy, and approval/warning/failure stay contained.
- Truthfulness rules: the anchor still derives from existing QML inputs and `UiBridge.voiceState`; it does not start capture, execute actions, grant approval, verify completion, or create frontend-owned state. Speaking/listening/acting/approval/failure visuals remain tied to their corresponding backend-derived states or explicit caller inputs.
- Fog boundary: UI-P2A.3 does not implement, tune, diagnose, or configure fog. Fog remains UI-P2VF ownership, and the anchor must stay readable without depending on fog visibility.
- Classic preservation: P2A.3 is Stormforge-only. Classic Ghost and Deck files remain the baseline and must not receive Anchor Core visuals.
- Known limitations: P2A.3 uses focused QML tests and offscreen screenshots, not a complete visual baseline or hardware/GPU motion capture harness.

UI-P2A.4 Anchor central aperture and helm lens pass:

- Purpose: UI-P2A.4 focuses on the central 30-40% of `StormforgeAnchorCore.qml` so the anchor reads less like a small dot inside a dial and more like Stormhelm's living compass-heart.
- Central helm lens: the anchor now exposes `centerLensSignature: "living_helm_lens"` and token-backed lens layer, lens radius, aperture segment, pearl, rim, iris, highlight, and shadow values. The center uses a deeper local lens gradient, inner shadow, rim rings, four compass-petal aperture segments, a small signal pearl, and a restrained highlight crescent.
- Signal aperture behavior: `centerStateSignature` describes the center-specific posture. Ready uses a calm helm lens; wake/ready brightens the signal pearl; listening opens the aperture; transcribing adds segmented processing around the center; thinking drifts the inner iris slowly; acting draws a directional center bearing; speaking adds calm radiance only when speaking/playback is supported; approval locks the lens with brass/copper rim accents; warning uses a contained amber boundary; failed shows a small red/copper diagnostic break; mock/dev uses a violet artificial lens; unavailable dims the center nearly off.
- Motion rules: center motion remains small and local. Aperture opening, lens glow, speaking radiance, thinking drift, and warning/failure behavior are bounded Canvas drawing changes, not shader work, progress animation, or frontend-owned state.
- Truthfulness rules: the center follows the same state contract as the rest of the anchor. It does not imply listening, speaking, acting, approval, warning, failure, verification, or completion unless the existing bridge/caller state resolves to that posture.
- Fog boundary: UI-P2A.4 does not implement, tune, diagnose, or configure fog. Fog remains UI-P2VF ownership, and the central lens must stay readable without depending on fog.
- Classic preservation: P2A.4 is Stormforge-only and does not alter Classic Ghost or Deck visuals.
- Known limitations: P2A.4 uses focused QML construction tests plus offscreen screenshot/manual artifacts. It is not a hardware visual baseline or real-GPU motion capture harness.

UI-P2A.4A Anchor idle presence hotfix:

- Purpose: UI-P2A.4A keeps the Stormforge Anchor Core structurally visible in idle, ready, and unknown/no-active-command states. The anchor is Stormhelm's Ghost identity center and must not disappear just because no command is active.
- Root-cause guardrail: earlier anchor drawing used scattered low alpha values for idle/ready without a single exposed visibility floor. In live Ghost composition those quiet values could fall below practical readability, especially around the center lens and bearing ticks.
- Minimum presence rules: `StormforgeAnchorCore.qml` now exposes `minimumRingOpacity`, `minimumCenterLensOpacity`, `minimumBearingTickOpacity`, `minimumSignalPointOpacity`, `minimumLabelOpacity`, `visualPresenceFloor`, and `anchorVisibilityStatus`. Idle, ready, and wake states use `visible_idle_floor`; unavailable uses `visible_unavailable_floor`; active command states keep their state-driven posture.
- State fallback: unknown, null-like, or empty visual state input falls back to neutral idle/ready posture through `normalizedStateFallback: "idle"`. Disabled/offline/unavailable input still maps to the unavailable visual state.
- Visual behavior: idle/ready remain quiet and calm, but the outer ring, bearing ticks, center lens, signal point, and label stay intentionally present. Unavailable remains much dimmer than idle, but not structurally absent. Mock/dev remains distinct through the existing synthetic violet signature.
- Truthfulness: the hotfix does not add backend state, command authority, speaking claims, listening claims, acting claims, or approval claims. It only prevents the neutral anchor from becoming visually blank.
- Fog boundary: UI-P2A.4A does not implement, tune, diagnose, or configure fog. The anchor remains readable without depending on fog or backdrop.
- Classic preservation: UI-P2A.4A is Stormforge-only and does not alter Classic Ghost or Deck visuals.

UI-P2A.5 Anchor motion system and state stability pass:

- Purpose: UI-P2A.5 makes the Stormforge Anchor Core feel alive, stable, and intentional without adding new decorative complexity. The pass focuses on idle motion, canonical state normalization, visual-state dwell, and transition smoothing.
- Idle life rules: idle, ready, and wake states keep the P2A.4A visibility floors and now expose `idleMotionActive`, `idleBreathValue`, `idlePulseMin`, `idlePulseMax`, and `idleBreathDurationMs`. Idle motion is limited to slow core breathing, faint lens pulse, subtle aperture shimmer, and tiny bearing/horizon drift. It must not look like listening, thinking, command progress, or a spinner.
- State normalization rules: `normalizedState` remains the backend-derived truth used for state claims. Empty, null-like, unknown, or unsupported hints fall back to visible idle through `normalizedStateFallback: "idle"`. Aliases such as `signal_acquired`, `ghost_ready`, `routing`, `executing`, `requires_approval`, `warning`, `error`, `disabled`, `mock`, and `dev` normalize to the same canonical visual vocabulary instead of falling into blank or substring-driven paths.
- Transition smoothing rules: `visualState` is the display posture. It follows `normalizedState` immediately for prompt states such as unavailable, failed, blocked, approval required, speaking, listening/capturing, and acting. Non-critical changes use a small token-backed dwell through `stateMinimumDwellMs` and a token-backed ease through `stateTransitionDurationMs`, with `pendingVisualState`, `previousVisualState`, `stateTransitionActive`, `transitionProgress`, and `visualStateChangeSerial` exposed for focused QML tests.
- Truthfulness boundaries: smoothing is visual only. It does not mutate backend state, invent command authority, fake speaking/listening/acting, or hold stale safety states. Speaking radiance still requires speaking/playback support; listening motion still requires listening/capture state; warnings/failures/approval remain prompt.
- Motion tokens: Stormforge tokens now include idle breath duration, state transition duration, minimum visual dwell, idle pulse min/max, idle lens pulse strength, idle aperture shimmer, idle bearing drift, orbital speed, listening ripple speed, speaking radiance speed, warning pulse limit, and unavailable opacity floors.
- Fog boundary: UI-P2A.5 does not implement, tune, diagnose, or configure fog. Anchor motion remains independent of fog and must remain readable with fog disabled or enabled by its owning phase.
- Classic preservation: UI-P2A.5 is Stormforge-only and does not alter Classic Ghost or Deck visuals.
- Known limitations: P2A.5 uses focused QML diagnostics plus offscreen screenshots. It does not provide a full screenshot baseline system or real-GPU/hardware motion capture.

UI-P2M merge seam contract:

- `StormforgeGhostStage.qml` owns Ghost stage layer constants and the inert `stormforgeGhostInstrumentationLayer`; it does not import Anchor Core or fog renderers.
- `StormforgeAnchorHost.qml` owns anchor placement and integration. It exposes `componentRole: "stormforge_anchor_host"`, `ownsAnchorPlacement: true`, and `ownsAnchorAnimation: false`.
- `StormforgeAnchorCore.qml` owns anchor identity, state animation, Canvas drawing, waveform/ripple behavior, labels, and motion profiles.
- `StormforgeGhostShell.qml` wires the Stage, AnchorHost, transcript, cards, approval prompt, action region, and fog host together. It does not instantiate `StormforgeAnchorCore` directly.
- `stormforgeGhostAtmosphereSlot` remains the only Ghost shell fog host. Fog stays behind the Stormforge stage composition and remains absent from Classic.
- `StormforgeGhostCardStack.qml` owns context-card density limits, and `StormforgeGhostActionRegion.qml` owns the compact Ghost action-strip placement without adding frontend command authority.

Z-layer model:

- Base translucent stage/backdrop: `StormforgeGhostBackdrop.qml`.
- Back atmosphere host: `stormforgeGhostAtmosphereSlot` in `StormforgeGhostShell.qml`.
- Low-noise instrumentation: `stormforgeGhostInstrumentationLayer` in `StormforgeGhostStage.qml`.
- Anchor slot: `StormforgeAnchorHost.qml` with `StormforgeAnchorCore.qml` visually dominant above the back atmosphere.
- Transcript/status surfaces: `StormforgeGhostStatusLine.qml` and `StormforgeGhostTranscript.qml`.
- Context cards: `StormforgeGhostCardStack.qml`.
- Approval/action surfaces: `StormforgeGhostPermissionPrompt.qml` and `StormforgeGhostActionRegion.qml`.
- Future foreground atmosphere belongs to UI-P2VF, not UI-P2S.

Fog boundary:

- UI-P2VF owns volumetric fog, shader fog, fallback behavior, quality modes, config, and visual tuning. UI-P2S preserves the host slot and stacking order only.
- UI-P2A expects fog to sit behind the Anchor Core. Foreground wisps may only pass as a restrained outer-edge atmosphere; fog must not obscure the Anchor Core label, state halo, waveform, or approval/warning/failure readability.
- UI-P2VF-1 tunes the isolated Stormforge Ghost volumetric-fog path from feasibility prototype toward production-readiness. It is not wired into Classic, and it is not wired into Command Deck.
- `StormforgeGhostShell.qml` owns `stormforgeGhostAtmosphereSlot` with `fogImplemented: true`. The slot sits after the backdrop and before instrumentation, anchor, transcript, cards, approval, and actions.
- `StormforgeVolumetricFogLayer.qml` uses `assets/qml/shaders/stormforge_volumetric_fog.frag.qsb`, an animated ShaderEffect with bounded pseudo-raymarch sample counts, smoothed 3D-noise accumulation, low rolling drift, lower-screen bias, edge weighting, central/card/anchor clearing, token-tinted near/far color, and soft alpha.
- Readability behavior is local and visual only. The shader receives a central protected region, an anchor-safe region, center-clear strength, card-clear strength, and a separate foreground-wisp opacity cap so transcript, approval, blocked, failed, and action surfaces stay legible.
- Config default: `[ui.stormforge.fog] enabled = false`, `mode = "volumetric"`, `quality = "medium"`, `intensity = 0.35`, `motion = true`, `edge_fog = true`, `foreground_wisps = true`, `max_foreground_opacity = 0.08`, `center_clear_strength = 0.65`, `lower_bias = 0.45`, `drift_speed = 0.055`, `drift_direction = "right_to_left"`, `flow_scale = 1.0`, `crosswind_wobble = 0.18`, `rolling_speed = 0.035`, `wisp_stretch = 1.8`, `card_clear_strength = 0.72`, `anchor_clear_radius = 0.18`, `debug_visible = false`, `debug_intensity_multiplier = 3.0`, and `debug_tint = true`.
- Environment override: `STORMHELM_STORMFORGE_FOG=1` enables the fog for Stormforge Ghost testing. `STORMHELM_STORMFORGE_FOG_DEBUG_VISIBLE=true` enables the deliberately obvious diagnostic overlay. Invalid mode, quality, intensity, and tuning values normalize safely back to bounded defaults.
- Quality modes: `off` disables work, `low` uses 8 samples, `medium` uses 14 samples, and `high` uses 24 samples. The shader clamps at 28 samples and does not create particles.
- Fallback behavior: `StormforgeFogFallbackLayer.qml` exists only for explicit `mode = "fallback"` testing. It is intentionally not treated as volumetric production fog and is disabled by default; automatic shader-failure detection is still not implemented.
- Diagnostics: `StormforgeVolumetricFogLayer.qml` exposes QML-only state such as `fogEnabledRequested`, `fogActive`, `fogVisible`, `shaderEnabled`, `fallbackEnabled`, `effectiveOpacity`, `layerWidth`, `layerHeight`, `zLayer`, `renderMode`, `maskStrengths`, and `disabledReason`. These are visual diagnostics only and do not create route, trust, or command authority.
- Proof path: `scripts/run_stormforge_fog_visual_probe.py` renders `ghost_fog_off.png`, `ghost_fog_on.png`, `ghost_fog_on_t0.png`, `ghost_fog_on_t1.png`, `ghost_fog_debug_visible.png`, `fog_diff.png`, `fog_motion_diff.png`, and `fog_debug_diff.png` while reporting mean pixel difference, significant pixel count, whether normal ShaderEffect pixels were captured, and a fog-field horizontal motion estimate. `fog_diff.png` is the normal fog-off versus fog-on proof; `fog_motion_diff.png` is the enabled t0/t1 movement proof; `fog_debug_diff.png` is only the deliberately obvious debug overlay proof. Offscreen captures may still miss ShaderEffect pixels, so desktop/OpenGL capture is the visual truth path for shader tuning.
- UI-P2VF-3 visual tuning: normal fog is intentionally more visible than the activation prototype through shader density shaping, stronger lower/edge accumulation, whispier foreground noise, and bounded alpha. The central protected region, anchor clear region, card clear strength, and foreground opacity cap remain active so the transcript, approval prompt, action region, and Anchor Core stay readable.
- UI-P2VF-4 motion tuning: the shader separates bulk flow from internal rolling. The main density field advects right-to-left using `drift_direction`, `drift_speed`, and `flow_scale`; subtle crosswind wobble and `rolling_speed` deform the field internally; `wisp_stretch` elongates the density domain into horizontal/diagonal wisps instead of stationary blobs. The QML diagnostics expose these values through `motionControls`.
- Performance/readability warning: fog animation stops when disabled, no fog runs for Classic, and foreground wisps must stay subtle. Debug-visible mode is intentionally stronger and must not be treated as final styling. UI-P2VF-3 is visually viable in desktop/OpenGL capture, but the fog should remain default-off until broader hardware/GPU QA confirms the cinematic balance across renderer backends.

Next phase boundaries:

- UI-P3 should polish Stormforge Command Deck structure and panels.
- UI-P4 should handle broader motion/animation polish after Ghost and Deck composition are stable.
- UI-P2VF should keep fog default-off until production screenshot coverage and real-GPU tuning confirm the effect across renderer backends.
- UI-P2A follow-up should tune Anchor Core screenshots and future Deck reuse only after the Ghost placement and fog stack are visually verified together.
- Classic baseline files remain preserved and should not be visually rewritten.

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
- Source files: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/ghost_input.py`, `src/stormhelm/ui/ghost_adaptive.py`, `assets/qml/components/VariantGhostShell.qml`, `assets/qml/variants/classic/ClassicGhostShell.qml`, `assets/qml/variants/stormforge/StormforgeGhostShell.qml`, `assets/qml/variants/stormforge/StormforgeAnchorHost.qml`, `assets/qml/variants/stormforge/StormforgeAnchorCore.qml`, `assets/qml/components/SignalStrip.qml`, `assets/qml/components/CommandSurfaceCard.qml`
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
- Source files: `assets/qml/components/VoiceCore.qml`, `assets/qml/variants/stormforge/StormforgeAnchorCore.qml`, `assets/qml/components/GhostShell.qml`, `assets/qml/components/CommandDeckShell.qml`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/controllers/main_controller.py`, `src/stormhelm/ui/voice_surface.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py`
- Tests: `tests/test_qml_shell.py`, `tests/test_ui_bridge.py`, `tests/test_voice_bridge_controls.py`, `tests/test_voice_ui_state_payload.py`, `tests/test_voice_capture_service.py`
- Status note: Implemented but limited in the current worktree. Voice is disabled by default, and wake word, always-listening, VAD, Realtime, full interruption, and direct provider-owned command execution remain unavailable.
