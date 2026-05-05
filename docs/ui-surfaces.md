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
- `assets/qml/variants/stormforge/StormforgeAnchorFrame.qml`
- `assets/qml/variants/stormforge/StormforgeAnchorDynamicCore.qml`
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

Voice-AR3 Stormforge Anchor renderer split:

- Purpose: AR3 repairs the production Canvas paint bottleneck without changing the PCM meter, voice playback, Ghost layout, Classic, fog visuals, or planner/Core routing. `StormforgeAnchorCore.qml` now orchestrates a cached static frame layer plus a high-frequency dynamic voice layer.
- Static ownership: `StormforgeAnchorFrame.qml` owns the static/rarely changing nautical instrument work: glass disc, outer rings, bearing ticks, quadrant marks, sonar/horizon detail, compass needles, helm crown, and static clamps. It repaints on size/theme/state changes, not every voice-energy frame.
- Dynamic ownership: `StormforgeAnchorDynamicCore.qml` owns the high-frequency visual path: organic blob deformation, blob expansion, speaking radiance, audio glow, shimmer/glint motion, rotating ring fragments, waveform/state signatures, and response arcs. The local/shared animation clock requests this layer during speaking.
- Audio fidelity diagnostics: production QML diagnostics expose scalar-only `voice_visual_energy`, `qmlReceivedVoiceVisualEnergy`, `finalSpeakingEnergy`, `blobScaleDrive`, `blobDeformationDrive`, `blobRadiusScale`, `radianceDrive`, `ringDrive`, `visualAmplitudeCompressionRatio`, and `visualAmplitudeLatencyMs`. Raw PCM/audio is still not exposed to QML or reports.
- Performance boundary: high-rate scalar updates should only update the latest voice-visual target and dynamic layer. They must not rebuild Ghost surfaces, transcript/cards, Classic surfaces, or full voice-state objects at 30-60 Hz.
- Visual quality rule: the split is not a flattening pass. The organic blob remains the primary audio-reactive element, shimmer remains animated, ring fragments remain slow/dynamic, and state signatures remain visually distinct.

Voice-AR3-R / AR4 renderer fallback:

- Default renderer: `legacy_blob_reference`. `STORMHELM_STORMFORGE_ANCHOR_RENDERER=legacy_blob` remains a compatibility alias for the same approved full Canvas organic blob visual behavior while keeping the AR0 scalar PCM meter, lightweight bridge hot path, speaking start/release fixes, and scalar-only diagnostics.
- AR4 parity candidate: `legacy_blob_fast_candidate`. It is selectable for side-by-side parity and performance review, but it is not the live default until the approved legacy blob look is manually accepted.
- AR5 parity candidate: `legacy_blob_qsg_candidate`. It is a scene-graph/Shape clone of the approved legacy center aperture plus the cached static frame path. It is for opt-in performance and visual-parity review only; visible differences from `legacy_blob_reference` are renderer bugs, not design changes.
- Experimental renderer: `ar3_split`. `STORMHELM_STORMFORGE_ANCHOR_RENDERER=ar3_split` keeps the AR3 static-frame/dynamic-core renderer available for future performance experiments, but it is not the live default because its visual result was rejected.
- Visual priority: AR3-R intentionally accepts the old Canvas paint bottleneck again to restore the approved organic blob look. AR5 candidates must preserve the legacy blob appearance and audio-reactive blob deformation before being promoted back to default.
- Sync proof: the real environment probe measures audible PCM wall-time energy against meter, bridge, QML, `finalSpeakingEnergy`, blob drives, and paint timing. `perceptual_sync_status` may be `aligned`, `visual_late`, `visual_early`, or `inconclusive`. AR4 uses direct audible-PCM-to-visual best lag only when correlation is strong enough; otherwise it reports a stage-latency basis such as `pcm_to_paint_estimated`.

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

UI-P2A.5R Anchor organic motion restoration and speaking stability fix:

- Purpose: UI-P2A.5R restores slow organic life to the Stormforge Anchor Core and removes the obvious uniform idle scale pulse. The center remains a helm lens/signal aperture, but its idle motion now reads as a living instrument surface rather than a bouncing button.
- No-trampoline rule: idle/ready/wake expose `idleUniformScalePulseDisabled: true` and `idleUniformScaleAmplitude: 0.0`. Idle no longer drives the outer dial or central lens through a short 1-2 second uniform scale loop.
- Organic idle motion: `organicMotionVersion: "UI-P2A.5R"` uses token-backed primary, secondary, and drift cycles (`idlePrimaryCycleMs`, `idleSecondaryCycleMs`, `idleDriftCycleMs`) to create small asymmetric lens deformation, slow glow variation, aperture shimmer, and tiny internal drift. This motion is visual presence only; it does not imply listening, thinking, command progress, or capture.
- Ring fragments: the anchor exposes `ringFragmentsActive`, `ringFragmentCount`, `ringFragmentMinCycleMs`, and `ringFragmentMaxCycleMs`. Four quiet cyan/line/brass-tinted arc fragments drift independently around the mid/outer instrument rings with 18-45 second periods so the dial has current without becoming a spinner.
- Speaking stability: speaking radiance now uses `rawSpeakingLevel`, `speakingEnvelopeSmoothed`, `outerMotionSmoothed`, `speakingPhase`, `visualSpeakingActive`, and a short token-backed `speakingGraceMs`. Playback/speaking support is still required, but the visual envelope eases in/out and tolerates brief backend flicker without restarting the animation or snapping to idle.
- State transition stability: repeated same-state updates should not reset `visualStateChangeSerial` or the speaking phase. Unknown, empty, and null-like states still fall back to visible idle; unavailable stays dim but structurally rendered; approval, warning, failure, and unavailable remain prompt.
- Truthfulness boundaries: UI-P2A.5R does not add backend state, voice pipeline logic, command authority, capture authority, approval truth, or fake speaking. The short speaking grace is visual smoothing only and decays quickly when playback support ends.
- Fog boundary: UI-P2A.5R does not implement, tune, diagnose, or configure fog. Anchor motion and readability remain independent of fog.
- Classic preservation: UI-P2A.5R is Stormforge-only and does not alter Classic Ghost or Deck visuals.
- Known limitations: offscreen screenshots can prove construction, geometry, and frame-to-frame differences, but they are not a full hardware motion-capture baseline. A combined Ghost QA pass should still review idle and speaking cadence on the live renderer.

UI-P2A.6 Anchor organic blob hybrid architecture:

- Purpose: UI-P2A.6 is a directional correction for `StormforgeAnchorCore.qml`. The prior helm-lens center was clean but too static and dial-like in live Ghost use, so the center returns to an organic blob-style living core while retaining the useful Stormforge nautical instrument frame.
- Recovered model: the pass adapts the older `VoiceCore.qml` center-blob idea: a Canvas-drawn organic core, continuous animation time, soft glow, audio-envelope response, and restrained rotating ring arcs. It does not copy Classic visuals into Stormforge and does not replace the Stormforge outer bearing/tick/crown language.
- Hybrid architecture: `anchorMotionArchitecture: "organic_blob_hybrid"` marks the new center/frame split. The blob is the visual heart; outer rings, bearing ticks, sonar arcs, compass cross, helm crown, and state accents frame it without becoming the main motion.
- Blob motion rules: `blobCoreEnabled`, `blobPointCount`, `organicBlobMotionActive`, `blobPrimaryCycleMs`, `blobSecondaryCycleMs`, and `blobDriftCycleMs` expose the test-only shape contract. The blob uses non-uniform radial deformation and slow independent phases instead of a uniform center scale pulse. Idle motion should be visible when watched, but it must not imply listening, thinking, speaking, command progress, or capture.
- Removed bad motion: `uniformScalePulseDisabled: true` and `idleUniformScalePulseDisabled: true` remain the rule. No 1-2 second center bounce, no phase reset on repeated state updates, and no raw unsmoothed speaking radiance should drive the center.
- Ring fragment rules: subtle arc fragments remain active through `ringFragmentsActive`, `ringFragmentCount`, and ring-fragment cycle diagnostics. Fragments drift at different slow speeds and may pick up state tint, but they must not rotate in sync or become a loading indicator.
- Speaking stability: speaking visuals use a continuous `speakingPhase`, low-pass `speakingEnvelopeSmoothed`, `outerMotionSmoothed`, and `speakingStateFlapGuardEnabled`. A short truthful grace window keeps playback flicker from snapping the anchor to idle, then the envelope decays instead of claiming long fake speech.
- State stability: empty, null-like, and unknown state still fall back to visible idle; unavailable remains dim but structurally rendered; mock/dev stays distinct; approval, warning, failed, and unavailable remain prompt. Center signatures now describe blob postures such as `calm_organic_core`, `radiant_voice_blob`, and `diagnostic_blob_break`.
- Truthfulness boundaries: UI-P2A.6 remains visual only. Speaking still requires backend-derived speaking/playback support; listening/capturing/acting/approval/warning/failure states still require their existing state inputs. No backend/Core/planner/bridge contract changed, and the anchor does not create command authority.
- Fog boundary: UI-P2A.6 does not implement, tune, diagnose, or configure fog. Fog remains UI-P2VF ownership and must not obscure the blob center, state halo, labels, or warning/approval/failure readability.
- Classic preservation: UI-P2A.6 is Stormforge-only and does not alter Classic Ghost or Deck visuals.
- Known limitations: offscreen still cannot prove live cadence perfectly. Use the generated blob frame probes and a live Ghost renderer pass to judge whether the organic center feels alive without becoming too bright or busy.

UI-P2A.6.1 Organic core motion sweet spot:

- Purpose: UI-P2A.6.1 keeps the successful organic blob hybrid architecture and makes the center motion slightly easier to notice. It is an amplitude tuning pass, not a redesign.
- Deformation tuning: `blobMotionSweetSpotVersion: "UI-P2A.6.1"` and `organicMotionAmplitudeVersion: "UI-P2A.6.1"` expose the bounded tuning marker. Idle blob deformation, base blob deformation, glow variation, aperture shimmer, and tiny center drift increase modestly while the primary/secondary/drift cycle timing stays slow.
- No-uniform-scale rule: `uniformScalePulseDisabled` and `idleUniformScalePulseDisabled` remain true, and `idleUniformScaleAmplitude` remains `0.0`. The blob should reshape asymmetrically, not bounce as one circle.
- Speaking stability: P2A.6.1 does not shorten speaking timing or reset speaking phase. `speakingEnvelopeSmoothed`, `speakingPhaseContinuous`, and the speaking flap guard remain the stability contract.
- Ring fragments: no spinner behavior was added. Ring fragments remain slow, subtle, independent, and secondary to the blob center.
- Known limitations: visual sweet spot still needs live Ghost renderer QA because offscreen frame probes can show movement but cannot fully judge perceived calmness on the real display.

UI-P2A.6.2 Aperture shimmer motion pass:

- Purpose: UI-P2A.6.2 keeps the organic blob hybrid center and animates the aperture shimmer as embedded living-glass refraction rather than a static dot, blink, sparkle, or separate sticker.
- Shimmer behavior: `apertureShimmerMotionVersion: "UI-P2A.6.2"` exposes the frontend-only motion marker. The shimmer uses a tiny elliptical offset inside the blob, a separate secondary offset phase, and a clipped radial/crescent highlight so the glint moves within the center aperture without leaving the lens.
- Timing rules: the primary shimmer drift stays slow at `apertureShimmerDriftCycleMs` and the secondary offset stays slower at `apertureShimmerSecondaryCycleMs`. The shimmer uses the same continuous anchor time base as the blob but independent cycle lengths, so repeated state updates do not restart it.
- Intensity rules: `apertureShimmerOpacityMin` and `apertureShimmerOpacityMax` bound the effect. Idle remains calm, speaking/listening may add only small backend-supported intensity, and unavailable/muted states remain deliberately subdued.
- No-blink/no-sparkle rule: the shimmer must not pulse quickly, twinkle, act like a loading indicator, fake speaking/listening/thinking, or revive a uniform center scale pulse. `uniformScalePulseDisabled` and `idleUniformScalePulseDisabled` remain true.
- Truthfulness and boundaries: P2A.6.2 is Stormforge-only visual motion. It does not change backend/Core/planner/bridge contracts, voice pipeline logic, fog, Ghost layout, Deck behavior, Classic visuals, command authority, approval truth, or frontend-owned state.
- Known limitations: offscreen frame probes can confirm center-region pixel movement, but live Ghost renderer QA is still needed to judge whether the glint reads as premium glass motion on the actual display.

UI-P2A.6.3 Anchor presence, speaking expression, and shimmer legibility pass:

- Purpose: UI-P2A.6.3 keeps the organic blob hybrid architecture and makes the anchor easier to perceive live. It is a controlled presence/expression pass, not a redesign or a return to the old uniform scale pulse.
- Presence tuning: `anchorPresenceTuningVersion: "UI-P2A.6.3"` exposes the bounded pass marker. `anchorPresenceBoost` raises center glow, rim, signal point, idle center floor, ring-fragment opacity, and local ring contrast by roughly 10-20% while leaving unavailable/dev deliberately subdued.
- Speaking expression: `speakingExpressionBoost` increases supported speaking radiance, response arcs, waveform strength, and speaking blob deformation modestly. It still uses `speakingEnvelopeSmoothed`, `speakingPhaseContinuous`, and `speakingStateFlapGuardEnabled`, so speaking remains smooth and backend/playback-bound rather than a fake idle animation.
- Shimmer legibility: `apertureShimmerMotionVersion: "UI-P2A.6.3"` and `shimmerLegibilityBoost` mark the stronger live-legibility tuning. The pass raises the aperture shimmer opacity range, local highlight contrast, drift distance, and glint radius so the effect is visible when watching the center for several seconds. The shimmer remains clipped inside the blob lens, uses an independent phase, and does not blink or twinkle.
- No-trampoline/no-sparkle rules: `uniformScalePulseDisabled`, `idleUniformScalePulseDisabled`, and `idleUniformScaleAmplitude: 0.0` remain active. Idle must remain calm and watchful, the shimmer must read as glass/refraction, and speaking must not become an alarm or fast equalizer.
- Truthfulness and boundaries: P2A.6.3 remains Stormforge-only visual tuning. Speaking visuals still require backend-derived speaking/playback support; listening, acting, approval, warning, and failure still require their existing state inputs. No fog, Ghost layout, Deck, Classic, backend/Core/planner/bridge contract, voice-pipeline, or state-model changes belong to this pass.
- Known limitations: offscreen frame probes show shimmer and speaking movement, but perceived legibility should be judged in live Stormforge Ghost with the actual renderer and display brightness.

UI-P2A.6.4 Anchor state binding, speaking attack, and cadence pass:

- Purpose: UI-P2A.6.4 fixes the live Ghost symptom where the anchor could appear to have only idle and speaking postures. It keeps the organic blob hybrid design and adds a presentation-only state binding layer so the anchor can truthfully reflect existing Ghost, route, assistant, card, action, and voice/playback state.
- State binding: `StormforgeGhostShell.qml` now exposes `assistantState` and `routeInspector` inputs and derives `ghostTone` with `ghostToneSource`. Precedence is unavailable/failed/blocked/approval first, then backend-supported speaking, then listening/capturing/transcribing, acting/executing, thinking/routing/planning, wake/ready, mock/dev, and idle fallback. `StormforgeAnchorHost.qml` forwards the source hint while `StormforgeAnchorCore.qml` exposes `anchorStateBindingVersion`, `derivedAnchorVisualState`, `anchorVisualStateSource`, `statePrecedenceVersion`, and `supportedVisualStates` for QML tests.
- Alias coverage: state aliases such as `planning`, `planned`, `running`, `execution`, `in_progress`, `permission_required`, `pending_approval`, `trust_pending`, `warning`, `failure`, `disabled`, `mock`, and `dev` normalize into the existing visual vocabulary instead of collapsing to idle.
- Organic cadence: `organicCadenceVersion: "UI-P2A.6.4"` and `organicCadenceSpeedupFactor` mark a roughly 18% faster organic cadence. Blob primary/secondary/drift cycles move to `10000`/`16000`/`24500` ms, blob shimmer to `31500` ms, and aperture shimmer drift/secondary cycles to `12500`/`19500` ms. Ring-fragment periods remain slow so the dial does not become a spinner.
- Speaking attack smoothing: `speakingAttackSmoothingEnabled`, `speakingAttackMs`, `speakingReleaseMs`, and `speakingStartupStable` expose the startup-ramp contract. Speaking keeps a continuous phase, smoothed envelope, and short grace against micro-flicker, but it no longer seeds a large raw-level jump on the first playback frame. Speaking still requires `speaking_visual_active` or active playback status.
- Truthfulness and boundaries: P2A.6.4 does not add backend state, command authority, approval authority, or voice-pipeline behavior. The Main/VariantGhostShell change is only a presentation mapping of existing `UiBridge.assistantState` and `UiBridge.routeInspector` into the Stormforge Ghost shell. Unknown or missing state still falls back to visible idle/ready, and urgent unavailable/failed/blocked/approval states are not delayed behind speaking.
- Classic/fog boundary: Classic QML files are unchanged; Stormforge does not become default. Fog remains UI-P2VF ownership and is neither implemented nor tuned in this pass.
- Known limitations: if the bridge payload does not populate a meaningful route, action, card, assistant, or voice state for a live operation, the anchor must truthfully remain idle/ready. Live Ghost QA should confirm that the existing bridge values are present during real thinking, acting, approval, warning, and failure flows.

UI-P2A.6.5 Anchor live state latching and idle presence hotfix:

- Purpose: UI-P2A.6.5 fixes two live Stormforge Ghost blockers: idle/ready could become practically invisible, and active states could flicker back to idle when a short bridge/voice/playback update gap arrived.
- Idle presence floors: `StormforgeAnchorCore.qml` now exposes `idlePresenceFloorEnabled`, `idleBlobOpacityFloor`, `idleRingOpacityFloor`, `idleCenterGlowFloor`, `idleFragmentOpacityFloor`, and `idleAnchorVisible`. Idle/ready remain quiet and non-commanding, but the organic blob, center glow, signal point, ring fragments, bearing ticks, and label have explicit token-backed floors so the anchor does not vanish against the Ghost stage or future fog.
- Idle perceptual hotfix: `idlePerceptualPresenceVersion: "UI-P2A.6.5A"` raises the actual live idle/ready luminance floor after testing showed that nonzero diagnostic opacity was still too faint. Idle is still calm, but its center blob, inner glow, signal point, ring fragments, and bearing ring now render as an intentional identity mark rather than a barely-there trace. The Stormforge Ghost anchor host also gets a contained size floor bump so idle does not read as missing in the live stage.
- Visual state latch: the anchor separates `rawDerivedVisualState` from `latchedVisualState`/`normalizedState`. Missing, null, unknown, or idle fallback no longer erases a recently valid active visual state inside a bounded micro-flicker window. The latch is QML presentation smoothing only; it does not mutate backend state or create command truth.
- Speaking stability: speaking still requires `speaking_visual_active` or active playback support, but `visualSpeakingActive` now survives brief playback-state flicker through `speakingLatchMs` while the smoothed envelope releases. The speaking phase stays continuous and repeated same-state updates do not restart the animation.
- Transition continuity: mode changes keep the organic motion clock, shimmer phase, ring-fragment phase, orbit, wave phase, and speaking phase continuous. State-specific geometry arrives through a token-backed `stateFeatureAlpha` floor instead of making the anchor look like it reset to a first frame.
- State precedence and dwell: unavailable, failed, blocked, and approval required remain urgent and override speaking immediately. Speaking, thinking/routing, acting/executing, listening/capturing/transcribing, and wake states get short token-backed visual dwell windows; idle wins once no current or recently valid active source remains.
- Truthfulness and boundaries: UI-P2A.6.5 is Stormforge-only. It does not change backend/Core/planner/bridge contracts, voice-pipeline logic, fog, Ghost layout, Deck behavior, Classic visuals, approval authority, route truth, or command progress. If the existing bridge never emits a supported active state, the anchor still truthfully falls back to visible idle/ready.
- Known limitations: this is a focused hotfix with QML construction and latch tests plus local artifacts. It should be followed by live Stormforge Ghost QA to verify real bridge cadence, playback updates, and state dwell under actual use.

UI-P2A.6.6 Anchor never-vanish invariant and voice-offline separation hotfix:

- Purpose: UI-P2A.6.6 fixes the live case where Ghost showed `Ready`/`Voice offline` while the anchor almost disappeared. Voice capture availability is now separated from Stormhelm identity availability.
- Voice offline distinction: `StormforgeAnchorCore.qml` exposes `voiceAvailabilityState` and `voiceOfflineDoesNotHideAnchor`. Voice/capture states such as `capture_disabled`, `voice_unavailable`, `provider_unavailable`, `offline`, and voice-phase `unavailable` may drive the sublabel `Voice offline`, but they no longer collapse the anchor visual state to `unavailable`. Voice availability cards such as `Voice Capture / Unavailable / Capture disabled` are also treated as voice-status context, not Stormhelm identity shutdown. Speaking/listening visuals still require the existing speaking/playback or capture/listening state.
- Never-vanish floor: `neverVanishInvariantVersion: "UI-P2A.6.6"` adds final composited diagnostics including `finalAnchorOpacityFloor`, `finalBlobOpacity`, `finalRingOpacity`, `finalCenterGlowOpacity`, `finalSignalPointOpacity`, `finalBearingTickOpacity`, `finalVisibilityFloorApplied`, and `finalAnchorVisible`. These floors are applied after state dimming/muted multipliers so later opacity math cannot erase the identity core.
- Unavailable styling: true explicit anchor/system `unavailable` remains dimmer than idle and uses the sublabel `Stormhelm unavailable`, but it still renders a visible blob, signal point, bearing ticks, rings, and label. It is not allowed to become black-on-black unless the parent shell intentionally hides the whole anchor.
- Ghost integration: `StormforgeGhostShell.qml` no longer treats voice-only offline/muted/interrupted playback fields or voice-capture context cards as Ghost-level `unavailable`. Lifecycle install-boundary hold cards remain visible as context cards, but they are treated as lifecycle advisories for the anchor instead of command-blocking anchor state; speaking/playback can still take over truthfully while audio is active. Cards, route state, actions, and explicit assistant/system unavailable or blocked states can still select unavailable or warning postures.
- Boundaries: this is Stormforge-only. It does not change Classic, fog implementation, Ghost layout, Deck behavior, backend/Core/planner/bridge contracts, voice backend behavior, approval authority, or command progress truth.
- Known limitations: the hotfix proves QML construction and visual artifacts for voice-offline and unavailable states. Live QA should still confirm that the bridge payload supplies the same `voice_available`/`unavailable_reason` shape during real local capture failures.

UI-P2A.6.7 Anchor advisory binding and transition glide hotfix:

- Purpose: UI-P2A.6.7 fixes the live case where lifecycle/install-boundary advisories kept the anchor in `Warning` while backend playback truth was `speaking`. Lifecycle boundary text such as `Lifecycle Hold`, `install posture changed`, and `Held at boundary` remains visible as context/status, but it no longer owns the anchor's live mode or suppresses truthful speaking.
- State binding: `StormforgeGhostShell.qml` now filters lifecycle advisory cards, route-inspector text, and assistant warning state before selecting the anchor tone. Urgent non-advisory unavailable, failed, blocked, approval, card, action, and explicit assistant states still retain their existing precedence. Voice speaking still requires `speaking_visual_active` or active playback status.
- Organic cadence: the organic center timing is about 20% faster while preserving the organic-blob hybrid architecture and the no-uniform-scale-pulse rule. The main blob cycles are now 8.0s, 12.8s, and 19.6s, with shimmer cadence adjusted proportionally.
- Transition glide: `StormforgeAnchorCore.qml` exposes `modeTransitionContinuityVersion: "UI-P2A.6.7"`, `stateFeatureCrossfadeEnabled`, `colorTransitionSmoothingEnabled`, `transitionFromState`, `transitionToState`, and `transitionBlendProgress`. The Canvas blends previous and target state colors, crossfades state-specific geometry, keeps the organic/shimmer/ring phases continuous, and animates label color/opacity instead of looking like a reset between modes.
- Speaking onset stabilization: `speakingOnsetStabilityVersion: "UI-P2A.6.7"` adds a bounded onset guard for the first 1.5 seconds of truthful playback-backed speaking. Startup frames with zero level, brief support flicker, or an early raw-level spike no longer slam the envelope or drop the anchor back to idle; they ramp through `speakingTargetEnvelope`, `speakingEnvelopeSmoothed`, and the continuous `speakingPhase` timebase.
- Envelope and latch rules: speaking attack is 680 ms, release is 780 ms, micro-flicker grace is 1050 ms, and the speaking latch is bounded at 1320 ms. The onset guard may suppress brief startup flicker, but urgent unavailable, failed, blocked, and approval states still override promptly. The guard smooths existing playback/speaking support only and does not create frontend-owned speaking truth.
- Boundaries: this pass is Stormforge-only. It does not change Classic, fog, Ghost layout, Deck behavior, backend/Core/planner/bridge contracts, voice-pipeline logic, approval authority, or command progress truth.

UI-P2A.6.7R Anchor speaking render-loop regression fix:

- Purpose: UI-P2A.6.7R fixes the regression where speaking-mode voice/envelope updates could make the whole Stormforge Ghost scene stutter, including fog. The root cause was direct Canvas repaint requests from high-frequency speaking/audio property-change handlers while the anchor already had a visual animation timer.
- Repaint cadence: `StormforgeAnchorCore.qml` exposes `renderLoopRegressionGuardVersion: "UI-P2A.6.7R"`, `requestPaintCoalescingEnabled`, `voiceEventDirectPaintDisabled`, `anchorFrameTimerIntervalMs`, and `paintCoalesceIntervalMs`. Voice/playback events now update target values and latch flags only; Canvas painting is coalesced behind a bounded timer instead of being requested directly on every raw playback-level change.
- Diagnostics: optional dev/test diagnostics include `renderLoopDiagnosticsEnabled`, `anchorPaintCountPerSecond`, `anchorRequestPaintCountPerSecond`, `speakingUpdateCountPerSecond`, `speakingEnvelopeUpdateCountPerSecond`, and `animationCadenceWarning`. These are frontend diagnostics only and do not become backend truth or command authority.
- Speaking behavior: the existing truth-bound speaking latch, attack/release smoothing, continuous phase, and urgent-state overrides remain in place. The fix changes update cadence, not the visual design or backend voice pipeline.
- Fog boundary: this pass does not tune or rewrite fog. The acceptance condition is that anchor rendering no longer starves the shared QML scene while speaking, so fog animation can remain smooth under its existing implementation.

UI-P2A.6.8 Anchor speaking audio-reactivity, envelope decoupling, and ring-fragment visibility pass:

- Purpose: UI-P2A.6.8 makes the already-truth-bound speaking animation about 50% more expressive and lifts the slow rotating ring fragments slightly so they are easier to perceive live without changing idle semantics, fog, Classic, Ghost layout, or backend contracts.
- Speaking strength: `StormforgeTokens.qml` raises `anchorSpeakingExpressionBoost` from `1.28` to `1.92` and exposes `anchorSpeakingAudioReactiveStrengthBoost: 1.50`. `StormforgeAnchorCore.qml` exposes `speakingAudioReactiveStrengthVersion: "UI-P2A.6.9"` and `speakingAudioReactiveStrengthBoost` for focused QML tests.
- Audio-reactive scope: the boost applies only inside the supported speaking posture: blob edge ripple, speaking blob deformation, center glow response, speaking radiance rings/arcs, and waveform amplitude. It does not make idle look active, does not alter warning/approval semantics, and does not reintroduce uniform scale bounce.
- Envelope decoupling: `reactiveEnvelopeVersion: "UI-P2A.6.8"` adds a Stormforge-only QML visual envelope between bridge playback-level events and anchor geometry. Raw level updates only refresh `reactiveLevelTarget`; the frame timer advances `reactiveEnvelope`, `visualSpeechEnergy`, and `finalSpeakingEnergy` continuously, so sparse chunks, zero gaps, and burst spikes cannot directly jerk the center blob or radiance rings.
- Procedural speech synthesis: while existing truthful speaking/playback support keeps `visualSpeakingActive` true, `proceduralSpeechEnergy` provides calm speech-like motion if the real playback meter is sparse or temporarily missing. It is a visual synthesizer only: it does not claim semantic audio content, does not run in idle, and releases after the bounded speaking latch/release window.
- Smoothing rules: `finalSpeakingEnergy` is a jitter-guarded blend of the smoothed real envelope and procedural speech energy. Raw level spikes are rate-limited, raw zero gaps are held through the visual envelope, `speakingPhase` remains monotonic, and raw playback events do not call Canvas paint or reset animation phase.
- Ring fragments: `ringFragmentVisibilityVersion: "UI-P2A.6.8"` marks the small visibility lift. Fragment opacity and floors are slightly higher, but rotation periods and staggered direction remain unchanged so the fragments read as calm instrument current rather than a loading spinner.
- Diagnostics: frontend/test-only diagnostics include `audioReactiveDecoupled`, `reactiveEnvelopeVersion`, `rawPlaybackLevel`, `reactiveLevelTarget`, `reactiveEnvelope`, `proceduralSpeechEnergy`, `finalSpeakingEnergy`, `rawLevelUpdateCount`, `reactiveEnvelopeContinuous`, `proceduralSpeechSynthEnabled`, `rawLevelDirectGeometryDriveDisabled`, `missingRawLevelUsesProceduralSpeechEnergy`, and `speakingEnergyJitterGuardEnabled`.
- Truthfulness and boundaries: speaking visuals still require existing playback/speaking support such as `speaking_visual_active` or active playback status. The pass changes visual expression and visual-envelope continuity only; it does not invent frontend state, command progress, backend voice truth, Classic visuals, fog behavior, Ghost layout, Deck behavior, planner routing, or voice playback audio behavior.

UI-P2R Stormforge render cadence and voice sync stabilization:

- Purpose: UI-P2R gives Stormforge Ghost one bounded visual timing source during speech so fog, anchor phase, shimmer, ring fragments, and audio-reactive motion advance from a steady visual frame clock rather than independent animation timers or irregular backend voice event cadence.
- Shared clock: `StormforgeAnimationClock.qml` exposes `renderCadenceVersion: "UI-P2R"`, `targetFps: 60`, `minAcceptableFps: 30`, `animationTimeMs`, `animationTimeSec`, `deltaTimeMs`, `frameCounter`, measured FPS, long-frame counters, max frame gaps, and cadence-stability flags. The clock runs only while the Stormforge Ghost is visible and clamps large deltas to avoid visible animation jumps after a delayed frame.
- Voice event coalescing: `StormforgeGhostShell.qml` keeps raw `voiceState` as the backend input, but applies it to `visualVoiceState` on the shared animation frame. Stormforge child components consume `visualVoiceState`, so high-rate playback/envelope events set visual targets at frame cadence instead of rebinding the whole Ghost subtree at backend event cadence.
- Anchor timing: `StormforgeAnchorCore.qml` exposes `voiceVisualSyncVersion: "UI-P2R"`, `sharedVisualClockActive`, `audioReactiveUsesVisualClock`, and `rawAudioEventsDoNotRequestPaint`. When the shared clock is present, the anchor disables its fallback frame timer, advances organic motion/speaking phase/envelope from shared `deltaTimeMs`, and flushes at most one Canvas paint per shared frame.
- Fog timing: `StormforgeVolumetricFogLayer.qml` exposes `fogVisualClockVersion: "UI-P2R"` and `fogUsesSharedVisualClock`. The shader `time` uniform comes from the shared clock when available; the old `NumberAnimation` phase remains only as a fallback for isolated fog harnesses.
- Diagnostics: Ghost-level diagnostics include `visualClockFps`, `visualClockLongFrameCount`, `voiceEventRateDuringSpeaking`, `anchorPaintFpsDuringSpeaking`, `fogTickFpsDuringSpeaking`, `speakingVisualLatencyEstimateMs`, `rawAudioEventsDoNotRequestPaint`, and cadence-stability flags. `scripts/run_stormforge_render_cadence_probe.py` simulates voice event churn with fog enabled and writes `.artifacts/stormforge_render_cadence/stormforge_p2r_cadence_report.json`.
- Boundaries: this is Stormforge-only timing/synchronization work. It does not tune fog appearance, redesign Anchor art, change Classic, change Ghost layout, change Deck behavior, alter backend/Core/planner contracts, or change voice playback audio behavior.

UI-P2R.1 live renderer cadence and fog timebase fix:

- Purpose: UI-P2R.1 fixes the shared-clock fog speed regression and adds a live desktop renderer proof path for the speaking-plus-fog case. The offscreen cadence probe remains useful for QML binding and shared-clock contract checks, but it is not final proof that the real desktop renderer is swapping frames smoothly during voice playback.
- Fog timebase: `StormforgeVolumetricFogLayer.qml` exposes `fogTimebaseVersion: "UI-P2R.1"`, `fogTimeInputUnit: "seconds"`, `fogSharedClockTimeSec`, `fogLegacyPhaseUnitsPerSecond`, `fogEffectiveDriftSpeed`, `fogFallbackAnimationActive`, and `fogDoubleDriven`. Shared-clock seconds are scaled into the legacy fog phase domain (`10000.0 / 520000.0` phase units per second) before reaching the shader `time` uniform, matching the old slow VF-4 drift instead of treating elapsed seconds as raw fog phase units.
- Double-drive guard: the fallback `NumberAnimation` remains the isolated harness fallback and is inactive while the shared visual clock is active. `fogDoubleDriven` must remain `false` in the normal Stormforge Ghost path.
- Live proof path: `scripts/run_stormforge_live_renderer_probe.py` opens a visible desktop `QQuickWindow`, drives Stormforge speaking-state churn with fog enabled, and records actual `frameSwapped` intervals, long frames over 33 ms, severe frames over 50 ms, voice update rate, visual-state apply count, anchor paint cadence, fog tick cadence, and fog timebase state. It writes `live_renderer_cadence_report.json`, `live_renderer_cadence_report.md`, `live_frame_intervals.csv`, `live_voice_update_churn_report.json`, and `fog_timebase_report.json`.
- Acceptance model: the Stormforge Ghost visual path should maintain at least 30 Hz while visible. Timer FPS alone is not enough for live acceptance; frame-swapped desktop evidence or direct production-window renderer diagnostics are required for the speaking-plus-fog smoothness claim.
- Voice sync: audio-reactive anchor motion remains truth-bound to active playback/speaking support and continues to use the shared visual clock plus the already-decoupled UI-P2A.6.8 envelope. P2R.1 does not change the voice playback backend or invent speaking when playback is inactive.
- Boundaries and limitations: UI-P2R.1 is Stormforge-only. It does not change Classic, Deck, Ghost layout, planner/Core routing, or the voice audio path. The live probe measures a real desktop probe window with `frameSwapped`; it is stronger than offscreen `grabWindow`, but it is still not the same as attaching to an already-running production Stormhelm UI process with transcript/surface-model churn unless those production diagnostics are exposed.

Voice-AR0 clean audio-reactive anchor reset:

- Purpose: Voice-AR0 makes the production Stormforge speaking visualizer a simple PCM stream meter beside the playback path. It intentionally bypasses the previous source-flapping envelope/timeline/warming chain.
- Backend model: `VoiceVisualMeter` accepts PCM chunks being submitted to playback, computes RMS/peak energy, normalizes it to one `0.0..1.0` scalar, applies lightweight attack/release smoothing, and emits at the configured 30-60 Hz visual cadence. It exposes scalar meter state only; raw PCM/audio bytes never enter the UI payload.
- Startup preroll: `[voice.visual_meter]` defaults to `enabled=true`, `sample_rate_hz=60`, `startup_preroll_ms=350`, `attack_ms=60`, `release_ms=160`, `noise_floor=0.015`, `gain=2.0`, `max_startup_wait_ms=800`, and `visual_offset_ms=0`. When streaming PCM arrives before playback starts, the meter consumes the preroll so the first visual frames already have energy. If preroll fills quickly, playback starts promptly; if it cannot fill before the max wait, playback continues and the payload reports a typed unavailable/timeout reason instead of hanging.
- UI bridge model: production voice payloads expose one visual truth surface: `voice_visual_energy`, `voice_visual_active`, `voice_visual_source`, `voice_visual_playback_id`, `voice_visual_available`, `voice_visual_disabled_reason`, `voice_visual_sample_rate_hz`, `voice_visual_started_at_ms`, `voice_visual_latest_age_ms`, and `raw_audio_present=false`. QML does not choose among envelope, timeline, meter, and warming sources.
- Stormforge Anchor model: `StormforgeAnchorCore.qml` drives blob deformation, radiance, subtle shimmer, and subtle ring energy from `voice_visual_energy` only while truthful speaking/playback is active and `voice_visual_source == "pcm_stream_meter"`. Idle organic motion remains independent, and the anchor keeps the no-uniform-scale-pulse rule.
- Diagnostic modes: supported production/diagnostic modes are `off`, `procedural_test`, `pcm_stream_meter`, and optional `constant_test_wave`. `procedural_test` is an explicit configured fallback for local visual testing and must not fake speaking while playback is inactive.
- Deprecated chain: `VoicePlaybackEnvelopeFollower`, envelope timeline samples, playback-envelope warming labels, timeline alignment gates, and visual source switching are legacy diagnostic/test paths only. They are not the default Stormforge production visualizer, and labels such as `Playback envelope warming` or `Stormhelm playback meter` must not flicker during one spoken response.
- Fog isolation: `STORMHELM_STORMFORGE_FOG=0/1` remains the Stormforge fog switch. Voice-AR0 does not tune fog art or fog timing.
- Boundaries: this does not change TTS text generation, STT, planner/Core routing, command authority, Classic UI, Deck layout, Ghost layout, fog tuning, or playback audio behavior beyond computing safe scalar telemetry beside the supported PCM playback path.

Voice-AR-DIAG audio-reactive chain probe:

- Purpose: Voice-AR-DIAG measures the scalar signal path from deterministic synthetic PCM through the backend meter, UI payload handoff, QML-received voice energy, `finalSpeakingEnergy`, and Anchor paint/frame diagnostics. It is a proof harness, not a visual tuning pass.
- Probe command: `python scripts\run_voice_reactive_chain_probe.py --mode closed-loop` generates no audible output. `--mode local-playback` also plays the synthetic test signal locally when the Windows sound API is available.
- Artifacts: the probe writes `.artifacts/voice_reactive_chain/voice_reactive_chain_report.json`, `.artifacts/voice_reactive_chain/voice_reactive_chain_report.md`, and `.artifacts/voice_reactive_chain/energy_timeline.csv`.
- QML diagnostics: `StormforgeAnchorCore.qml` and `StormforgeAnchorHost.qml` expose diagnostic-only properties including `qmlReceivedVoiceVisualEnergy`, `qmlReceivedEnergyTimeMs`, `qmlFinalSpeakingEnergy`, `qmlSpeechEnergySource`, `qmlVoiceVisualActive`, `qmlEnergySampleAgeMs`, `qmlAnchorPaintCount`, `qmlLastPaintTimeMs`, `qmlFrameTimeMs`, and `qmlAnchorReactiveChainVersion`.
- Classification: `backend_meter_flat`, `payload_handoff_flat`, `qml_receive_flat`, `anchor_mapping_flat`, `qml_paint_missing`, `latency_too_high`, `sample_drop_detected`, and `correlation_poor` point to the stage where scalar energy was lost, delayed, flattened, clipped, or desynchronized. `chain_pass` means the measured scalar path survived with bounded latency.
- Privacy boundary: the probe may generate synthetic PCM in memory and, in local-playback mode, a temporary WAV for playback, but reports, logs, UI payloads, and CSV rows contain only scalar energy/timing fields and `raw_audio_present=false`.

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
