import QtQuick 2.15

Item {
    id: root

    property var voiceState: ({})
    property var voiceVisualState: ({})
    property string assistantState: "idle"
    property string label: ""
    property string sublabel: ""
    property real intensity: -1
    property bool active: true
    property bool disabled: false
    property bool warning: false
    property real speakingLevel: -1
    property real audioLevel: 0
    property real progress: 0
    property real pulseStrength: 0
    property bool compact: false
    property string stateSourceHint: ""

    readonly property bool finalAnchorImplemented: true
    readonly property string componentRole: "stormforge_anchor_core"
    readonly property string visualTuningVersion: "UI-P2A.6.1"
    readonly property string idlePresenceHotfixVersion: "UI-P2A.4A"
    readonly property string stateStabilityVersion: "UI-P2A.6"
    readonly property string organicMotionVersion: "UI-P2A.6.1"
    readonly property string blobMotionSweetSpotVersion: "UI-P2A.6.1"
    readonly property string organicMotionAmplitudeVersion: "UI-P2A.6.1"
    readonly property string apertureShimmerMotionVersion: "UI-P2A.6.3"
    readonly property string anchorPresenceTuningVersion: "UI-P2A.6.3"
    readonly property string anchorMotionArchitecture: "organic_blob_hybrid"
    readonly property bool blobCoreEnabled: true
    readonly property bool apertureShimmerAnimated: true
    readonly property bool apertureShimmerUsesIndependentPhase: true
    readonly property bool apertureShimmerVisibleTarget: true
    readonly property bool speakingExpressionPronounced: true
    readonly property string speakingOnsetStabilityVersion: "UI-P2A.6.7"
    readonly property string speakingAudioReactiveStrengthVersion: "UI-P2A.6.9"
    readonly property string ringFragmentVisibilityVersion: "UI-P2A.6.8"
    readonly property string anchorStateBindingVersion: "UI-P2A.6.4"
    readonly property string statePrecedenceVersion: "UI-P2A.6.4"
    readonly property string visualStateLatchVersion: "UI-P2A.6.5"
    readonly property string idlePerceptualPresenceVersion: "UI-P2A.6.5A"
    readonly property string neverVanishInvariantVersion: "UI-P2A.6.6"
    readonly property string modeTransitionContinuityVersion: "UI-P2A.6.7"
    readonly property string renderLoopRegressionGuardVersion: "UI-P2A.6.7R"
    readonly property string reactiveEnvelopeVersion: "UI-P2A.6.8"
    readonly property bool modeTransitionEasingEnabled: true
    readonly property bool stateFeatureCrossfadeEnabled: true
    readonly property bool colorTransitionSmoothingEnabled: true
    readonly property bool animationTimebaseContinuous: true
    readonly property bool transitionDoesNotResetAnchor: true
    readonly property bool requestPaintCoalescingEnabled: true
    readonly property bool voiceEventDirectPaintDisabled: true
    readonly property bool audioReactiveDecoupled: true
    readonly property bool reactiveEnvelopeContinuous: true
    readonly property bool proceduralSpeechSynthEnabled: true
    readonly property bool rawLevelDirectGeometryDriveDisabled: true
    readonly property bool missingRawLevelUsesProceduralSpeechEnergy: true
    readonly property bool speakingEnergyJitterGuardEnabled: true
    readonly property string playbackEnvelopeVersion: "Voice-L0.2.1"
    readonly property string playbackEnvelopeVisualDriveVersion: "Voice-L0.2.1A"
    readonly property string envelopeDynamicsVersion: "Voice-L0.3"
    readonly property string sourceLatchVersion: "Voice-L0.4"
    readonly property string timelineVisualizerVersion: "Voice-L0.6"
    readonly property string liveVoiceIsolationVersion: "UI-VOICE-LIVE-ISO"
    readonly property bool envelopeBackedProceduralBaseEnabled: true
    readonly property bool envelopeDrivesVisualDynamics: true
    readonly property bool speakingPlateauSuppressionEnabled: true
    readonly property bool centerUniformSpeakingScaleDisabled: true
    readonly property bool sourceFlapGuardEnabled: true
    readonly property bool visualizerSourceSwitchingDisabled: true
    readonly property bool playbackEnvelopeRequiresTimebaseAlignment: true
    readonly property bool proceduralFallbackContinuityEnabled: true
    readonly property int envelopeDynamicsWindowMs: 1600
    readonly property string voiceVisualSyncVersion: "UI-P2R"
    readonly property string qmlAnchorReactiveChainVersion: "Voice-AR-DIAG"
    readonly property string anchorRendererArchitectureVersion: root.ar3SplitRendererActive
        ? "Voice-AR3-static-frame-dynamic-core"
        : root.qsgCandidateRendererActive
            ? "Voice-AR5-legacy-blob-qsg-candidate"
            : root.legacyBlobFastCandidateActive
                ? "Voice-AR4-legacy-blob-fast-candidate"
                : "Voice-AR4-legacy-blob-reference"
    readonly property string anchorRendererArchitecture: root.ar3SplitRendererActive
        ? "static_nautical_frame_cached_dynamic_voice_core"
        : root.qsgCandidateRendererActive
            ? "legacy_blob_qsg_candidate_cached_frame_qsg_dynamic"
            : root.legacyBlobFastCandidateActive
                ? "legacy_blob_fast_candidate_canvas"
                : "legacy_blob_reference_canvas"
    readonly property bool staticFrameLayerEnabled: root.ar3SplitRendererActive || root.qsgCandidateRendererActive
    readonly property bool dynamicCoreLayerEnabled: root.ar3SplitRendererActive || root.qsgCandidateRendererActive
    readonly property bool fullFrameVoiceCanvasRepaintDisabled: root.ar3SplitRendererActive || root.qsgCandidateRendererActive
    property real visualClockAnimationTimeMs: -1
    property real visualClockDeltaMs: root.anchorFrameTimerIntervalMs
    property real visualClockWallTimeMs: 0
    property int visualClockFrameCounter: 0
    property real visualClockMeasuredFps: 0
    property int visualClockLongFrameCount: 0
    property string visualizerDiagnosticMode: "auto"
    property string anchorRenderer: "legacy_blob_reference"
    readonly property string effectiveAnchorRenderer: root.normalizeAnchorRenderer(root.anchorRenderer)
    readonly property bool legacyBlobReferenceActive: root.effectiveAnchorRenderer === "legacy_blob_reference"
    readonly property bool legacyBlobFastCandidateActive: root.effectiveAnchorRenderer === "legacy_blob_fast_candidate"
    readonly property bool legacyBlobRendererActive: root.legacyBlobReferenceActive || root.legacyBlobFastCandidateActive
    readonly property bool ar3SplitRendererActive: root.effectiveAnchorRenderer === "ar3_split"
    readonly property bool qsgCandidateRendererActive: root.effectiveAnchorRenderer === "legacy_blob_qsg_candidate"
    readonly property string requestedAnchorVisualizerMode: root.normalizeAnchorVisualizerMode(root.visualizerDiagnosticMode) !== "auto"
        ? root.normalizeAnchorVisualizerMode(root.visualizerDiagnosticMode)
        : root.normalizeAnchorVisualizerMode(
            voiceValue("requested_anchor_visualizer_mode", voiceValue("requestedAnchorVisualizerMode", "auto"))
        )
    readonly property string effectiveAnchorVisualizerMode: root.requestedAnchorVisualizerMode !== "auto"
        ? root.requestedAnchorVisualizerMode
        : root.normalizeAnchorVisualizerMode(
            voiceValue(
                "anchor_visualizer_mode",
                voiceValue(
                    "anchorVisualizerMode",
                    voiceValue("effective_anchor_visualizer_mode", voiceValue("effectiveAnchorVisualizerMode", "auto"))
                )
            )
        )
    readonly property bool anchorVisualizerModeForced: root.effectiveAnchorVisualizerMode !== "auto"
    readonly property bool anchorReactiveAnimationDisabledByMode: root.effectiveAnchorVisualizerMode === "off"
    readonly property bool anchorVisualizerModeUnavailable: root.effectiveAnchorVisualizerMode === "envelope_timeline"
        && root.visualSpeakingActive
        && !root.playbackEnvelopeTimelineActive
    readonly property string anchorVisualizerModeUnavailableReason: root.anchorVisualizerModeUnavailable
        ? "envelope_timeline_unavailable"
        : ""
    readonly property bool forcedVisualizerModeHonored: !root.anchorVisualizerModeForced
        || root.visualizerSourceStrategy === root.visualizerSourceCandidate
    readonly property string forcedVisualizerModeUnavailableReason: root.anchorVisualizerModeUnavailable
        ? root.anchorVisualizerModeUnavailableReason
        : textValue(voiceValue("forced_visualizer_mode_unavailable_reason", voiceValue("forcedVisualizerModeUnavailableReason", "")), "")
    readonly property string visualizerStrategySelectedBy: root.anchorVisualizerModeForced
        ? "qml_override"
        : textValue(voiceValue("visualizer_strategy_selected_by", voiceValue("visualizerStrategySelectedBy", "service_auto")), "service_auto")
    readonly property bool sharedVisualClockActive: root.visualClockFrameCounter > 0
    readonly property bool audioReactiveUsesVisualClock: root.sharedVisualClockActive
    readonly property bool rawAudioEventsDoNotRequestPaint: true
    readonly property real visualClockFps: root.visualClockMeasuredFps
    readonly property real speakingVisualLatencyEstimateMs: root.sharedVisualClockActive
        ? Math.max(0, root.visualClockDeltaMs)
        : root.anchorFrameTimerIntervalMs
    readonly property int anchorFrameTimerIntervalMs: root.motionProfile === "breathing" ? 50 : 32
    readonly property int localSpeakingFrameIntervalMs: 16
    readonly property bool localSpeakingFrameClockActive: root.visualSpeakingActive
        && root.sharedVisualClockActive
        && (root.visualClockMeasuredFps <= 0
            || root.visualClockMeasuredFps < 30
            || root.visualClockDeltaMs > 34)
    readonly property int paintCoalesceIntervalMs: 16
    property bool renderLoopDiagnosticsEnabled: false
    property int anchorPaintCountPerSecond: 0
    property int anchorRequestPaintCountPerSecond: 0
    property int speakingUpdateCountPerSecond: 0
    property int speakingEnvelopeUpdateCountPerSecond: 0
    readonly property bool animationCadenceWarning: root.renderLoopDiagnosticsEnabled
        && (root.anchorPaintCountPerSecond > 70
            || root.anchorRequestPaintCountPerSecond > 70
            || root.speakingUpdateCountPerSecond > 90
            || root.speakingEnvelopeUpdateCountPerSecond > 70)
    readonly property string derivedAnchorVisualState: root.normalizedState
    readonly property string anchorVisualStateSource: resolveStateSource()
    readonly property var supportedVisualStates: [
        "idle",
        "ready",
        "wake_detected",
        "listening",
        "capturing",
        "transcribing",
        "thinking",
        "acting",
        "speaking",
        "approval_required",
        "blocked",
        "failed",
        "unavailable",
        "mock_dev"
    ]
    readonly property string organicCadenceVersion: "UI-P2A.6.4"
    readonly property real organicCadenceSpeedupFactor: sf.anchorOrganicCadenceSpeedupFactor
    readonly property bool speakingAttackSmoothingEnabled: true
    readonly property int speakingOnsetGuardMs: sf.durationAnchorSpeakingOnsetGuard
    readonly property int speakingAttackMs: sf.durationAnchorSpeakingAttack
    readonly property int speakingReleaseMs: sf.durationAnchorSpeakingRelease
    readonly property int speakingRawDropHoldMs: sf.durationAnchorSpeakingRawDropHold
    readonly property bool speakingStartupStable: true
    readonly property bool speakingEnvelopeSmoothingEnabled: true
    readonly property bool speakingPhaseResetOnUpdate: false
    readonly property string speakingPhaseSource: "continuous_time"
    readonly property real anchorPresenceBoost: sf.anchorPresenceBoost
    readonly property real speakingAudioReactiveStrengthBoost: sf.anchorSpeakingAudioReactiveStrengthBoost
    readonly property real speakingExpressionBoost: sf.anchorSpeakingExpressionBoost
    readonly property real shimmerLegibilityBoost: sf.anchorShimmerLegibilityBoost
    readonly property int blobPointCount: sf.anchorBlobPointCount
    readonly property bool organicBlobMotionActive: root.idleMotionActive
    readonly property bool uniformScalePulseDisabled: true
    readonly property real organicMotionAmplitude: sf.anchorBlobIdleDeformStrength
    readonly property real blobDeformationStrength: sf.anchorBlobIdleDeformStrength
    readonly property real blobBaseDeformationStrength: sf.anchorBlobDeformStrength
    readonly property real blobSpeakingDeformationStrength: sf.anchorBlobSpeakingDeformStrength
    readonly property int blobPrimaryCycleMs: sf.durationAnchorBlobPrimary
    readonly property int blobSecondaryCycleMs: sf.durationAnchorBlobSecondary
    readonly property int blobDriftCycleMs: sf.durationAnchorBlobDrift
    readonly property int apertureShimmerDriftCycleMs: sf.durationAnchorApertureShimmerDrift
    readonly property int apertureShimmerSecondaryCycleMs: sf.durationAnchorApertureShimmerSecondary
    readonly property real apertureShimmerOpacityMin: sf.anchorApertureShimmerOpacityMin
    readonly property real apertureShimmerOpacityMax: sf.anchorApertureShimmerOpacityMax
    readonly property real apertureShimmerPhase: (root.organicMotionTimeMs / Math.max(1, root.apertureShimmerDriftCycleMs)) * Math.PI * 2
    readonly property real apertureShimmerSecondaryPhase: (root.organicMotionTimeMs / Math.max(1, root.apertureShimmerSecondaryCycleMs)) * Math.PI * 2
    readonly property real apertureShimmerOffsetX: Math.sin(root.apertureShimmerPhase + 0.35) * sf.anchorApertureShimmerDriftX
        + Math.sin(root.apertureShimmerSecondaryPhase + 1.40) * sf.anchorApertureShimmerSecondaryX
    readonly property real apertureShimmerOffsetY: Math.sin(root.apertureShimmerPhase * 0.72 + 1.10) * sf.anchorApertureShimmerDriftY
        + Math.sin(root.apertureShimmerSecondaryPhase * 1.18 + 2.25) * sf.anchorApertureShimmerSecondaryY
    readonly property real apertureShimmerOpacity: root.apertureShimmerOpacityMin
        + (root.apertureShimmerOpacityMax - root.apertureShimmerOpacityMin) * clamp01(
            0.50
            + Math.sin(root.apertureShimmerPhase + 2.15) * 0.24
            + Math.sin(root.apertureShimmerSecondaryPhase - 0.65) * 0.15
            + (root.visualState === "speaking" ? root.finalSpeakingEnergy * 0.16 : 0)
            + (root.visualState === "speaking" ? root.envelopeExpandedEnergy * 0.18 + root.envelopeTransientEnergy * 0.12 : 0)
            + ((root.visualState === "listening" || root.visualState === "capturing") ? root.effectiveAudioLevel * 0.10 : 0)
        )
    readonly property bool idleUniformScalePulseDisabled: true
    readonly property bool idleOrganicMotionActive: root.idleMotionActive
    readonly property int idlePrimaryCycleMs: root.blobPrimaryCycleMs
    readonly property int idleSecondaryCycleMs: root.blobSecondaryCycleMs
    readonly property int idleDriftCycleMs: root.blobDriftCycleMs
    readonly property bool ringFragmentsActive: true
    readonly property int ringFragmentCount: sf.anchorRingFragmentCount
    readonly property int ringFragmentMinCycleMs: sf.durationAnchorRingFragmentMin
    readonly property int ringFragmentMaxCycleMs: sf.durationAnchorRingFragmentMax
    readonly property real ringFragmentOpacity: sf.anchorRingFragmentOpacity
    readonly property bool speakingAnimationStable: true
    readonly property int speakingGraceMs: sf.durationAnchorSpeakingGrace
    readonly property int speakingLatchMs: sf.durationAnchorSpeakingLatch
    readonly property int thinkingLatchMs: sf.durationAnchorThinkingLatch
    readonly property int actingLatchMs: sf.durationAnchorActingLatch
    readonly property int captureLatchMs: sf.durationAnchorCaptureLatch
    readonly property int wakeLatchMs: sf.durationAnchorWakeLatch
    readonly property int promptLatchMs: sf.durationAnchorPromptLatch
    readonly property bool speakingPhaseContinuous: true
    readonly property bool speakingStateFlapGuardEnabled: true
    readonly property bool visualStateStable: true
    readonly property bool animationPhaseDoesNotResetOnSameState: true
    readonly property real idleUniformScaleAmplitude: 0.0
    readonly property string signatureSilhouette: "helm_crown_lens_aperture"
    readonly property string centerLensSignature: "organic_blob_core"
    readonly property string normalizedStateFallback: "idle"
    readonly property int bearingTickCount: sf.anchorBearingTickCount
    readonly property real visualSoftness: sf.anchorVisualSoftness
    readonly property int presenceDepthLayerCount: sf.anchorDepthLayerCount
    readonly property int nauticalDetailCount: sf.anchorNauticalDetailCount
    readonly property int signatureFeatureCount: sf.anchorSignatureFeatureCount
    readonly property int centerLensLayerCount: sf.anchorCenterLensLayerCount
    readonly property int centerApertureSegmentCount: sf.anchorCenterApertureSegmentCount
    readonly property real centerLensRadiusRatio: sf.anchorCenterLensRadiusRatio
    readonly property real instrumentGlassOpacity: sf.anchorInnerGlassOpacity
    readonly property real depthShadowOpacity: sf.anchorDepthShadowOpacity
    readonly property real centerApertureStrength: sf.anchorCenterApertureOpacity
    readonly property real centerPearlStrength: sf.anchorCenterPearlOpacity
    readonly property real headingMarkerStrength: sf.anchorHeadingMarkerOpacity
    readonly property real outerClampStrength: sf.anchorOuterClampOpacity
    readonly property string rawDerivedVisualState: resolveState()
    property string latchedVisualState: root.normalizedStateFallback
    property string lastNonIdleVisualState: ""
    property double lastNonIdleStateChangedAt: 0
    property double stateDwellUntil: 0
    property string stateLatchReason: "idle_fallback"
    readonly property bool stateLatchActive: root.latchedVisualState !== root.rawDerivedVisualState
    readonly property string normalizedState: root.latchedVisualState.length > 0 ? root.latchedVisualState : root.normalizedStateFallback
    readonly property string resolvedState: root.normalizedState
    property string visualState: "idle"
    property string previousVisualState: "idle"
    property string pendingVisualState: ""
    property bool stateTransitionActive: false
    property real transitionProgress: 1.0
    property int visualStateChangeSerial: 0
    property double lastVisualStateChangeMs: 0
    readonly property int stateTransitionDurationMs: sf.durationAnchorStateTransition
    readonly property int stateMinimumDwellMs: sf.durationAnchorStateMinimumDwell
    readonly property real transitionBlendProgress: root.stateTransitionActive ? smoothStep(root.transitionProgress) : 1.0
    readonly property string transitionFromState: root.stateTransitionActive ? root.previousVisualState : root.visualState
    readonly property string transitionToState: root.visualState
    readonly property bool idleMotionActive: isIdlePresenceState(root.visualState) && !root.disabled && root.visible
    readonly property real organicPrimaryValue: organicSine(root.organicMotionTimeMs, root.idlePrimaryCycleMs, 0.0)
    readonly property real organicSecondaryValue: organicSine(root.organicMotionTimeMs, root.idleSecondaryCycleMs, 1.7)
    readonly property real organicDriftValue: organicSine(root.organicMotionTimeMs, root.idleDriftCycleMs, 0.4)
    readonly property real idleOrganicValue: root.idleMotionActive ? clamp01(0.50 + root.organicPrimaryValue * 0.22 + root.organicSecondaryValue * 0.16 + root.organicDriftValue * 0.10) : 0
    readonly property real idleBreathValue: root.idleOrganicValue
    readonly property real idlePulseMin: sf.anchorIdlePulseMinOpacity
    readonly property real idlePulseMax: sf.anchorIdlePulseMaxOpacity
    readonly property int idleBreathDurationMs: sf.durationAnchorIdleBreath
    readonly property real lensPulseStrength: sf.anchorIdleLensPulseStrength
    readonly property real orbitalSpeedScale: sf.anchorOrbitalSpeedScale
    readonly property real listeningRippleSpeedScale: sf.anchorListeningRippleSpeedScale
    readonly property real speakingRadianceSpeedScale: sf.anchorSpeakingRadianceSpeedScale
    readonly property real warningPulseLimit: sf.anchorWarningPulseLimit
    readonly property real transitionContinuityFloor: sf.anchorModeTransitionContinuityFloor
    readonly property real stateFeatureAlpha: root.stateTransitionActive
        ? root.transitionContinuityFloor + root.transitionBlendProgress * (1.0 - root.transitionContinuityFloor)
        : 1.0
    readonly property real anchorVisibleFloor: root.visualPresenceFloor
    readonly property real lensVisibleFloor: root.minimumCenterLensOpacity
    readonly property real ringVisibleFloor: root.minimumRingOpacity
    readonly property string resolvedLabel: root.label.length > 0 ? root.label : defaultLabel(root.visualState)
    readonly property string resolvedSublabel: root.sublabel.length > 0 ? root.sublabel : defaultSublabel(root.visualState)
    readonly property string motionProfile: profileForState(root.visualState)
    readonly property real motionSpeedScale: speedScaleForProfile(root.motionProfile)
    readonly property string stateVisualSignature: signatureForState(root.visualState)
    readonly property string stateGeometrySignature: geometryForState(root.visualState)
    readonly property string centerStateSignature: centerSignatureForState(root.visualState)
    readonly property real minimumRingOpacity: visibilityFloor("ring", root.visualState)
    readonly property real minimumCenterLensOpacity: visibilityFloor("center_lens", root.visualState)
    readonly property real minimumBearingTickOpacity: visibilityFloor("bearing_tick", root.visualState)
    readonly property real minimumSignalPointOpacity: visibilityFloor("signal_point", root.visualState)
    readonly property real minimumLabelOpacity: visibilityFloor("label", root.visualState)
    readonly property bool idlePresenceFloorEnabled: true
    readonly property real idleBlobOpacityFloor: sf.anchorIdleBlobOpacityFloor
    readonly property real idleRingOpacityFloor: sf.anchorIdleMinimumRingOpacity
    readonly property real idleCenterGlowFloor: sf.anchorIdleCenterGlowFloor
    readonly property real idleFragmentOpacityFloor: sf.anchorIdleFragmentOpacityFloor
    readonly property real idleActiveAlphaFloor: sf.anchorIdleActiveAlphaFloor
    readonly property string voiceAvailabilityState: resolveVoiceAvailabilityState()
    readonly property bool voiceOfflineDoesNotHideAnchor: !isVoiceOfflineAvailability(root.voiceAvailabilityState)
        || root.rawDerivedVisualState !== "unavailable"
        || root.anchorVisualStateSource !== "voice_availability_state"
    readonly property real finalAnchorOpacityFloor: finalOpacityFloorForState(root.visualState)
    readonly property real finalBlobOpacity: finalVisibilityFloorForKind("blob", root.visualState)
    readonly property real finalRingOpacity: finalVisibilityFloorForKind("ring", root.visualState)
    readonly property real finalCenterGlowOpacity: finalVisibilityFloorForKind("center_glow", root.visualState)
    readonly property real finalSignalPointOpacity: finalVisibilityFloorForKind("signal_point", root.visualState)
    readonly property real finalBearingTickOpacity: finalVisibilityFloorForKind("bearing_tick", root.visualState)
    readonly property bool finalVisibilityFloorApplied: true
    readonly property bool finalAnchorVisible: root.finalBlobOpacity > 0
        && root.finalRingOpacity > 0
        && root.finalSignalPointOpacity > 0
        && root.finalBearingTickOpacity > 0
    readonly property bool idleAnchorVisible: isIdlePresenceState(root.visualState)
        && root.minimumRingOpacity >= root.idleRingOpacityFloor
        && root.minimumCenterLensOpacity >= sf.anchorIdleMinimumCenterLensOpacity
        && root.idleBlobOpacityFloor > 0
        && root.idleCenterGlowFloor > 0
    readonly property real visualPresenceFloor: Math.min(
        root.minimumRingOpacity,
        root.minimumCenterLensOpacity,
        root.minimumBearingTickOpacity,
        root.minimumSignalPointOpacity
    )
    readonly property string anchorVisibilityStatus: root.visualState === "unavailable"
        ? "visible_unavailable_floor"
        : isIdlePresenceState(root.visualState) ? "visible_idle_floor" : "state_visible"
    readonly property bool animationRunning: !root.disabled && root.visualState !== "unavailable"
    readonly property string authoritativeVoiceStateVersion: textValue(voiceValue("authoritativeVoiceStateVersion", ""), "")
    readonly property int authoritativeStateSequence: Math.max(0, Math.round(Number(voiceValue("authoritativeStateSequence", 0))))
    readonly property string authoritativePlaybackStatus: textKey(voiceValue("authoritativePlaybackStatus", voiceValue("activePlaybackStatus", "")))
    readonly property string authoritativePlaybackId: textValue(voiceValue("authoritativePlaybackId", voiceValue("activePlaybackId", "")), "")
    readonly property string voiceVisualSource: textValue(voiceValue("authoritativeStateSource", voiceValue("voice_visual_source", voiceValue("voice_visual_energy_source", "unavailable"))), "unavailable")
    readonly property bool voiceVisualAvailable: root.voiceVisualSource === "pcm_stream_meter"
        && (root.voiceVisualTargetUpdatedAtMs > 0
            || hasVoiceValue("voice_visual_energy")
            || boolValue(voiceValue("authoritativeVoiceVisualActive", voiceValue("voice_visual_active", false)))
            || boolValue(voiceValue("voice_visual_available", false)))
    readonly property bool voiceVisualActive: root.voiceVisualAvailable
        && boolValue(voiceValue("authoritativeVoiceVisualActive", voiceValue("voice_visual_active", false)))
    readonly property real voiceVisualEnergy: clamp01(firstNumber(
        voiceValue("authoritativeVoiceVisualEnergy", undefined),
        voiceValue("voice_visual_energy", undefined),
        0
    ))
    readonly property string voiceVisualPlaybackId: textValue(voiceValue("authoritativePlaybackId", voiceValue("activePlaybackId", voiceValue("voice_visual_playback_id", voiceValue("playback_id", "")))), "")
    readonly property string voicePlaybackStatus: textKey(voiceValue("authoritativePlaybackStatus", voiceValue("activePlaybackStatus", voiceValue("active_playback_status", voiceValue("playback_status", "")))))
    readonly property bool voicePlaybackActive: playbackSupportsSpeaking(root.voicePlaybackStatus)
    readonly property string voiceVisualDisabledReason: textValue(voiceValue("voice_visual_disabled_reason", ""), "")
    readonly property int voiceVisualSampleRateHz: Math.max(0, Math.round(Number(voiceValue("voice_visual_sample_rate_hz", 0))))
    readonly property real voiceVisualLatestAgeMs: Math.max(0, Number(voiceValue("voice_visual_latest_age_ms", 0)))
    readonly property int maxVoiceVisualStaleMs: 800
    readonly property real voiceVisualTargetAgeMs: root.voiceVisualTargetUpdatedAtMs > 0
        ? Math.max(0, (root.visualClockWallTimeMs > 0 ? root.visualClockWallTimeMs : Date.now()) - root.voiceVisualTargetUpdatedAtMs)
        : 999999
    readonly property bool voiceVisualTargetFresh: root.voiceVisualActive
        && root.voiceVisualTargetAgeMs <= root.maxVoiceVisualStaleMs
        && root.voiceVisualLatestAgeMs <= root.maxVoiceVisualStaleMs
    readonly property bool voiceVisualPlaybackHoldActive: root.voiceVisualAvailable
        && root.voicePlaybackActive
        && root.voiceVisualTargetUpdatedAtMs > 0
        && root.voiceVisualTargetAgeMs <= root.maxVoiceVisualStaleMs
    readonly property bool voiceVisualFreshForSpeaking: root.voiceVisualActive
        && (root.voiceVisualTargetUpdatedAtMs <= 0 || root.voiceVisualTargetFresh)
    readonly property bool voiceVisualReleaseRequested: root.voiceVisualAvailable
        && ((!root.voiceVisualActive && !root.voiceVisualPlaybackHoldActive)
            || (root.voiceVisualTargetUpdatedAtMs > 0
                && !root.voiceVisualTargetFresh
                && !root.voiceVisualPlaybackHoldActive))
    readonly property real targetVoiceVisualEnergy: root.voiceVisualTargetFresh ? root.voiceVisualEnergy : 0
    readonly property real finalEnergyCompressionRatio: root.voiceVisualEnergy > 0.001
        ? clamp01(root.finalSpeakingEnergy / Math.max(0.001, root.voiceVisualEnergy))
        : 0
    property double qmlReceivedEnergyTimeMs: 0
    readonly property real qmlReceivedVoiceVisualEnergy: root.voiceVisualEnergy
    readonly property string qmlReceivedVoiceVisualSource: root.voiceVisualSource
    readonly property string qmlReceivedPlaybackId: root.voiceVisualPlaybackId.length > 0
        ? root.voiceVisualPlaybackId
        : root.currentPlaybackId
    readonly property bool qmlVoiceVisualActive: root.voiceVisualActive
    readonly property real qmlEnergySampleAgeMs: root.voiceVisualLatestAgeMs
    readonly property string audioReactiveSource: root.voiceVisualSource === "pcm_stream_meter"
        ? "pcm_stream_meter"
        : textValue(voiceValue("voice_audio_reactive_source", voiceValue("audio_reactive_source", "unavailable")), "unavailable")
    readonly property bool audioReactiveAvailable: root.voiceVisualSource === "pcm_stream_meter"
        ? root.voiceVisualAvailable
        : boolValue(voiceValue("voice_audio_reactive_available", voiceValue("audio_reactive_available", false)))
    readonly property string currentPlaybackId: textValue(
        voiceValue("authoritativePlaybackId", voiceValue("activePlaybackId", voiceValue("playback_id", voiceValue("active_playback_stream_id", voiceValue("active_playback_id", ""))))),
        ""
    )
    readonly property string currentAnchorPlaybackId: root.qmlReceivedPlaybackId.length > 0
        ? root.qmlReceivedPlaybackId
        : root.currentPlaybackId
    property string lastAnchorPlaybackId: ""
    property int anchorPlaybackIdSwitchCount: 0
    property string anchorAcceptedPlaybackId: ""
    property string anchorIgnoredPlaybackId: ""
    property string anchorSpeakingEntryPlaybackId: ""
    property string anchorSpeakingExitPlaybackId: ""
    property string anchorSpeakingEntryReason: ""
    property string anchorSpeakingExitReason: ""
    readonly property string finalSpeakingEnergyPlaybackId: root.currentAnchorPlaybackId
    readonly property string blobDrivePlaybackId: root.currentAnchorPlaybackId
    readonly property string envelopeSyncCalibrationVersion: "Voice-L0.5"
    readonly property bool playbackEnvelopeVisualSyncCalibrationEnabled: boolValue(voiceValue(
        "playback_envelope_sync_enabled",
        hasVoiceValue("envelope_sync_calibration_version")
            || hasVoiceValue("playback_envelope_time_offset_applied_ms")
            || hasVoiceValue("envelope_visual_offset_ms")
            || hasVoiceValue("estimated_output_latency_ms")
    ))
    readonly property bool envelopeSyncDebugShowSync: boolValue(voiceValue("envelope_sync_debug_show_sync", false))
    readonly property bool playbackEnvelopeSupported: boolValue(voiceValue("playback_envelope_supported", false))
    readonly property string playbackEnvelopeSource: textValue(voiceValue("playback_envelope_source", "unavailable"), "unavailable")
    readonly property bool playbackEnvelopeBackendAvailable: root.playbackEnvelopeSupported
        && boolValue(voiceValue("playback_envelope_available", false))
        && root.playbackEnvelopeSource === "playback_pcm"
    readonly property real playbackEnvelopePayloadEnergy: clamp01(firstNumber(
        voiceValue("playback_envelope_energy", undefined),
        voiceValue("latest_voice_energy", undefined),
        0
    ))
    readonly property int playbackEnvelopeSampleRateHz: Math.max(0, Math.round(Number(voiceValue("playback_envelope_sample_rate_hz", 0))))
    readonly property int playbackEnvelopeLatencyMs: Math.round(boundedNumber(
        voiceValue("playback_envelope_latency_ms", voiceValue("estimated_output_latency_ms", 120)),
        0,
        500,
        120
    ))
    readonly property int playbackEnvelopeEstimatedOutputLatencyMs: Math.round(boundedNumber(
        voiceValue("estimated_output_latency_ms", root.playbackEnvelopeLatencyMs),
        0,
        500,
        root.playbackEnvelopeLatencyMs
    ))
    readonly property int envelopeVisualOffsetMs: Math.round(boundedNumber(
        voiceValue("envelope_visual_offset_ms", voiceValue("playback_envelope_visual_offset_ms", 0)),
        -500,
        500,
        0
    ))
    readonly property real playbackEnvelopeSampleAgeMs: Math.max(0, Number(voiceValue("playback_envelope_sample_age_ms", 0)))
    readonly property string playbackEnvelopeWindowMode: textValue(voiceValue("playback_envelope_window_mode", "latest"), "latest")
    readonly property real playbackEnvelopeQueryTimeMs: optionalNumber(voiceValue("playback_envelope_query_time_ms", undefined))
    readonly property real playbackEnvelopeLatestTimeMs: optionalNumber(voiceValue("playback_envelope_latest_time_ms", voiceValue("latest_voice_energy_time_ms", undefined)))
    readonly property var playbackEnvelopeSamplesRecent: voiceValue("playback_envelope_samples_recent", [])
    readonly property var envelopeTimelinePayloadSamples: voiceValue(
        "envelopeTimelineSamples",
        voiceValue("envelope_timeline_samples", [])
    )
    readonly property var envelopeTimelineSamples: root.envelopeTimelinePayloadSamples && root.envelopeTimelinePayloadSamples.length > 0
        ? root.envelopeTimelinePayloadSamples
        : root.playbackEnvelopeSamplesRecent
    readonly property bool envelopeTimelineAvailable: boolValue(voiceValue(
        "envelopeTimelineAvailable",
        voiceValue("envelope_timeline_available", false)
    )) || (root.envelopeTimelineSamples && root.envelopeTimelineSamples.length >= 2)
    readonly property int envelopeTimelineSampleRateHz: Math.max(0, Math.round(Number(voiceValue(
        "envelopeTimelineSampleRateHz",
        voiceValue("envelope_timeline_sample_rate_hz", root.playbackEnvelopeSampleRateHz)
    ))))
    readonly property int envelopeTimelineSampleCount: Math.max(0, Math.round(Number(voiceValue(
        "envelopeTimelineSampleCount",
        voiceValue("envelope_timeline_sample_count", root.envelopeTimelineSamples ? root.envelopeTimelineSamples.length : 0)
    ))))
    readonly property real qmlPlaybackVisualTimeMs: firstFiniteNumber(
        voiceValue("playback_visual_time_ms", undefined),
        voiceValue("playback_clock_ms", undefined),
        root.playbackEnvelopeQueryTimeMs
    )
    readonly property real qmlEnvelopeTimeOffsetAppliedMs: root.playbackEnvelopeVisualSyncCalibrationEnabled
        ? -root.playbackEnvelopeEstimatedOutputLatencyMs - root.envelopeVisualOffsetMs
        : 0
    readonly property real qmlEnvelopeSampleTimeMs: isFinite(root.qmlPlaybackVisualTimeMs)
        ? Math.max(0, root.qmlPlaybackVisualTimeMs + root.qmlEnvelopeTimeOffsetAppliedMs)
        : root.playbackEnvelopeQueryTimeMs
    readonly property string qmlEnvelopeAlignmentMode: root.playbackEnvelopeVisualSyncCalibrationEnabled
        ? "playback_time_minus_output_latency"
        : "playback_time_direct"
    readonly property int playbackEnvelopeSampleCount: Math.max(
        0,
        Math.round(Number(voiceValue(
            "playback_envelope_sample_count",
            root.playbackEnvelopeSamplesRecent ? root.playbackEnvelopeSamplesRecent.length : 0
        )))
    )
    readonly property bool playbackEnvelopeHasSamples: root.playbackEnvelopeSampleCount > 0
    readonly property bool playbackEnvelopeFresh: root.playbackEnvelopeSampleAgeMs <= 500
    readonly property bool playbackEnvelopeHasEnergy: root.playbackEnvelopePayloadEnergy > 0.006
        || root.samplesContainVoiceEnergy(root.playbackEnvelopeSamplesRecent)
    readonly property real qmlEnvelopeSampleFirstTimeMs: sampleWindowTime(root.playbackEnvelopeSamplesRecent, true)
    readonly property real qmlEnvelopeSampleLastTimeMs: sampleWindowTime(root.playbackEnvelopeSamplesRecent, false)
    readonly property real qmlEnvelopeAlignmentErrorMs: envelopeAlignmentErrorMs(
        root.qmlEnvelopeSampleTimeMs,
        root.qmlEnvelopeSampleFirstTimeMs,
        root.qmlEnvelopeSampleLastTimeMs
    )
    readonly property int playbackEnvelopeAlignmentToleranceMs: Math.round(boundedNumber(
        voiceValue("playback_envelope_alignment_tolerance_ms", 260),
        0,
        500,
        260
    ))
    readonly property real playbackEnvelopeAlignmentDeltaMs: optionalNumber(voiceValue(
        "playback_envelope_alignment_delta_ms",
        voiceValue("playback_envelope_alignment_error_ms", root.qmlEnvelopeAlignmentErrorMs)
    ))
    readonly property string playbackEnvelopeAlignmentStatus: textValue(
        voiceValue("playback_envelope_alignment_status", root.localPlaybackEnvelopeAlignmentStatus()),
        root.localPlaybackEnvelopeAlignmentStatus()
    )
    readonly property bool playbackEnvelopeTimebaseAligned: root.localPlaybackEnvelopeTimebaseAligned()
    readonly property string playbackEnvelopeBackendUsableReason: textValue(voiceValue("playback_envelope_usable_reason", ""), "")
    readonly property bool playbackEnvelopeBackendUsableAllowed: boolValue(voiceValue("playback_envelope_usable", true))
        || (root.playbackEnvelopeBackendUsableReason === "playback_envelope_unaligned"
            && root.playbackEnvelopeTimebaseAligned)
    readonly property bool playbackEnvelopeUsable: root.playbackEnvelopeBackendAvailable
        && root.playbackEnvelopeBackendUsableAllowed
        && root.playbackEnvelopeHasSamples
        && root.playbackEnvelopeFresh
        && root.playbackEnvelopeHasEnergy
        && root.playbackEnvelopeTimebaseAligned
    readonly property string playbackEnvelopeUsableReason: root.resolvePlaybackEnvelopeUsableReason()
    readonly property bool playbackEnvelopeStale: root.playbackEnvelopeBackendAvailable && !root.playbackEnvelopeFresh
    readonly property bool playbackEnvelopeAvailable: root.rawSpeakingActive && root.playbackEnvelopeBackendAvailable
    readonly property int envelopeSamplesDropped: Math.max(0, Math.round(Number(voiceValue("playback_envelope_samples_dropped", voiceValue("envelope_samples_dropped", 0)))))
    property string visualizerSourceStrategy: "none"
    property bool visualizerSourceLocked: false
    property string visualizerSourcePlaybackId: ""
    property int visualizerSourceSwitchCount: 0
    property bool envelopeTimelineReadyAtPlaybackStart: false
    property real finalSpeakingEnergyMinDuringSpeaking: 0
    property real finalSpeakingEnergyMaxDuringSpeaking: 0
    readonly property string visualizerSourceCandidate: root.resolveVisualizerSourceCandidate()
    readonly property bool playbackEnvelopeTimelineActive: root.visualSpeakingActive
        && root.visualizerSourceStrategy === "playback_envelope_timeline"
        && root.playbackEnvelopeBackendAvailable
        && (root.playbackEnvelopeHasSamples || root.envelopeTimelineAvailable)
    readonly property bool anchorUsesPlaybackEnvelope: root.playbackEnvelopeTimelineActive && root.envelopeCrossfadeAlpha > 0.04
    readonly property bool proceduralFallbackActive: root.visualSpeakingActive
        && (root.visualizerSourceStrategy === "procedural_speaking"
            || (root.visualizerSourceStrategy === "playback_envelope_timeline" && root.envelopeCrossfadeAlpha < 0.96))
    readonly property string speakingEnergySourceCandidate: root.visualizerSourceStrategy === "pcm_stream_meter"
        ? "pcm_stream_meter"
        : root.playbackEnvelopeUsable
        ? "playback_envelope"
        : root.visualSpeakingActive ? "procedural_fallback" : "none"
    readonly property bool envelopeFallbackActive: root.proceduralFallbackActive
    readonly property string speakingVisualSyncMode: root.visualSpeakingActive
        ? root.speakingEnergySourceLatched
        : "idle"
    readonly property bool envelopeInterpolationActive: root.anchorUsesPlaybackEnvelope
        && ((root.playbackEnvelopeSamplesRecent && root.playbackEnvelopeSamplesRecent.length >= 2)
            || (root.envelopeTimelineSamples && root.envelopeTimelineSamples.length >= 2))
    readonly property string proceduralFallbackReason: root.resolveProceduralFallbackReason()
    readonly property string envelopeFallbackReason: root.anchorUsesPlaybackEnvelope
        ? ""
        : root.proceduralFallbackReason
    readonly property real envelopeToVisualLatencyEstimateMs: root.anchorUsesPlaybackEnvelope
        ? root.playbackEnvelopeLatencyMs + Math.max(0, root.visualClockDeltaMs)
        : 0
    property real playbackEnvelopeEnergy: 0
    property real playbackEnvelopeVisualDrive: 0
    property real envelopeRecentMin: 0
    property real envelopeRecentMax: 0
    property real envelopeDynamicRange: 0
    property real envelopeDynamicEnergy: 0
    property real envelopeExpandedEnergy: 0
    property real envelopeAdaptiveGain: 1
    property real envelopePeakHold: 0
    property real envelopeTransientEnergy: 0
    property real envelopeDerivativeEnergy: 0
    property real speakingBaseEnergy: 0
    property real proceduralCarrierEnergy: 0
    property string speakingEnergySourceLatched: "none"
    property string speakingEnergySourceLatchPlaybackId: ""
    property int speakingEnergySourceSwitchCount: 0
    property real envelopeCrossfadeAlpha: 0
    property double playbackEnvelopeFirstUsableAtMs: 0
    readonly property bool qmlPlaybackEnvelopeSupported: root.playbackEnvelopeSupported
    readonly property bool qmlPlaybackEnvelopeAvailable: root.playbackEnvelopeAvailable
    readonly property bool qmlPlaybackEnvelopeUsable: root.playbackEnvelopeUsable
    readonly property string qmlPlaybackEnvelopeSource: root.playbackEnvelopeSource
    readonly property real qmlPlaybackEnvelopeEnergy: root.playbackEnvelopeEnergy
    readonly property real qmlPlaybackEnvelopeVisualDrive: root.playbackEnvelopeVisualDrive
    readonly property real qmlEnvelopeExpandedEnergy: root.envelopeExpandedEnergy
    readonly property real qmlEnvelopeDynamicRange: root.envelopeDynamicRange
    readonly property int qmlPlaybackEnvelopeSampleCount: root.playbackEnvelopeSampleCount
    readonly property real qmlPlaybackEnvelopeSampleAgeMs: root.playbackEnvelopeSampleAgeMs
    readonly property bool qmlEnvelopeTimelineAvailable: root.envelopeTimelineAvailable
    readonly property int qmlEnvelopeTimelineSampleCount: root.envelopeTimelineSampleCount
    readonly property real qmlEnvelopeInterpolationIndex: root.envelopeInterpolationActive ? 1 : -1
    readonly property real qmlEnvelopeInterpolationAlpha: root.envelopeInterpolationActive ? root.envelopeCrossfadeAlpha : 0
    readonly property real qmlEnvelopeTimeOffsetMs: root.qmlEnvelopeTimeOffsetAppliedMs
    readonly property real qmlEstimatedOutputLatencyMs: root.playbackEnvelopeEstimatedOutputLatencyMs
    readonly property bool qmlSpeakingVisualActive: root.visualSpeakingActive
    readonly property bool qmlProceduralFallbackActive: root.proceduralFallbackActive
    readonly property real qmlFinalSpeakingEnergy: root.finalSpeakingEnergy
    readonly property string qmlSpeakingEnergySource: root.visualSpeakingActive ? root.speakingEnergySourceLatched : "none"
    readonly property string qmlSpeechEnergySource: root.qmlSpeakingEnergySource
    readonly property real qmlFrameTimeMs: root.visualClockWallTimeMs > 0 ? root.visualClockWallTimeMs : root._lastAnchorFrameTimeMs
    readonly property bool anchorSpeakingVisualActive: root.visualSpeakingActive
    readonly property string anchorCurrentVisualState: root.visualState
    readonly property string anchorMotionMode: root.motionProfile
    readonly property real anchorFrameDeltaMs: root.visualClockDeltaMs
    readonly property int staticFramePaintCount: root.staticFrameLayerEnabled ? anchorFrameLayer.paintCount : 0
    readonly property int staticFrameRequestPaintCount: root.staticFrameLayerEnabled ? anchorFrameLayer.requestPaintCount : 0
    readonly property real staticFrameLastPaintTimeMs: root.staticFrameLayerEnabled ? anchorFrameLayer.lastPaintTimeMs : 0
    readonly property int dynamicCorePaintCount: root.ar3SplitRendererActive
        ? anchorDynamicLayer.paintCount
        : root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.paintCount : 0
    readonly property int dynamicCoreRequestPaintCount: root.ar3SplitRendererActive
        ? anchorDynamicLayer.requestPaintCount
        : root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.requestPaintCount : 0
    readonly property real dynamicCoreLastPaintTimeMs: root.ar3SplitRendererActive
        ? anchorDynamicLayer.lastPaintTimeMs
        : root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.lastPaintTimeMs : 0
    readonly property string qsgRendererPlaybackId: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgRendererPlaybackId : ""
    readonly property string qsgRendererReceivedEnergyForPlaybackId: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgRendererReceivedEnergyForPlaybackId : ""
    readonly property string qsgRendererPaintedPlaybackId: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgRendererPaintedPlaybackId : ""
    readonly property string qsgReflectionParityVersion: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgReflectionParityVersion : ""
    readonly property string qsgReflectionShape: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgReflectionShape : ""
    readonly property bool qsgReflectionRoundedRectDisabled: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgReflectionRoundedRectDisabled : false
    readonly property bool qsgReflectionUsesLegacyGeometry: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgReflectionUsesLegacyGeometry : false
    readonly property bool qsgReflectionAnimated: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgReflectionAnimated : false
    readonly property real qsgReflectionOffsetX: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgReflectionOffsetX : 0
    readonly property real qsgReflectionOffsetY: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgReflectionOffsetY : 0
    readonly property real qsgReflectionOpacity: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgReflectionOpacity : 0
    readonly property real qsgReflectionSoftness: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgReflectionSoftness : 0
    readonly property bool qsgReflectionClipInsideBlob: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgReflectionClipInsideBlob : false
    readonly property string qsgBlobEdgeFeatherVersion: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgBlobEdgeFeatherVersion : ""
    readonly property bool qsgBlobEdgeFeatherEnabled: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgBlobEdgeFeatherEnabled : false
    readonly property bool qsgBlobEdgeFeatherMatchesLegacySoftness: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgBlobEdgeFeatherMatchesLegacySoftness : false
    readonly property real qsgBlobEdgeFeatherOpacity: root.qsgCandidateRendererActive ? anchorLegacyBlobQsgLayer.qsgBlobEdgeFeatherOpacity : 0
    readonly property real blobScaleDrive: root.clamp01(root.finalSpeakingEnergy * 0.82 + root.envelopeExpandedEnergy * 0.18 + root.envelopeTransientEnergy * 0.10)
    readonly property real blobDeformationDrive: root.clamp01(
        (root.visualState === "speaking" ? root.finalSpeakingEnergy * 0.56 + root.envelopeExpandedEnergy * 0.78 + root.envelopeTransientEnergy * 0.34 : 0)
        + (root.idleMotionActive ? root.idleBreathValue * 0.14 : 0)
    )
    readonly property real blobRadiusScale: 1.0 + (
        root.visualState === "speaking"
            ? 0.055 + root.finalSpeakingEnergy * 0.045 + root.envelopeExpandedEnergy * 0.040 + root.envelopeTransientEnergy * 0.028
            : root.visualState === "listening" || root.visualState === "capturing"
                ? 0.07 + root.effectiveAudioLevel * 0.04
                : root.isIdlePresenceState(root.visualState) ? 0.025 : 0.015
    )
    readonly property real radianceDrive: root.clamp01(root.visualState === "speaking"
        ? (root.anchorUsesPlaybackEnvelope
            ? root.finalSpeakingEnergy * 0.44 + root.envelopeExpandedEnergy * 0.82 + root.envelopeTransientEnergy * 0.44
            : root.finalSpeakingEnergy)
        : (root.motionProfile === "listening_wave" ? root.effectiveAudioLevel * 0.42 : root.effectiveIntensity * 0.20))
    readonly property real ringDrive: root.clamp01(0.18 + root.radianceDrive * 0.54 + root.outerMotionSmoothed * 0.18 + root.envelopeExpandedEnergy * 0.18)
    readonly property real visualAmplitudeCompressionRatio: root.voiceVisualEnergy > 0.001
        ? root.clamp01(root.blobScaleDrive / Math.max(0.001, root.voiceVisualEnergy))
        : 0
    readonly property real visualAmplitudeLatencyMs: root.qmlLastPaintTimeMs > 0 && root.finalSpeakingEnergyUpdatedAtMs > 0
        ? Math.max(0, root.qmlLastPaintTimeMs - root.finalSpeakingEnergyUpdatedAtMs)
        : 0
    readonly property real anchorEnergyToPaintLatencyMs: root.qmlLastPaintTimeMs > 0 && root.finalSpeakingEnergyUpdatedAtMs > 0
        ? Math.max(0, root.qmlLastPaintTimeMs - root.finalSpeakingEnergyUpdatedAtMs)
        : 0
    readonly property string anchorStaleEnergyReason: root.voiceVisualActive && !root.voiceVisualTargetFresh && root.voiceVisualTargetUpdatedAtMs > 0
        ? "voice_visual_stale"
        : ""
    readonly property string anchorReleaseReason: root.voiceVisualReleaseRequested && root.finalSpeakingEnergy <= 0.003
        ? "voice_visual_inactive"
        : ""
    readonly property bool envelopeUnavailableFallbackWorks: root.visualSpeakingActive && !root.anchorUsesPlaybackEnvelope ? root.proceduralFallbackActive : true
    readonly property bool finalSpeakingEnergyNonZeroDuringFallback: root.proceduralFallbackActive ? root.finalSpeakingEnergy > 0.0 : false
    readonly property bool rawSpeakingActive: root.rawDerivedVisualState === "speaking"
    readonly property bool speakingLatched: root.latchedVisualState === "speaking" && !root.rawSpeakingActive
    readonly property bool speakingDroppedToIdleDuringActive: false
    readonly property real rawPlaybackLevel: root.rawSpeakingLevel
    readonly property real rawSpeakingLevel: root.rawSpeakingActive ? clamp01(firstNumber(
        root.voiceVisualActive ? root.voiceVisualEnergy : undefined,
        root.speakingLevel,
        voiceValue("voice_center_blob_scale_drive", undefined),
        voiceValue("voice_center_blob_drive", undefined),
        voiceValue("audioDriveLevel", undefined),
        voiceValue("voice_visual_drive_level", undefined),
        root.audioLevel
    )) : 0
    readonly property real effectiveSpeakingLevel: root.finalSpeakingEnergy
    readonly property real effectiveAudioLevel: clamp01(firstNumber(
        root.audioLevel,
        voiceValue("voice_instant_audio_level", undefined),
        voiceValue("voice_fast_audio_level", undefined),
        voiceValue("voice_smoothed_output_level", undefined),
        voiceValue("voice_audio_level", undefined),
        0
    ))
    readonly property real effectiveOuterMotion: clamp01(firstNumber(
        voiceValue("voice_outer_speaking_motion", undefined),
        voiceValue("outer_speaking_motion", undefined),
        root.rawSpeakingLevel,
        0
    ))
    readonly property real effectiveIntensity: clamp01(root.disabled ? 0 : firstNumber(
        root.intensity,
        voiceValue("voice_motion_intensity", undefined),
        root.pulseStrength,
        root.speakingEnvelopeSmoothed,
        root.effectiveAudioLevel,
        0.14
    ))
    readonly property color accentColor: root.colorTransitionSmoothingEnabled
        ? mixColors(sf.stateAccent(root.previousVisualState), sf.stateAccent(root.visualState), root.transitionBlendProgress)
        : sf.stateAccent(root.visualState)
    readonly property color haloColor: root.colorTransitionSmoothingEnabled
        ? mixColors(sf.stateGlow(root.previousVisualState), sf.stateGlow(root.visualState), root.transitionBlendProgress)
        : sf.stateGlow(root.visualState)
    readonly property real labelBandHeight: root.compact ? 0 : Math.min(40, root.height * 0.22)

    implicitWidth: root.compact ? 156 : 214
    implicitHeight: root.compact ? 156 : 244

    StormforgeTokens {
        id: sf
    }

    function clamp01(value) {
        var number = Number(value)
        if (!isFinite(number))
            return 0
        return Math.max(0, Math.min(1, number))
    }

    function boundedNumber(value, minimum, maximum, fallback) {
        var number = Number(value)
        if (!isFinite(number))
            number = Number(fallback)
        if (!isFinite(number))
            number = minimum
        return Math.max(minimum, Math.min(maximum, number))
    }

    function smoothStep(value) {
        var t = clamp01(value)
        return t * t * (3 - 2 * t)
    }

    function mixNumber(fromValue, toValue, amount) {
        var t = clamp01(amount)
        return Number(fromValue) + (Number(toValue) - Number(fromValue)) * t
    }

    function mixColors(fromColor, toColor, amount) {
        var t = clamp01(amount)
        return Qt.rgba(
            mixNumber(fromColor.r, toColor.r, t),
            mixNumber(fromColor.g, toColor.g, t),
            mixNumber(fromColor.b, toColor.b, t),
            mixNumber(fromColor.a, toColor.a, t)
        )
    }

    function organicSine(timeMs, cycleMs, offset) {
        return Math.sin((Number(timeMs) / Math.max(1, Number(cycleMs))) * Math.PI * 2 + offset)
    }

    function stepToward(currentValue, targetValue, maxFall, maxRise) {
        var current = Number(currentValue)
        var target = clamp01(targetValue)
        var delta = target - current
        if (delta > maxRise)
            return clamp01(current + maxRise)
        if (delta < -maxFall)
            return clamp01(current - maxFall)
        return target
    }

    function optionalNumber(value) {
        if (value === undefined || value === null || value === "")
            return NaN
        var number = Number(value)
        return isFinite(number) ? number : NaN
    }

    function firstFiniteNumber() {
        for (var index = 0; index < arguments.length; ++index) {
            var number = optionalNumber(arguments[index])
            if (isFinite(number))
                return number
        }
        return NaN
    }

    function sampleWindowTime(samples, first) {
        if (!samples || samples.length <= 0)
            return NaN
        var found = false
        var result = first ? 999999999 : -999999999
        for (var index = 0; index < samples.length; ++index) {
            var sample = samples[index]
            if (!sample)
                continue
            var sampleTime = optionalNumber(sample.sample_time_ms)
            if (!isFinite(sampleTime))
                sampleTime = optionalNumber(sample.t_ms)
            if (!isFinite(sampleTime))
                continue
            found = true
            result = first ? Math.min(result, sampleTime) : Math.max(result, sampleTime)
        }
        return found ? result : NaN
    }

    function envelopeAlignmentErrorMs(queryTimeMs, firstSampleTimeMs, lastSampleTimeMs) {
        if (!isFinite(queryTimeMs) || !isFinite(firstSampleTimeMs) || !isFinite(lastSampleTimeMs))
            return 999999
        if (firstSampleTimeMs <= queryTimeMs && queryTimeMs <= lastSampleTimeMs)
            return 0
        return Math.min(Math.abs(queryTimeMs - firstSampleTimeMs), Math.abs(queryTimeMs - lastSampleTimeMs))
    }

    function localPlaybackEnvelopeAlignmentStatus() {
        if (!root.playbackEnvelopeBackendAvailable || root.playbackEnvelopeWindowMode !== "playback_time")
            return "not_playback_time"
        if (!isFinite(root.qmlEnvelopeSampleTimeMs) || root.playbackEnvelopeSampleCount < 2)
            return "invalid_query"
        if (root.qmlEnvelopeSampleFirstTimeMs <= root.qmlEnvelopeSampleTimeMs
                && root.qmlEnvelopeSampleTimeMs <= root.qmlEnvelopeSampleLastTimeMs)
            return "aligned"
        if (root.qmlEnvelopeSampleTimeMs > root.qmlEnvelopeSampleLastTimeMs)
            return root.qmlEnvelopeAlignmentErrorMs <= root.playbackEnvelopeAlignmentToleranceMs
                ? "ahead_clamped"
                : "ahead"
        return root.qmlEnvelopeAlignmentErrorMs <= root.playbackEnvelopeAlignmentToleranceMs
            ? "behind_clamped"
            : "behind"
    }

    function localPlaybackEnvelopeTimebaseAligned() {
        if (!root.playbackEnvelopeBackendAvailable || root.playbackEnvelopeWindowMode !== "playback_time")
            return false
        if (!isFinite(root.qmlEnvelopeSampleTimeMs) || root.playbackEnvelopeSampleCount < 2)
            return false
        var localAligned = root.qmlEnvelopeAlignmentErrorMs <= root.playbackEnvelopeAlignmentToleranceMs
        if (hasVoiceValue("playback_envelope_timebase_aligned"))
            return boolValue(voiceValue("playback_envelope_timebase_aligned", false)) || localAligned
        return localAligned
    }

    function resolvePlaybackEnvelopeUsableReason() {
        var explicit = root.playbackEnvelopeBackendUsableReason
        if (root.playbackEnvelopeUsable)
            return explicit.length > 0 && explicit !== "playback_envelope_unaligned"
                ? explicit
                : "playback_envelope_usable"
        if (explicit.length > 0 && explicit !== "playback_envelope_usable")
            return explicit
        if (!root.playbackEnvelopeSupported)
            return "playback_envelope_unsupported"
        if (!root.playbackEnvelopeBackendAvailable)
            return "playback_envelope_unavailable"
        if (!root.playbackEnvelopeHasSamples)
            return "playback_envelope_empty"
        if (!root.playbackEnvelopeFresh)
            return "playback_envelope_stale"
        if (!root.playbackEnvelopeTimebaseAligned)
            return "playback_envelope_unaligned"
        if (!root.playbackEnvelopeHasEnergy)
            return "playback_envelope_zero_energy"
        return "playback_envelope_unusable"
    }

    function samplesContainVoiceEnergy(samples) {
        if (!samples || samples.length <= 0)
            return false
        for (var index = 0; index < samples.length; ++index) {
            var sample = samples[index]
            if (!sample)
                continue
            if (clamp01(firstNumber(sample.smoothed_energy, sample.energy, 0)) > 0.006)
                return true
        }
        return false
    }

    function resolveProceduralFallbackReason() {
        if (root.visualizerSourceStrategy === "pcm_stream_meter")
            return root.voiceVisualDisabledReason
        if (root.anchorUsesPlaybackEnvelope || !root.visualSpeakingActive)
            return ""
        var explicit = textValue(
            voiceValue("playback_envelope_fallback_reason", voiceValue("envelope_fallback_reason", "")),
            ""
        )
        if (explicit.length > 0)
            return explicit
        if (!root.playbackEnvelopeSupported)
            return "playback_envelope_unsupported"
        if (!root.playbackEnvelopeBackendAvailable)
            return "playback_envelope_unavailable"
        if (!root.playbackEnvelopeHasSamples)
            return "playback_envelope_empty"
        if (!root.playbackEnvelopeFresh)
            return "playback_envelope_stale"
        if (!root.playbackEnvelopeTimebaseAligned)
            return "playback_envelope_unaligned"
        if (!root.playbackEnvelopeHasEnergy)
            return "playback_envelope_zero_energy"
        return "playback_envelope_unusable"
    }

    function playbackEnvelopeVisualDriveForEnergy(value) {
        var energy = clamp01(value)
        if (energy <= 0.0)
            return 0.0
        return clamp01(0.080 + Math.sqrt(energy) * 0.460)
    }

    function speakingEnergySourceLabel() {
        if (!root.visualSpeakingActive && !root.speakingLatched)
            return "Stormhelm voice motion"
        if (root.visualizerSourceStrategy === "off")
            return "Stormhelm visualizer off"
        if (root.visualizerSourceStrategy === "constant_test_wave")
            return "Stormhelm test wave"
        if (root.visualizerSourceStrategy === "pcm_stream_meter")
            return "PCM stream meter"
        return "Stormhelm voice motion"
    }

    function resetEnvelopeDynamics() {
        root.envelopeDynamicsHistory = []
        root.envelopeRecentMin = 0
        root.envelopeRecentMax = 0
        root.envelopeDynamicRange = 0
        root.envelopeDynamicEnergy = 0
        root.envelopeExpandedEnergy = 0
        root.envelopeAdaptiveGain = 1
        root.envelopePeakHold = 0
        root.envelopeTransientEnergy = 0
        root.envelopeDerivativeEnergy = 0
        root.speakingBaseEnergy = 0
        root.proceduralCarrierEnergy = 0
        root.envelopeDynamicsLastEnergy = 0
        root.envelopeDynamicsLastSampleMs = 0
    }

    function resetSpeakingEnergySourceLatch() {
        root.speakingEnergySourceLatched = "none"
        root.speakingEnergySourceLatchPlaybackId = ""
        root.speakingEnergySourceSwitchCount = 0
        root.visualizerSourceStrategy = "none"
        root.visualizerSourceLocked = false
        root.visualizerSourcePlaybackId = ""
        root.visualizerSourceSwitchCount = 0
        root.envelopeTimelineReadyAtPlaybackStart = false
        root.envelopeCrossfadeAlpha = 0
        root.playbackEnvelopeFirstUsableAtMs = 0
    }

    function normalizeAnchorVisualizerMode(value) {
        var normalized = textValue(value, "auto").toLowerCase().replace(/[- ]/g, "_")
        if (normalized === "off"
                || normalized === "procedural"
                || normalized === "procedural_test"
                || normalized === "pcm_stream_meter"
                || normalized === "envelope_timeline"
                || normalized === "constant_test_wave")
            return normalized
        return "auto"
    }

    function normalizeAnchorRenderer(value) {
        var normalized = textValue(value, "legacy_blob_reference").toLowerCase().replace(/[- ]/g, "_")
        if (normalized === "legacy_blob" || normalized === "legacy_blob_reference")
            return "legacy_blob_reference"
        if (normalized === "legacy_blob_fast" || normalized === "legacy_blob_fast_candidate")
            return "legacy_blob_fast_candidate"
        if (normalized === "legacy_blob_qsg" || normalized === "legacy_blob_qsg_candidate")
            return "legacy_blob_qsg_candidate"
        if (normalized === "ar3_split")
            return "ar3_split"
        return "legacy_blob_reference"
    }

    function normalizeVisualizerSourceStrategy(value) {
        var normalized = textValue(value, "")
        if (normalized === "pcm_stream_meter")
            return "pcm_stream_meter"
        if (normalized === "playback_envelope" || normalized === "playback_pcm" || normalized === "pcm")
            return "playback_envelope_timeline"
        if (normalized === "procedural" || normalized === "procedural_test" || normalized === "procedural_fallback")
            return "procedural_speaking"
        if (normalized === "playback_envelope_timeline" || normalized === "procedural_speaking" || normalized === "off" || normalized === "constant_test_wave")
            return normalized
        return ""
    }

    function speakingSourceForVisualizerStrategy(strategyName) {
        if (strategyName === "pcm_stream_meter")
            return "pcm_stream_meter"
        if (strategyName === "playback_envelope_timeline")
            return "playback_envelope"
        if (strategyName === "constant_test_wave")
            return "constant_test_wave"
        if (strategyName === "off")
            return "none"
        return "procedural_fallback"
    }

    function resolveVisualizerSourceCandidate() {
        if (root.effectiveAnchorVisualizerMode === "off")
            return "off"
        if (root.effectiveAnchorVisualizerMode === "constant_test_wave")
            return "constant_test_wave"
        if (root.effectiveAnchorVisualizerMode === "procedural" || root.effectiveAnchorVisualizerMode === "procedural_test")
            return "procedural_speaking"
        if (root.effectiveAnchorVisualizerMode === "pcm_stream_meter")
            return "pcm_stream_meter"
        if (root.effectiveAnchorVisualizerMode === "envelope_timeline")
            return "playback_envelope_timeline"
        if (root.voiceVisualAvailable)
            return "pcm_stream_meter"
        var explicit = normalizeVisualizerSourceStrategy(voiceValue(
            "visualizer_source_strategy",
            voiceValue("visualizerSourceStrategy", "")
        ))
        if (explicit.length > 0)
            return explicit
        if (!root.visualSpeakingActive)
            return "none"
        return root.voiceVisualAvailable && root.voiceVisualSource === "pcm_stream_meter"
            ? "pcm_stream_meter"
            : "procedural_speaking"
    }

    function setSpeakingEnergySource(sourceName) {
        var normalized = textValue(sourceName, "none")
        if (normalized.length <= 0)
            normalized = "none"
        if (root.speakingEnergySourceLatched === normalized)
            return
        if (root.speakingEnergySourceLatched.length > 0 && root.speakingEnergySourceLatched !== "none")
            root.speakingEnergySourceSwitchCount += 1
        root.speakingEnergySourceLatched = normalized
    }

    function updateSpeakingEnergySourceLatch(now, frameScale) {
        if (!root.visualSpeakingActive) {
            root.resetSpeakingEnergySourceLatch()
            return
        }
        var playbackId = root.currentPlaybackId.length > 0 ? root.currentPlaybackId : "speaking"
        if (root.speakingEnergySourceLatchPlaybackId !== playbackId) {
            root.resetSpeakingEnergySourceLatch()
            root.speakingEnergySourceLatchPlaybackId = playbackId
            root.visualizerSourcePlaybackId = playbackId
        }
        if (root.anchorVisualizerModeForced
                && root.visualizerSourceLocked
                && root.visualizerSourceCandidate.length > 0
                && root.visualizerSourceStrategy !== root.visualizerSourceCandidate) {
            root.visualizerSourceStrategy = root.visualizerSourceCandidate
            root.speakingEnergySourceLatched = root.speakingSourceForVisualizerStrategy(root.visualizerSourceCandidate)
            root.visualizerSourceSwitchCount = 0
            root.speakingEnergySourceSwitchCount = 0
            root.envelopeTimelineReadyAtPlaybackStart = root.visualizerSourceCandidate === "playback_envelope_timeline"
                && root.playbackEnvelopeTimelineActive
        }
        if (!root.visualizerSourceLocked) {
            var selected = root.visualizerSourceCandidate
            if (selected === "none" || selected.length <= 0)
                selected = "procedural_speaking"
            root.visualizerSourceStrategy = selected
            root.visualizerSourceLocked = true
            root.speakingEnergySourceLatched = root.speakingSourceForVisualizerStrategy(selected)
            root.envelopeTimelineReadyAtPlaybackStart = selected === "playback_envelope_timeline"
                && root.playbackEnvelopeTimelineActive
        }
        if (root.visualizerSourceStrategy === "playback_envelope_timeline" && root.playbackEnvelopeTimelineActive) {
            if (root.playbackEnvelopeFirstUsableAtMs <= 0)
                root.playbackEnvelopeFirstUsableAtMs = now
        }
        var alphaTarget = root.visualizerSourceStrategy === "playback_envelope_timeline" ? 1.0 : 0.0
        root.envelopeCrossfadeAlpha = root.stepToward(
            root.envelopeCrossfadeAlpha,
            alphaTarget,
            0.130 * frameScale,
            0.105 * frameScale
        )
    }

    function updateEnvelopeDynamics(now, energy, frameScale) {
        if (!root.playbackEnvelopeTimelineActive || !root.visualSpeakingActive) {
            root.resetEnvelopeDynamics()
            return
        }
        var current = clamp01(energy)
        var cutoff = now - root.envelopeDynamicsWindowMs
        var history = root.envelopeDynamicsHistory || []
        var nextHistory = []
        var minValue = 1.0
        var maxValue = 0.0
        for (var index = 0; index < history.length; ++index) {
            var entry = history[index]
            if (!entry || Number(entry.t) < cutoff)
                continue
            var entryEnergy = clamp01(entry.e)
            nextHistory.push({"t": Number(entry.t), "e": entryEnergy})
            minValue = Math.min(minValue, entryEnergy)
            maxValue = Math.max(maxValue, entryEnergy)
        }
        if (current > 0.006) {
            nextHistory.push({"t": now, "e": current})
            minValue = Math.min(minValue, current)
            maxValue = Math.max(maxValue, current)
        }
        if (nextHistory.length > 96)
            nextHistory = nextHistory.slice(nextHistory.length - 96)
        root.envelopeDynamicsHistory = nextHistory

        if (nextHistory.length <= 0) {
            root.envelopeRecentMin = 0
            root.envelopeRecentMax = 0
            root.envelopeDynamicRange = 0
            root.envelopeAdaptiveGain = 1
            root.envelopeDynamicEnergy = root.stepToward(root.envelopeDynamicEnergy, 0, 0.080 * frameScale, 0.080 * frameScale)
            root.envelopeExpandedEnergy = root.stepToward(root.envelopeExpandedEnergy, 0, 0.090 * frameScale, 0.080 * frameScale)
            root.envelopeTransientEnergy = root.stepToward(root.envelopeTransientEnergy, 0, 0.070 * frameScale, 0.040 * frameScale)
            root.envelopeDerivativeEnergy = 0
            return
        }

        var range = Math.max(0, maxValue - minValue)
        var rangeActive = range >= 0.012
        var normalized = rangeActive ? clamp01((current - minValue) / Math.max(0.001, range)) : 0
        var adaptiveGain = rangeActive ? Math.max(1.2, Math.min(8.0, 0.32 / Math.max(0.001, range))) : 1.0
        var previousEnergy = root.envelopeDynamicsLastSampleMs > 0 ? root.envelopeDynamicsLastEnergy : current
        var derivative = current - previousEnergy
        var positiveDerivative = Math.max(0, derivative)
        var derivativeEnergy = rangeActive ? clamp01(Math.abs(derivative) * adaptiveGain * 1.35) : 0
        var transientTarget = rangeActive ? clamp01(positiveDerivative * adaptiveGain * 2.0) : 0
        var dynamicTarget = rangeActive ? clamp01((current - minValue) * adaptiveGain) : 0

        root.envelopeRecentMin = minValue
        root.envelopeRecentMax = maxValue
        root.envelopeDynamicRange = range
        root.envelopeAdaptiveGain = adaptiveGain
        root.envelopeDerivativeEnergy = derivativeEnergy
        root.envelopeTransientEnergy = root.stepToward(
            root.envelopeTransientEnergy,
            transientTarget,
            0.055 * frameScale,
            0.180 * frameScale
        )

        var expandedTarget = rangeActive
            ? clamp01(Math.pow(normalized, 0.74) * 0.56 + dynamicTarget * 0.18 + root.envelopeTransientEnergy * 0.22)
            : 0
        root.envelopeDynamicEnergy = root.stepToward(
            root.envelopeDynamicEnergy,
            dynamicTarget,
            0.060 * frameScale,
            0.120 * frameScale
        )
        root.envelopeExpandedEnergy = root.stepToward(
            root.envelopeExpandedEnergy,
            expandedTarget,
            0.075 * frameScale,
            0.140 * frameScale
        )
        root.envelopePeakHold = Math.max(
            root.envelopePeakHold - 0.045 * frameScale,
            root.envelopeExpandedEnergy,
            root.envelopeTransientEnergy
        )
        root.envelopeDynamicsLastEnergy = current
        root.envelopeDynamicsLastSampleMs = now
    }

    function proceduralSpeechEnergyAt(now) {
        if (!root.visualSpeakingActive)
            return 0
        var seconds = Number(now) / 1000.0
        var phase = root.speakingPhase
        var phrase = 0.5 + Math.sin(phase * 2.13 + Math.sin(seconds * 0.73) * 0.46) * 0.5
        var syllable = 0.5 + Math.sin(phase * 4.67 + Math.sin(seconds * 1.11) * 0.62 + 1.40) * 0.5
        var breath = 0.5 + Math.sin(seconds * 0.83 + 0.80) * 0.5
        var flutter = 0.5 + Math.sin(phase * 7.90 + Math.sin(seconds * 1.90) * 0.90 + 2.20) * 0.5
        return clamp01(0.070 + phrase * 0.105 + syllable * 0.060 + breath * 0.035 + flutter * 0.020)
    }

    function constantTestWaveEnergyAt(now) {
        if (!root.visualSpeakingActive)
            return 0
        var seconds = Number(now) / 1000.0
        var primary = 0.5 + Math.sin(seconds * 6.2) * 0.5
        var secondary = 0.5 + Math.sin(seconds * 11.4 + 0.8) * 0.5
        return clamp01(0.18 + primary * 0.20 + secondary * 0.08)
    }

    function samplePlaybackEnvelopeEnergy(now) {
        if (!root.playbackEnvelopeTimelineActive)
            return 0
        var samples = root.envelopeTimelineAvailable && root.envelopeTimelineSamples && root.envelopeTimelineSamples.length > 0
            ? root.envelopeTimelineSamples
            : root.playbackEnvelopeSamplesRecent
        if (!samples || samples.length <= 0)
            return root.playbackEnvelopePayloadEnergy
        var latest = samples[samples.length - 1]
        var latestTime = firstFiniteNumber(latest.sample_time_ms, latest.t_ms)
        if (!isFinite(latestTime))
            return clamp01(firstNumber(latest.smoothed_energy, latest.energy, root.playbackEnvelopePayloadEnergy))
        var targetTime = root.qmlEnvelopeSampleTimeMs
        if (!isFinite(targetTime))
            targetTime = root.playbackEnvelopeQueryTimeMs
        if (!isFinite(targetTime))
            targetTime = latestTime
        targetTime = Math.max(0, targetTime)
        var previous = latest
        for (var index = samples.length - 1; index >= 0; --index) {
            var sample = samples[index]
            var sampleTime = firstFiniteNumber(sample.sample_time_ms, sample.t_ms)
            if (!isFinite(sampleTime))
                continue
            if (sampleTime <= targetTime) {
                previous = sample
                var next = index + 1 < samples.length ? samples[index + 1] : sample
                var previousEnergy = clamp01(firstNumber(previous.smoothed_energy, previous.energy, root.playbackEnvelopePayloadEnergy))
                var nextEnergy = clamp01(firstNumber(next.smoothed_energy, next.energy, previousEnergy))
                var nextTime = firstFiniteNumber(next.sample_time_ms, next.t_ms)
                var span = Math.max(1, isFinite(nextTime) ? nextTime - sampleTime : 1)
                return clamp01(previousEnergy + (nextEnergy - previousEnergy) * clamp01((targetTime - sampleTime) / span))
            }
        }
        var first = samples[0]
        return clamp01(firstNumber(first.smoothed_energy, first.energy, root.playbackEnvelopePayloadEnergy))
    }

    function updateReactiveSpeechEnergy(now, intervalMs, backendSpeakingNow) {
        var frameScale = Math.max(0.5, Math.min(2.4, Number(intervalMs) / 32.0))
        var targetAge = root.reactiveEnvelopeLastUpdateMs > 0 ? now - root.reactiveEnvelopeLastUpdateMs : 999999
        var rawTargetFresh = backendSpeakingNow && targetAge <= 280
        var rawTarget = backendSpeakingNow ? clamp01(root.reactiveLevelTarget) : 0
        var envelopeTarget = rawTargetFresh
            ? rawTarget
            : root.visualSpeakingActive ? root.reactiveEnvelope * 0.88 : 0
        var envelopeRise = (rawTargetFresh ? 0.060 : 0.024) * frameScale
        var envelopeFall = (root.visualSpeakingActive ? (rawTargetFresh ? 0.022 : 0.030) : 0.060) * frameScale
        var nextEnvelope = root.stepToward(root.reactiveEnvelope, envelopeTarget, envelopeFall, envelopeRise)
        root.reactiveEnvelopeVelocity = nextEnvelope - root.reactiveEnvelope
        root.reactiveEnvelope = nextEnvelope
        if (!root.visualSpeakingActive && root.reactiveEnvelope < 0.003)
            root.reactiveEnvelope = 0

        root.proceduralSpeechEnergy = root.proceduralSpeechEnergyAt(now)
        root.updateSpeakingEnergySourceLatch(now, frameScale)
        if (root.effectiveAnchorVisualizerMode === "off") {
            root.playbackEnvelopeEnergy = root.stepToward(root.playbackEnvelopeEnergy, 0, 0.120 * frameScale, 0.120 * frameScale)
            root.playbackEnvelopeVisualDrive = 0
            root.updateEnvelopeDynamics(now, 0, frameScale)
            root.visualSpeechEnergy = 0
            root.finalSpeakingEnergy = root.stepToward(root.finalSpeakingEnergy, 0, 0.090 * frameScale, 0.090 * frameScale)
            if (root.finalSpeakingEnergy < 0.003)
                root.finalSpeakingEnergy = 0
            root.sampleFinalSpeakingEnergyDuringSpeaking()
            return
        }
        if (root.effectiveAnchorVisualizerMode === "constant_test_wave") {
            root.playbackEnvelopeEnergy = 0
            root.playbackEnvelopeVisualDrive = 0
            root.updateEnvelopeDynamics(now, 0, frameScale)
            root.visualSpeechEnergy = root.constantTestWaveEnergyAt(now)
            root.finalSpeakingEnergy = root.stepToward(
                root.finalSpeakingEnergy,
                root.visualSpeechEnergy,
                0.030 * frameScale,
                0.055 * frameScale
            )
            root.sampleFinalSpeakingEnergyDuringSpeaking()
            return
        }
        if (root.visualizerSourceStrategy === "pcm_stream_meter") {
            root.playbackEnvelopeEnergy = 0
            root.playbackEnvelopeVisualDrive = 0
            root.envelopeCrossfadeAlpha = 0
            root.updateEnvelopeDynamics(now, 0, frameScale)
            var meterEnergyTarget = backendSpeakingNow && root.voiceVisualTargetFresh
                ? root.targetVoiceVisualEnergy
                : 0
            root.smoothedVoiceVisualEnergy = root.stepToward(
                root.smoothedVoiceVisualEnergy,
                meterEnergyTarget,
                0.105 * frameScale,
                0.095 * frameScale
            )
            if (!backendSpeakingNow && root.smoothedVoiceVisualEnergy < 0.003)
                root.smoothedVoiceVisualEnergy = 0
            var gainedEnergy = root.smoothedVoiceVisualEnergy * root.finalSpeakingEnergyGain
            root.finalSpeakingEnergyClampReason = ""
            if (gainedEnergy > 1.0)
                root.finalSpeakingEnergyClampReason = "upper_clamp"
            if (root.voiceVisualReleaseRequested && !root.voiceVisualTargetFresh)
                root.finalSpeakingEnergyClampReason = root.finalSpeakingEnergyClampReason.length > 0 ? root.finalSpeakingEnergyClampReason : "voice_visual_release"
            root.visualSpeechEnergy = clamp01(gainedEnergy)
            var meterRise = 0.090 * frameScale
            var meterFall = (backendSpeakingNow ? 0.070 : 0.135) * frameScale
            root.finalSpeakingEnergy = root.stepToward(
                root.finalSpeakingEnergy,
                root.visualSpeechEnergy,
                meterFall,
                meterRise
            )
            if (!backendSpeakingNow && root.finalSpeakingEnergy < 0.003)
                root.finalSpeakingEnergy = 0
            root.sampleFinalSpeakingEnergyDuringSpeaking()
            return
        }
        if (root.effectiveAnchorVisualizerMode === "envelope_timeline" && !root.playbackEnvelopeTimelineActive) {
            root.playbackEnvelopeEnergy = 0
            root.playbackEnvelopeVisualDrive = 0
            root.updateEnvelopeDynamics(now, 0, frameScale)
            root.visualSpeechEnergy = 0
            root.finalSpeakingEnergy = root.stepToward(root.finalSpeakingEnergy, 0, 0.090 * frameScale, 0.090 * frameScale)
            if (root.finalSpeakingEnergy < 0.003)
                root.finalSpeakingEnergy = 0
            root.sampleFinalSpeakingEnergyDuringSpeaking()
            return
        }
        var playbackEnvelopeTarget = root.samplePlaybackEnvelopeEnergy(now)
        var playbackRise = 0.070 * frameScale
        var playbackFall = (root.visualSpeakingActive ? 0.040 : 0.090) * frameScale
        root.playbackEnvelopeEnergy = root.stepToward(
            root.playbackEnvelopeEnergy,
            playbackEnvelopeTarget,
            playbackFall,
            playbackRise
        )
        if (!root.playbackEnvelopeTimelineActive && root.playbackEnvelopeEnergy < 0.003)
            root.playbackEnvelopeEnergy = 0
        root.playbackEnvelopeVisualDrive = root.playbackEnvelopeTimelineActive
            ? root.playbackEnvelopeVisualDriveForEnergy(root.playbackEnvelopeEnergy)
            : 0
        root.updateEnvelopeDynamics(now, playbackEnvelopeTarget, frameScale)
        var rawContribution = clamp01(root.reactiveEnvelope * 0.68)
        var envelopeAlpha = clamp01(root.envelopeCrossfadeAlpha)
        var envelopeContribution = root.playbackEnvelopeTimelineActive ? clamp01(root.playbackEnvelopeVisualDrive * envelopeAlpha) : 0
        var fallbackEnergyTarget = Math.max(root.proceduralSpeechEnergy, rawContribution, 0.045)
        root.proceduralCarrierEnergy = root.visualSpeakingActive
            ? clamp01(root.proceduralSpeechEnergy * (1.0 - envelopeAlpha * 0.78))
            : 0
        root.speakingBaseEnergy = root.anchorUsesPlaybackEnvelope
            ? clamp01(0.135 + root.proceduralCarrierEnergy * 0.50 + envelopeContribution * 0.10)
            : 0
        var envelopeEnergyTarget = clamp01(root.speakingBaseEnergy
            + root.envelopeExpandedEnergy * 0.48
            + root.envelopeTransientEnergy * 0.18
            + envelopeContribution * 0.12)
        var energyTarget = root.visualSpeakingActive
            ? (root.anchorUsesPlaybackEnvelope
                ? root.mixNumber(fallbackEnergyTarget, Math.max(envelopeEnergyTarget, fallbackEnergyTarget), envelopeAlpha)
                : fallbackEnergyTarget)
            : 0
        root.visualSpeechEnergy = clamp01(energyTarget)
        var energyRise = 0.048 * frameScale
        var energyFall = (root.visualSpeakingActive ? 0.022 : 0.070) * frameScale
        root.finalSpeakingEnergy = root.stepToward(root.finalSpeakingEnergy, root.visualSpeechEnergy, energyFall, energyRise)
        if (!root.visualSpeakingActive && root.finalSpeakingEnergy < 0.003)
            root.finalSpeakingEnergy = 0
        root.sampleFinalSpeakingEnergyDuringSpeaking()
    }

    function sampleFinalSpeakingEnergyDuringSpeaking() {
        if (!root.visualSpeakingActive) {
            root.finalSpeakingEnergyMinDuringSpeaking = 0
            root.finalSpeakingEnergyMaxDuringSpeaking = 0
            return
        }
        if (root.finalSpeakingEnergyMaxDuringSpeaking <= 0 && root.finalSpeakingEnergyMinDuringSpeaking <= 0) {
            root.finalSpeakingEnergyMinDuringSpeaking = root.finalSpeakingEnergy
            root.finalSpeakingEnergyMaxDuringSpeaking = root.finalSpeakingEnergy
            return
        }
        root.finalSpeakingEnergyMinDuringSpeaking = Math.min(root.finalSpeakingEnergyMinDuringSpeaking, root.finalSpeakingEnergy)
        root.finalSpeakingEnergyMaxDuringSpeaking = Math.max(root.finalSpeakingEnergyMaxDuringSpeaking, root.finalSpeakingEnergy)
    }

    function firstNumber() {
        for (var index = 0; index < arguments.length; ++index) {
            var value = arguments[index]
            if (value === undefined || value === null || value === "")
                continue
            var number = Number(value)
            if (isFinite(number) && number >= 0)
                return number
        }
        return 0
    }

    function textValue(value, fallback) {
        if (value === undefined || value === null || value === "")
            return fallback === undefined ? "" : String(fallback)
        return String(value)
    }

    function textKey(value) {
        return textValue(value, "").toLowerCase().replace(/-/g, "_")
    }

    function boolValue(value) {
        if (value === true || value === false)
            return value
        var key = textKey(value)
        return key === "1" || key === "true" || key === "yes" || key === "on"
    }

    function numericMapValue(map, key, fallback) {
        if (!map || map[key] === undefined || map[key] === null || map[key] === "")
            return fallback
        var parsed = Number(map[key])
        return isFinite(parsed) ? parsed : fallback
    }

    function isVoiceVisualScalarKey(key) {
        return key === "playback_id"
            || key === "voice_visual_active"
            || key === "voice_visual_available"
            || key === "voice_visual_energy"
            || key === "voice_visual_source"
            || key === "voice_visual_energy_source"
            || key === "voice_visual_playback_id"
            || key === "voice_visual_latest_age_ms"
            || key === "voice_visual_sample_rate_hz"
            || key === "voice_visual_started_at_ms"
            || key === "voice_visual_disabled_reason"
            || key === "payload_time_ms"
            || key === "payload_wall_time_ms"
            || key === "meter_time_ms"
            || key === "meter_wall_time_ms"
    }

    function voiceVisualSourceFor(map) {
        if (!map)
            return ""
        return textValue(
            map["voice_visual_source"] !== undefined && map["voice_visual_source"] !== null
                ? map["voice_visual_source"]
                : map["voice_visual_energy_source"],
            ""
        )
    }

    function shouldPreferVoiceStateVisualValue(key) {
        if (!root.isVoiceVisualScalarKey(key))
            return false
        if (root.voiceVisualState
                && root.voiceVisualState.authoritativeVoiceStateVersion === "AR6")
            return false
        if (!root.voiceState || root.voiceState[key] === undefined || root.voiceState[key] === null)
            return false
        if (!root.voiceVisualState || root.voiceVisualState[key] === undefined || root.voiceVisualState[key] === null)
            return false

        var stateSource = root.voiceVisualSourceFor(root.voiceState)
        if (stateSource !== "pcm_stream_meter")
            return false

        var visualSource = root.voiceVisualSourceFor(root.voiceVisualState)
        var stateActive = boolValue(root.voiceState["voice_visual_active"])
        var visualActive = boolValue(root.voiceVisualState["voice_visual_active"])
        var stateEnergy = root.numericMapValue(root.voiceState, "voice_visual_energy", 0)
        var visualEnergy = root.numericMapValue(root.voiceVisualState, "voice_visual_energy", 0)
        var stateHasSignal = stateActive || stateEnergy > 0.0001 || boolValue(root.voiceState["voice_visual_available"])

        if (visualSource !== "pcm_stream_meter")
            return stateHasSignal
        return stateActive && !visualActive && visualEnergy <= 0.0001
    }

    function voiceValue(key, fallback) {
        if (root.shouldPreferVoiceStateVisualValue(key))
            return root.voiceState[key]
        if (root.voiceVisualState && root.voiceVisualState[key] !== undefined && root.voiceVisualState[key] !== null)
            return root.voiceVisualState[key]
        if (!root.voiceState || root.voiceState[key] === undefined || root.voiceState[key] === null)
            return fallback
        return root.voiceState[key]
    }

    function hasVoiceValue(key) {
        return (!!root.voiceVisualState && root.voiceVisualState[key] !== undefined && root.voiceVisualState[key] !== null)
            || (!!root.voiceState && root.voiceState[key] !== undefined && root.voiceState[key] !== null)
    }

    function hasVoicePayload() {
        return hasVoiceValue("voice_anchor_state")
            || hasVoiceValue("voice_current_phase")
            || hasVoiceValue("active_playback_status")
            || hasVoiceValue("speaking_visual_active")
            || hasVoiceValue("voice_visual_active")
            || hasVoiceValue("voice_visual_energy")
            || hasVoiceValue("active_capture_id")
    }

    function isVoiceOfflineKey(key) {
        return key === "offline"
            || key === "unavailable"
            || key === "disabled"
            || key === "muted"
            || key === "interrupted"
            || key === "voice_offline"
            || key === "voice_unavailable"
            || key === "capture_disabled"
            || key === "capture_unavailable"
            || key === "provider_unavailable"
            || key === "dev_capture_not_allowed"
            || key === "manual_capture_disabled"
            || key === "push_to_talk_capture_disabled"
            || key === "push_to_talk_capture_unavailable"
            || key === "wake_supervised_capture_unavailable"
    }

    function isVoiceOfflineAvailability(stateName) {
        return stateName !== "available" && stateName !== ""
    }

    function resolveVoiceAvailabilityState() {
        var reason = textKey(voiceValue("unavailable_reason", voiceValue("capture_unavailable_reason", "")))
        if (reason.length > 0 && isVoiceOfflineKey(reason))
            return reason
        if (boolValue(voiceValue("voice_available", true)) === false || boolValue(voiceValue("available", true)) === false)
            return reason.length > 0 ? reason : "offline"
        var phase = textKey(voiceValue("voice_current_phase", ""))
        var anchor = textKey(voiceValue("voice_anchor_state", ""))
        if (isVoiceOfflineKey(phase))
            return phase
        if (isVoiceOfflineKey(anchor))
            return anchor
        return "available"
    }

    function normalizeVoiceStateName(value) {
        var key = textKey(value)
        if (key.length <= 0)
            return ""
        if (isVoiceOfflineKey(key))
            return ""
        return normalizeStateName(value)
    }

    function containsAny(text, words) {
        for (var index = 0; index < words.length; ++index) {
            if (text.indexOf(words[index]) >= 0)
                return true
        }
        return false
    }

    function isCanonicalStateName(key) {
        switch (key) {
        case "idle":
        case "ready":
        case "wake_detected":
        case "listening":
        case "capturing":
        case "transcribing":
        case "thinking":
        case "acting":
        case "speaking":
        case "approval_required":
        case "blocked":
        case "failed":
        case "unavailable":
        case "mock_dev":
            return true
        default:
            return false
        }
    }

    function normalizeStateName(value) {
        var key = textKey(value)
        if (key === "")
            return ""
        if (key === "unknown" || key === "none" || key === "null" || key === "inactive")
            return root.normalizedStateFallback
        if (key === "mock" || key === "dev" || key === "development" || key === "development_mode")
            return "mock_dev"
        if (key === "disabled" || key === "offline" || key === "muted" || key === "interrupted" || key === "unavailable")
            return "unavailable"
        if (key === "ghost_ready" || key === "signal_acquired" || key === "signal_acquire" || key === "wake" || key === "wake_ready")
            return "wake_detected"
        if (key === "routing"
                || key === "processing"
                || key === "synthesizing"
                || key === "preparing"
                || key === "preparing_speech"
                || key === "requested"
                || key === "planning"
                || key === "planned"
                || key === "plan_ready"
                || key === "queued"
                || key === "pending"
                || key === "calculating"
                || key === "thinking")
            return "thinking"
        if (key === "executing"
                || key === "execution"
                || key === "running"
                || key === "run"
                || key === "action"
                || key === "acting"
                || key === "in_progress"
                || key === "continuing_task")
            return "acting"
        if (key === "capture" || key === "capture_active")
            return "capturing"
        if (key === "approval"
                || key === "approval_pending"
                || key === "approval_required"
                || key === "confirmation_required"
                || key === "requires_approval"
                || key === "requires_confirmation"
                || key === "permission_required"
                || key === "pending_approval"
                || key === "trust_pending")
            return "approval_required"
        if (key === "warning" || key === "warned" || key === "denied" || key === "held")
            return "blocked"
        if (key === "error" || key === "failure")
            return "failed"
        return isCanonicalStateName(key) ? key : ""
    }

    function isIdlePresenceState(stateName) {
        return stateName === "idle" || stateName === "ready" || stateName === "wake_detected"
    }

    function stateInList(stateName, states) {
        for (var index = 0; index < states.length; ++index) {
            if (stateName === states[index])
                return true
        }
        return false
    }

    function anyStateInList(states, targets) {
        for (var index = 0; index < states.length; ++index) {
            if (stateInList(states[index], targets))
                return true
        }
        return false
    }

    function firstStateInList(states, targets) {
        for (var index = 0; index < states.length; ++index) {
            if (stateInList(states[index], targets))
                return states[index]
        }
        return ""
    }

    function isPromptVisualState(stateName) {
        return stateName === "unavailable"
            || stateName === "failed"
            || stateName === "blocked"
            || stateName === "approval_required"
            || stateName === "speaking"
            || stateName === "listening"
            || stateName === "capturing"
            || stateName === "acting"
    }

    function isUrgentVisualState(stateName) {
        return stateName === "unavailable"
            || stateName === "failed"
            || stateName === "blocked"
            || stateName === "approval_required"
    }

    function isLatchedActiveState(stateName) {
        return stateName === "speaking"
            || stateName === "thinking"
            || stateName === "acting"
            || stateName === "listening"
            || stateName === "capturing"
            || stateName === "transcribing"
            || stateName === "wake_detected"
    }

    function dwellMsForState(stateName) {
        switch (stateName) {
        case "speaking":
            return root.speakingLatchMs
        case "thinking":
            return root.thinkingLatchMs
        case "acting":
            return root.actingLatchMs
        case "listening":
        case "capturing":
        case "transcribing":
            return root.captureLatchMs
        case "wake_detected":
            return root.wakeLatchMs
        case "approval_required":
        case "blocked":
        case "failed":
        case "unavailable":
            return root.promptLatchMs
        default:
            return root.stateMinimumDwellMs
        }
    }

    function visibilityFloor(kind, stateName) {
        if (stateName === "unavailable") {
            switch (kind) {
            case "ring":
                return sf.anchorUnavailableMinimumRingOpacity
            case "center_lens":
                return sf.anchorUnavailableMinimumCenterLensOpacity
            case "bearing_tick":
                return sf.anchorUnavailableMinimumBearingTickOpacity
            case "signal_point":
                return sf.anchorUnavailableMinimumSignalPointOpacity
            case "label":
                return sf.anchorUnavailableMinimumLabelOpacity
            default:
                return sf.anchorUnavailableMinimumRingOpacity
            }
        }
        if (isIdlePresenceState(stateName)) {
            switch (kind) {
            case "ring":
                return sf.anchorIdleMinimumRingOpacity
            case "center_lens":
                return sf.anchorIdleMinimumCenterLensOpacity
            case "bearing_tick":
                return sf.anchorIdleMinimumBearingTickOpacity
            case "signal_point":
                return sf.anchorIdleMinimumSignalPointOpacity
            case "label":
                return sf.anchorIdleMinimumLabelOpacity
            default:
                return sf.anchorIdleMinimumRingOpacity
            }
        }
        return 0
    }

    function finalOpacityFloorForState(stateName) {
        if (stateName === "unavailable")
            return sf.anchorUnavailableActiveAlphaFloor
        if (stateName === "mock_dev")
            return 0.58
        if (isIdlePresenceState(stateName))
            return root.idleActiveAlphaFloor
        return 0.78
    }

    function finalVisibilityFloorForKind(kind, stateName) {
        if (stateName === "unavailable") {
            switch (kind) {
            case "blob":
                return sf.anchorUnavailableFinalBlobOpacityFloor
            case "center_glow":
                return sf.anchorUnavailableCenterGlowFloor
            case "ring":
                return sf.anchorUnavailableMinimumRingOpacity
            case "signal_point":
                return sf.anchorUnavailableMinimumSignalPointOpacity
            case "bearing_tick":
                return sf.anchorUnavailableMinimumBearingTickOpacity
            case "fragment":
                return sf.anchorUnavailableFragmentOpacityFloor
            default:
                return sf.anchorUnavailableMinimumRingOpacity
            }
        }
        if (isIdlePresenceState(stateName)) {
            switch (kind) {
            case "blob":
                return root.idleBlobOpacityFloor
            case "center_glow":
                return root.idleCenterGlowFloor
            case "ring":
                return root.idleRingOpacityFloor
            case "signal_point":
                return sf.anchorIdleMinimumSignalPointOpacity
            case "bearing_tick":
                return sf.anchorIdleMinimumBearingTickOpacity
            case "fragment":
                return root.idleFragmentOpacityFloor
            default:
                return root.idleRingOpacityFloor
            }
        }
        switch (kind) {
        case "blob":
            return sf.anchorFinalMinimumBlobOpacity
        case "center_glow":
            return sf.anchorFinalMinimumCenterGlowOpacity
        case "ring":
            return sf.anchorFinalMinimumRingOpacity
        case "signal_point":
            return sf.anchorFinalMinimumSignalPointOpacity
        case "bearing_tick":
            return sf.anchorFinalMinimumBearingTickOpacity
        case "fragment":
            return sf.anchorFinalMinimumFragmentOpacity
        default:
            return sf.anchorFinalMinimumRingOpacity
        }
    }

    function playbackSupportsSpeaking(playbackKey) {
        return playbackKey === "started" || playbackKey === "playing" || playbackKey === "active" || playbackKey === "prerolling"
    }

    function resolveState() {
        if (root.disabled)
            return "unavailable"

        var explicit = normalizeStateName(root.state)
        var phase = normalizeVoiceStateName(voiceValue("voice_current_phase", ""))
        var anchor = normalizeVoiceStateName(voiceValue("voice_anchor_state", ""))
        var playback = textKey(voiceValue("active_playback_status", ""))
        var assistant = normalizeStateName(root.assistantState)
        var states = [explicit, phase, anchor, assistant]
        var voiceBacked = hasVoicePayload()
        var voiceVisualSpeaking = root.voiceVisualFreshForSpeaking
            || root.voiceVisualPlaybackHoldActive
        var legacySpeakingAllowed = !root.voiceVisualReleaseRequested
        var speakingRequested = voiceVisualSpeaking
            || (legacySpeakingAllowed
                && (anyStateInList(states, ["speaking"])
                    || playback === "playback_active"
                    || playback === "playing"
                    || playback === "active"))
        var speakingSupported = voiceVisualSpeaking
            || (legacySpeakingAllowed
                && (boolValue(voiceValue("speaking_visual_active", false))
                    || playbackSupportsSpeaking(playback)))

        if (anyStateInList([explicit, assistant], ["unavailable"]))
            return "unavailable"
        if (anyStateInList(states, ["failed"]))
            return "failed"
        if (anyStateInList(states, ["approval_required"]))
            return "approval_required"
        if (root.warning || anyStateInList(states, ["blocked"]))
            return "blocked"
        if (speakingRequested) {
            if (!voiceBacked || speakingSupported)
                return "speaking"
            if (anyStateInList(states, ["thinking"]))
                return "thinking"
        }
        var priorityState = firstStateInList(states, [
            "acting",
            "thinking",
            "transcribing",
            "capturing",
            "listening",
            "wake_detected",
            "ready",
            "mock_dev",
            "idle"
        ])
        if (priorityState === "acting")
            return "acting"
        if (priorityState === "thinking")
            return "thinking"
        if (priorityState === "transcribing")
            return "transcribing"
        if (priorityState === "capturing" || boolValue(voiceValue("capture_started", false)) || textValue(voiceValue("active_capture_id", ""), "").length > 0)
            return "capturing"
        if (priorityState === "listening")
            return "listening"
        if (priorityState === "wake_detected")
            return "wake_detected"
        if (priorityState === "ready")
            return "ready"
        if (priorityState === "mock_dev")
            return "mock_dev"
        return root.normalizedStateFallback
    }

    function resolveStateSource() {
        var hinted = textKey(root.stateSourceHint)
        if (hinted.length > 0)
            return hinted
        if (root.disabled)
            return "disabled_or_unavailable_state"

        var explicit = normalizeStateName(root.state)
        var phase = normalizeVoiceStateName(voiceValue("voice_current_phase", ""))
        var anchor = normalizeVoiceStateName(voiceValue("voice_anchor_state", ""))
        var playback = textKey(voiceValue("active_playback_status", ""))
        var assistant = normalizeStateName(root.assistantState)
        var states = [explicit, phase, anchor, assistant]

        if (anyStateInList([explicit, assistant], ["unavailable"]))
            return "disabled_or_unavailable_state"
        if (anyStateInList(states, ["failed"]))
            return "failed_error_state"
        if (anyStateInList(states, ["blocked"]))
            return "warning_blocked_state"
        if (anyStateInList(states, ["approval_required"]))
            return "approval_trust_state"
        if (root.voiceVisualActive)
            return "voice_visual_pcm_stream_meter"
        if (anyStateInList([phase, anchor], ["speaking"]) || playbackSupportsSpeaking(playback))
            return "speaking_playback_state"
        if (anyStateInList([phase, anchor], ["listening", "capturing", "transcribing"]))
            return "voice_capture_state"
        if (explicit.length > 0 && explicit !== root.normalizedStateFallback)
            return "explicit_state"
        if (assistant.length > 0 && assistant !== root.normalizedStateFallback)
            return "route_or_assistant_state"
        if (root.normalizedState === "wake_detected")
            return "wake_state"
        if (root.normalizedState === "ready")
            return "ready_state"
        if (root.normalizedState === "mock_dev")
            return "dev_mock_state"
        return "idle_fallback"
    }

    function defaultLabel(stateName) {
        switch (stateName) {
        case "ready":
        case "idle":
            return "Ready"
        case "wake_detected":
            return "Signal acquired"
        case "listening":
        case "capturing":
            return "Listening"
        case "transcribing":
            return "Transcribing"
        case "thinking":
            return "Thinking"
        case "acting":
            return "Acting"
        case "speaking":
            return "Speaking"
        case "approval_required":
            return "Approval required"
        case "blocked":
            return "Warning"
        case "failed":
            return "Failed"
        case "unavailable":
            return "Unavailable"
        case "mock_dev":
            return "Dev mode"
        default:
            return "Ready"
        }
    }

    function defaultSublabel(stateName) {
        if (isIdlePresenceState(stateName) && isVoiceOfflineAvailability(root.voiceAvailabilityState))
            return "Voice offline"
        switch (stateName) {
        case "speaking":
            return root.speakingEnergySourceLabel()
        case "approval_required":
            return "Operator confirmation"
        case "blocked":
            return "Held at boundary"
        case "failed":
            return "Needs diagnosis"
        case "unavailable":
            return "Stormhelm unavailable"
        case "mock_dev":
            return "Development signal"
        default:
            return ""
        }
    }

    function profileForState(stateName) {
        switch (stateName) {
        case "unavailable":
            return "muted"
        case "wake_detected":
        case "ready":
            return "alignment"
        case "listening":
        case "capturing":
        case "transcribing":
            return "listening_wave"
        case "thinking":
            return "orbit"
        case "acting":
            return "directional_trace"
        case "speaking":
            return "radiating"
        case "approval_required":
            return "approval_halo"
        case "blocked":
            return "warning_halo"
        case "failed":
            return "failure"
        case "mock_dev":
            return "dev_trace"
        default:
            return "breathing"
        }
    }

    function speedScaleForProfile(profileName) {
        switch (profileName) {
        case "muted":
            return 0
        case "breathing":
            return 0.30
        case "alignment":
            return 0.46
        case "listening_wave":
            return sf.anchorListeningRippleSpeedScale
        case "orbit":
            return sf.anchorOrbitalSpeedScale
        case "directional_trace":
            return 0.54
        case "radiating":
            return sf.anchorSpeakingRadianceSpeedScale + root.finalSpeakingEnergy * 0.50
        case "approval_halo":
        case "warning_halo":
            return 0.34
        case "failure":
            return 0.24
        case "dev_trace":
            return 0.44
        default:
            return 0.32
        }
    }

    function signatureForState(stateName) {
        switch (stateName) {
        case "unavailable":
            return "offline_muted"
        case "wake_detected":
        case "ready":
            return "bearing_acquired"
        case "listening":
        case "capturing":
        case "transcribing":
            return "receive_wave"
        case "thinking":
            return "orbital_bearing"
        case "acting":
            return "bearing_trace"
        case "speaking":
            return "playback_radiance"
        case "approval_required":
            return "approval_bezel"
        case "blocked":
            return "warning_bezel"
        case "failed":
            return "failure_bezel"
        case "mock_dev":
            return "development_trace"
        default:
            return "powered_watch"
        }
    }

    function geometryForState(stateName) {
        switch (stateName) {
        case "unavailable":
            return "dimmed_lens"
        case "wake_detected":
        case "ready":
            return "aligned_heading_crown"
        case "listening":
        case "capturing":
            return "open_receive_aperture"
        case "transcribing":
            return "segmented_processing_aperture"
        case "thinking":
            return "internal_orbit_aperture"
        case "acting":
            return "directional_helm_trace"
        case "speaking":
            return "response_aperture_radiance"
        case "approval_required":
            return "brass_clamp_bezel"
        case "blocked":
            return "amber_boundary_clamp"
        case "failed":
            return "diagnostic_break_segment"
        case "mock_dev":
            return "synthetic_trace_aperture"
        default:
            return "closed_watch_crown"
        }
    }

    function centerSignatureForState(stateName) {
        switch (stateName) {
        case "unavailable":
            return "nearly_dark_lens"
        case "wake_detected":
        case "ready":
            return "brightened_signal_pearl"
        case "listening":
        case "capturing":
            return "receptive_organic_core"
        case "transcribing":
            return "segmented_processing_blob"
        case "thinking":
            return "slow_internal_blob"
        case "acting":
            return "bearing_directed_blob"
        case "speaking":
            return "radiant_voice_blob"
        case "approval_required":
            return "brass_bound_blob"
        case "blocked":
            return "amber_bound_blob"
        case "failed":
            return "diagnostic_blob_break"
        case "mock_dev":
            return "synthetic_violet_blob"
        default:
            return "calm_organic_core"
        }
    }

    function colorString(colorValue, alphaValue) {
        return "rgba("
            + Math.round(colorValue.r * 255) + ","
            + Math.round(colorValue.g * 255) + ","
            + Math.round(colorValue.b * 255) + ","
            + Math.max(0, Math.min(1, alphaValue)) + ")"
    }

    function requestAnchorPaint() {
        if (!root.visible)
            return
        root.qmlAnchorRequestPaintCount += 1
        root.anchorPaintPending = true
        if (root.sharedVisualClockActive)
            return
        if (!paintCoalesceTimer.running)
            paintCoalesceTimer.start()
    }

    function flushAnchorPaint() {
        if (!root.anchorPaintPending || !root.visible)
            return
        root.anchorPaintPending = false
        if (root.renderLoopDiagnosticsEnabled)
            root._anchorRequestPaintWindowCount += 1
        if (root.qsgCandidateRendererActive)
            anchorLegacyBlobQsgLayer.requestDynamicPaint()
        else if (root.ar3SplitRendererActive)
            anchorDynamicLayer.requestDynamicPaint()
        else
            anchorCanvas.requestPaint()
    }

    function requestStaticFramePaint() {
        if (!root.visible)
            return
        if (root.staticFrameLayerEnabled)
            anchorFrameLayer.requestFramePaint()
    }

    function requestAllAnchorLayersPaint() {
        root.requestStaticFramePaint()
        root.requestAnchorPaint()
    }

    function noteAnchorDynamicPaint(now) {
        root.qmlAnchorPaintCount += 1
        root.qmlLastPaintTimeMs = now
        if (root.renderLoopDiagnosticsEnabled)
            root._anchorPaintWindowCount += 1
    }

    function sampleRenderLoopDiagnostics(now) {
        if (!root.renderLoopDiagnosticsEnabled)
            return
        if (root._renderDiagnosticLastSampleMs <= 0) {
            root._renderDiagnosticLastSampleMs = now
            return
        }
        var elapsed = now - root._renderDiagnosticLastSampleMs
        if (elapsed < 1000)
            return
        var scale = 1000.0 / Math.max(1, elapsed)
        root.anchorPaintCountPerSecond = Math.round(root._anchorPaintWindowCount * scale)
        root.anchorRequestPaintCountPerSecond = Math.round(root._anchorRequestPaintWindowCount * scale)
        root.speakingUpdateCountPerSecond = Math.round(root._speakingUpdateWindowCount * scale)
        root.speakingEnvelopeUpdateCountPerSecond = Math.round(root._speakingEnvelopeUpdateWindowCount * scale)
        root._anchorPaintWindowCount = 0
        root._anchorRequestPaintWindowCount = 0
        root._speakingUpdateWindowCount = 0
        root._speakingEnvelopeUpdateWindowCount = 0
        root._renderDiagnosticLastSampleMs = now
    }

    function commitVisualState(stateName, immediate) {
        var target = normalizeStateName(stateName)
        if (target === "")
            target = root.normalizedStateFallback
        if (root.visualState === target) {
            root.pendingVisualState = ""
            if (root.lastVisualStateChangeMs <= 0)
                root.lastVisualStateChangeMs = Date.now()
            return
        }

        root.previousVisualState = root.visualState.length > 0 ? root.visualState : target
        root.visualState = target
        root.pendingVisualState = ""
        root.visualStateChangeSerial += 1
        root.lastVisualStateChangeMs = Date.now()

        transitionAnimation.stop()
        if (immediate) {
            root.transitionProgress = 1.0
            root.stateTransitionActive = false
        } else {
            root.transitionProgress = 0.0
            root.stateTransitionActive = true
            transitionAnimation.start()
        }
        root.requestAllAnchorLayersPaint()
    }

    function scheduleVisualState(stateName) {
        var target = normalizeStateName(stateName)
        if (target === "")
            target = root.normalizedStateFallback
        if (root.visualState === target) {
            root.pendingVisualState = ""
            stateHoldTimer.stop()
            return
        }

        var now = Date.now()
        var pcmReleaseRequested = (root.visualizerSourceStrategy === "pcm_stream_meter"
                || root.voiceVisualSource === "pcm_stream_meter")
            && root.voiceVisualReleaseRequested
            && target !== "speaking"
        if (pcmReleaseRequested && root.visualState === "speaking") {
            root.lastBackendSpeakingMs = 0
            stateHoldTimer.stop()
            commitVisualState(target, false)
            return
        }
        if (root.visualState === "speaking"
                && target !== "failed"
                && target !== "blocked"
                && target !== "approval_required"
                && target !== "unavailable"
                && now - root.lastBackendSpeakingMs < root.speakingGraceMs) {
            root.pendingVisualState = target
            stateHoldTimer.interval = Math.max(20, root.speakingGraceMs - (now - root.lastBackendSpeakingMs))
            stateHoldTimer.restart()
            return
        }
        var elapsed = root.lastVisualStateChangeMs <= 0 ? root.stateMinimumDwellMs : now - root.lastVisualStateChangeMs
        if (isPromptVisualState(target) || elapsed >= root.stateMinimumDwellMs) {
            stateHoldTimer.stop()
            commitVisualState(target, false)
            return
        }

        root.pendingVisualState = target
        stateHoldTimer.interval = Math.max(20, root.stateMinimumDwellMs - elapsed)
        stateHoldTimer.restart()
    }

    function commitLatchedVisualState(stateName, reason, now) {
        var target = normalizeStateName(stateName)
        if (target === "")
            target = root.normalizedStateFallback
        if (!now)
            now = Date.now()

        if (target !== root.latchedVisualState)
            root.latchedVisualState = target
        root.stateLatchReason = reason
        if (!isIdlePresenceState(target)) {
            root.lastNonIdleVisualState = target
            root.lastNonIdleStateChangedAt = now
            root.stateDwellUntil = now + dwellMsForState(target)
        } else {
            root.lastNonIdleVisualState = ""
            root.stateDwellUntil = 0
        }
    }

    function voiceVisualReleaseState() {
        var raw = normalizeStateName(root.rawDerivedVisualState)
        if (raw === "" || raw === "speaking")
            return root.normalizedStateFallback
        return raw
    }

    function releaseVoiceVisualSpeakingState(now) {
        var target = root.voiceVisualReleaseState()
        root.lastBackendSpeakingMs = 0
        root.speakingOnsetGuardActive = false
        root.visualSpeakingActive = false
        if (root.latchedVisualState === "speaking")
            root.commitLatchedVisualState(target, "voice_visual_release", now)
        stateHoldTimer.stop()
        root.pendingVisualState = ""
        if (root.visualState === "speaking")
            root.commitVisualState(target, false)
        else
            root.scheduleVisualState(target)
    }

    function holdVoiceVisualSpeakingState(now) {
        if (!root.visualSpeakingActive || root.voiceVisualReleaseRequested)
            return
        if (isUrgentVisualState(root.rawDerivedVisualState)
                || isUrgentVisualState(root.latchedVisualState)
                || isUrgentVisualState(root.visualState))
            return
        if (!now)
            now = Date.now()
        root.lastBackendSpeakingMs = now
        if (root.latchedVisualState !== "speaking")
            root.commitLatchedVisualState("speaking", "voice_visual_active_hold", now)
        if (root.visualState !== "speaking")
            root.scheduleVisualState("speaking")
    }

    function updateVisualStateLatch(rawStateName, immediate) {
        var now = Date.now()
        var raw = normalizeStateName(rawStateName)
        if (raw === "")
            raw = root.normalizedStateFallback

        if (isUrgentVisualState(raw)) {
            commitLatchedVisualState(raw, "prompt_source", now)
            return
        }

        if (isLatchedActiveState(raw)) {
            commitLatchedVisualState(raw, raw === "speaking" ? "speaking_source" : "active_source", now)
            return
        }

        if (!immediate
                && isLatchedActiveState(root.latchedVisualState)
                && now < root.stateDwellUntil) {
            if (root.latchedVisualState === "speaking"
                    && root.voiceVisualReleaseRequested
                    && raw !== "speaking") {
                commitLatchedVisualState(raw, "voice_visual_release", now)
                return
            }
            root.stateLatchReason = "micro_flicker_hold"
            return
        }

        commitLatchedVisualState(raw, raw === "ready" ? "ready_source" : "idle_fallback", now)
    }

    function refreshStateLatch(now) {
        var raw = normalizeStateName(root.rawDerivedVisualState)
        if (raw === "")
            raw = root.normalizedStateFallback
        if (isUrgentVisualState(raw) || isLatchedActiveState(raw))
            return
        if (isLatchedActiveState(root.latchedVisualState)
                && root.stateDwellUntil > 0
                && now >= root.stateDwellUntil) {
            commitLatchedVisualState(raw, raw === "ready" ? "ready_source" : "idle_fallback", now)
        }
    }

    function markVoiceVisualTargetUpdate(activeNow) {
        var now = Date.now()
        root.qmlReceivedEnergyTimeMs = now
        root.voiceVisualTargetUpdatedAtMs = now
        if (activeNow) {
            if (root.voiceVisualFirstTrueAtMs <= 0)
                root.voiceVisualFirstTrueAtMs = now
            if (root.qmlFirstVoiceVisualTrueAtMs <= 0)
                root.qmlFirstVoiceVisualTrueAtMs = now
            if (root.speakingAttackStartedMs <= 0)
                root.speakingAttackStartedMs = now
            root.lastBackendSpeakingMs = now
            root.updateVisualStateLatch("speaking", true)
            root.scheduleVisualState("speaking")
            root.visualSpeakingActive = true
        } else {
            if (root.voiceVisualPlaybackHoldActive) {
                root.lastBackendSpeakingMs = now
                root.updateVisualStateLatch("speaking", true)
                root.scheduleVisualState("speaking")
                root.visualSpeakingActive = true
            } else {
                root.releaseVoiceVisualSpeakingState(now)
            }
        }
    }

    property real phase: 0
    property real orbit: 0
    property real wavePhase: 0
    property real organicMotionTimeMs: 0
    property real ringFragmentPhase: 0
    property real speakingPhase: 0
    property real reactiveLevelTarget: 0
    property real reactiveEnvelope: 0
    property real reactiveEnvelopeVelocity: 0
    property double reactiveEnvelopeLastUpdateMs: 0
    property real proceduralSpeechEnergy: 0
    property real visualSpeechEnergy: 0
    property real finalSpeakingEnergy: 0
    property real smoothedVoiceVisualEnergy: 0
    property real finalSpeakingEnergyGain: 0.74
    property string finalSpeakingEnergyClampReason: ""
    property double finalSpeakingEnergyUpdatedAtMs: 0
    property double voiceVisualTargetUpdatedAtMs: 0
    property double voiceVisualFirstTrueAtMs: 0
    property double qmlFirstVoiceVisualTrueAtMs: 0
    property double speakingStateEnteredAtMs: 0
    readonly property real anchorSpeakingStartDelayMs: root.speakingStateEnteredAtMs > 0 && root.qmlFirstVoiceVisualTrueAtMs > 0
        ? Math.max(0, root.speakingStateEnteredAtMs - root.qmlFirstVoiceVisualTrueAtMs)
        : 0
    property double anchorSpeakingEnteredAtMs: 0
    property double anchorSpeakingExitedAtMs: 0
    property var envelopeDynamicsHistory: []
    property real envelopeDynamicsLastEnergy: 0
    property double envelopeDynamicsLastSampleMs: 0
    property int rawLevelUpdateCount: 0
    property double lastRawLevelUpdateMs: 0
    property real speakingEnvelopeSmoothed: 0
    property real outerMotionSmoothed: 0
    property real speakingTargetEnvelope: 0
    property real outerMotionTarget: 0
    property real speakingLatchRemainingMs: 0
    property bool speakingOnsetGuardActive: false
    property bool speakingStartupFlickerSuppressed: false
    property bool speakingDroppedToIdleDuringOnset: false
    property bool speakingRawDropPending: false
    property real lastRawSpeakingLevelSample: -1
    property real lastSpeakingTargetEnvelope: 0
    property real lastOuterMotionTarget: 0
    property double speakingRawDropHoldUntilMs: 0
    property bool visualSpeakingActive: false
    property double lastBackendSpeakingMs: 0
    property double speakingAttackStartedMs: 0
    property string lastSpeakingAudioReactiveSource: ""
    property bool lastSpeakingAudioReactiveAvailable: false
    property bool anchorPaintPending: false
    property int qmlAnchorPaintCount: 0
    property int qmlAnchorRequestPaintCount: 0
    property int localSpeakingFrameTickCount: 0
    property double qmlLastPaintTimeMs: 0
    property double _lastAnchorFrameTimeMs: 0
    property int _anchorPaintWindowCount: 0
    property int _anchorRequestPaintWindowCount: 0
    property int _speakingUpdateWindowCount: 0
    property int _speakingEnvelopeUpdateWindowCount: 0
    property double _renderDiagnosticLastSampleMs: 0

    Timer {
        id: stateHoldTimer
        repeat: false
        interval: root.stateMinimumDwellMs
        onTriggered: {
            if (root.pendingVisualState.length > 0)
                root.commitVisualState(root.pendingVisualState, false)
        }
    }

    Timer {
        id: paintCoalesceTimer
        repeat: false
        interval: root.paintCoalesceIntervalMs
        onTriggered: root.flushAnchorPaint()
    }

    SequentialAnimation {
        id: transitionAnimation
        NumberAnimation {
            target: root
            property: "transitionProgress"
            from: 0.0
            to: 1.0
            duration: root.stateTransitionDurationMs
            easing.type: Easing.InOutQuad
        }
        onStopped: {
            root.transitionProgress = 1.0
            root.stateTransitionActive = false
            root.requestAllAnchorLayersPaint()
        }
    }

    function advanceAnimationFrame(intervalMs, now) {
            root._lastAnchorFrameTimeMs = now
            var stateBoost = root.motionSpeedScale * sf.anchorMotionRestraint
            var seconds = intervalMs / 1000.0
            root.organicMotionTimeMs += intervalMs
            root.ringFragmentPhase += seconds
            root.refreshStateLatch(now)
            var backendSpeakingNow = root.rawSpeakingActive
                && (!root.voiceVisualAvailable
                    || root.voiceVisualFreshForSpeaking
                    || root.voiceVisualPlaybackHoldActive)
            if (!backendSpeakingNow && root.voiceVisualReleaseRequested) {
                root.releaseVoiceVisualSpeakingState(now)
            }
            if (backendSpeakingNow) {
                if (root.speakingAttackStartedMs <= 0
                        || (!root.visualSpeakingActive && root.speakingEnvelopeSmoothed <= 0.006)) {
                    root.speakingAttackStartedMs = now
                }
                root.lastBackendSpeakingMs = now
                root.speakingStartupFlickerSuppressed = false
                root.speakingDroppedToIdleDuringOnset = false
                if (root.audioReactiveAvailable) {
                    root.lastSpeakingAudioReactiveAvailable = true
                    root.lastSpeakingAudioReactiveSource = root.audioReactiveSource
                }
            }
            var releaseRequested = root.voiceVisualReleaseRequested
            var withinSpeakingGrace = !releaseRequested
                && root.lastBackendSpeakingMs > 0
                && now - root.lastBackendSpeakingMs < root.speakingGraceMs
            var onsetAge = root.speakingAttackStartedMs > 0 ? now - root.speakingAttackStartedMs : root.speakingOnsetGuardMs
            var onsetGuard = !releaseRequested
                && root.speakingAttackStartedMs > 0
                && onsetAge < root.speakingOnsetGuardMs
                && (backendSpeakingNow || root.latchedVisualState === "speaking" || root.visualState === "speaking" || withinSpeakingGrace)
            root.speakingOnsetGuardActive = onsetGuard
            root.speakingLatchRemainingMs = Math.max(0, root.stateDwellUntil - now)
            root.visualSpeakingActive = backendSpeakingNow
                || (!releaseRequested && root.latchedVisualState === "speaking")
                || (!releaseRequested && root.visualState === "speaking")
                || withinSpeakingGrace
                || onsetGuard
            root.holdVoiceVisualSpeakingState(now)

            if (backendSpeakingNow) {
                var sampledRawTarget = clamp01(root.rawPlaybackLevel)
                if (Math.abs(sampledRawTarget - root.reactiveLevelTarget) > 0.0005) {
                    root.reactiveLevelTarget = sampledRawTarget
                    root.reactiveEnvelopeLastUpdateMs = now
                    root.lastRawLevelUpdateMs = now
                    root.rawLevelUpdateCount += 1
                }
            }
            root.updateReactiveSpeechEnergy(now, intervalMs, backendSpeakingNow)
            var speakingHold = root.latchedVisualState === "speaking" || withinSpeakingGrace || onsetGuard
            var speakingTarget = root.visualSpeakingActive ? root.finalSpeakingEnergy : speakingHold ? root.speakingEnvelopeSmoothed * 0.84 : 0
            var outerTarget = root.visualSpeakingActive
                ? Math.max(root.finalSpeakingEnergy * 0.78, root.reactiveEnvelope * 0.52)
                : speakingHold ? root.outerMotionSmoothed * 0.80 : 0
            var rawDropSignal = backendSpeakingNow
                && ((root.lastRawSpeakingLevelSample >= 0
                        && root.reactiveLevelTarget < root.lastRawSpeakingLevelSample - 0.010)
                    || root.speakingRawDropPending)
            if (rawDropSignal)
                root.speakingRawDropHoldUntilMs = Math.max(root.speakingRawDropHoldUntilMs, now + root.speakingRawDropHoldMs)
            var rawDropHoldActive = backendSpeakingNow && root.speakingRawDropHoldUntilMs > now
            var rawSpeakingDropped = rawDropSignal || rawDropHoldActive
            if (backendSpeakingNow) {
                var attackProgress = clamp01(onsetAge / Math.max(1, root.speakingAttackMs))
                var attackGate = 0.14 + smoothStep(attackProgress) * 0.86
                var onsetProgress = clamp01(onsetAge / Math.max(1, root.speakingOnsetGuardMs))
                var onsetFloor = onsetGuard ? sf.anchorSpeakingOnsetFloor * (0.72 + smoothStep(attackProgress) * 0.28) : 0
                speakingTarget = Math.max(speakingTarget, onsetFloor)
                speakingTarget = Math.min(speakingTarget, Math.max(onsetFloor, root.finalSpeakingEnergy * attackGate))
                outerTarget = Math.min(outerTarget, Math.max(onsetFloor, root.finalSpeakingEnergy * (0.16 + smoothStep(attackProgress) * 0.84)))
                if (onsetGuard) {
                    var onsetCeiling = sf.anchorSpeakingOnsetSpikeCeiling * (0.58 + smoothStep(onsetProgress) * 0.42)
                    speakingTarget = Math.min(speakingTarget, onsetCeiling)
                    outerTarget = Math.min(outerTarget, onsetCeiling)
                    var maxRise = sf.anchorSpeakingOnsetTargetDeltaLimit
                    speakingTarget = Math.min(speakingTarget, root.lastSpeakingTargetEnvelope + maxRise)
                    outerTarget = Math.min(outerTarget, root.lastOuterMotionTarget + maxRise)
                    if (rawSpeakingDropped) {
                        var heldDropTarget = Math.max(speakingTarget, root.speakingEnvelopeSmoothed * sf.anchorSpeakingOnsetReleaseHold)
                        speakingTarget = Math.min(heldDropTarget, root.speakingEnvelopeSmoothed * 0.995)
                    }
                } else if (rawSpeakingDropped) {
                    speakingTarget = Math.max(speakingTarget, root.speakingEnvelopeSmoothed * 0.76)
                }
            } else if (onsetGuard && speakingHold) {
                root.speakingStartupFlickerSuppressed = true
                speakingTarget = Math.max(speakingTarget, root.speakingEnvelopeSmoothed * sf.anchorSpeakingOnsetReleaseHold)
                outerTarget = Math.max(outerTarget, root.outerMotionSmoothed * sf.anchorSpeakingOnsetReleaseHold)
                root.speakingDroppedToIdleDuringOnset = false
                root.lastRawSpeakingLevelSample = -1
                root.speakingRawDropPending = false
            }
            root.speakingTargetEnvelope = clamp01(speakingTarget)
            root.outerMotionTarget = clamp01(outerTarget)
            var envelopeDuration = backendSpeakingNow ? root.speakingAttackMs : root.speakingReleaseMs
            var effectiveEnvelopeDuration = root.visualSpeakingActive ? envelopeDuration : envelopeDuration * 0.42
            var envelopeStep = Math.min(onsetGuard ? 0.18 : 0.42, intervalMs / Math.max(1, effectiveEnvelopeDuration))
            root.speakingEnvelopeSmoothed += (root.speakingTargetEnvelope - root.speakingEnvelopeSmoothed) * envelopeStep
            root.outerMotionSmoothed += (root.outerMotionTarget - root.outerMotionSmoothed) * envelopeStep
            if (root.speakingEnvelopeSmoothed < 0.003 && speakingTarget <= 0)
                root.speakingEnvelopeSmoothed = 0
            if (root.outerMotionSmoothed < 0.003 && outerTarget <= 0)
                root.outerMotionSmoothed = 0
            if (root.renderLoopDiagnosticsEnabled && (root.visualSpeakingActive || root.speakingEnvelopeSmoothed > 0))
                root._speakingEnvelopeUpdateWindowCount += 1
            if (root.visualSpeakingActive || root.speakingEnvelopeSmoothed > 0)
                root.speakingPhase += seconds * (0.55 + root.finalSpeakingEnergy * 0.32)
            if (root.visualSpeakingActive || root.speakingEnvelopeSmoothed > 0 || root.finalSpeakingEnergy > 0)
                root.localSpeakingFrameTickCount += 1
            if (backendSpeakingNow) {
                root.lastRawSpeakingLevelSample = root.reactiveLevelTarget
                root.speakingRawDropPending = false
                root.lastSpeakingTargetEnvelope = root.speakingTargetEnvelope
                root.lastOuterMotionTarget = root.outerMotionTarget
            } else if (!root.visualSpeakingActive && root.speakingEnvelopeSmoothed <= 0) {
                root.lastRawSpeakingLevelSample = -1
                root.lastSpeakingTargetEnvelope = 0
                root.lastOuterMotionTarget = 0
                root.speakingAttackStartedMs = 0
                root.speakingOnsetGuardActive = false
                root.speakingStartupFlickerSuppressed = false
                root.speakingRawDropPending = false
                root.speakingRawDropHoldUntilMs = 0
            } else {
                root.lastSpeakingTargetEnvelope = root.speakingTargetEnvelope
                root.lastOuterMotionTarget = root.outerMotionTarget
            }

            root.phase += intervalMs / 1000.0 * (root.idleMotionActive ? 0.055 : stateBoost)
            root.orbit += intervalMs / 1000.0 * (0.16 + stateBoost * 0.26 + root.effectiveIntensity * 0.12)
            root.wavePhase += intervalMs / 1000.0 * (
                0.48
                + root.effectiveAudioLevel * sf.anchorListeningRippleSpeedScale
                + root.finalSpeakingEnergy * sf.anchorSpeakingRadianceSpeedScale
            )
            root.sampleRenderLoopDiagnostics(now)
            root.requestAnchorPaint()
            if (root.sharedVisualClockActive)
                root.flushAnchorPaint()
    }

    Timer {
        interval: root.localSpeakingFrameClockActive
            ? root.localSpeakingFrameIntervalMs
            : root.anchorFrameTimerIntervalMs
        repeat: true
        running: root.visible
            && root.animationRunning
            && (!root.sharedVisualClockActive || root.localSpeakingFrameClockActive)
        onTriggered: root.advanceAnimationFrame(interval, Date.now())
    }

    onVisualClockFrameCounterChanged: {
        if (root.sharedVisualClockActive) {
            var frameNow = root.visualClockWallTimeMs > 0 ? root.visualClockWallTimeMs : Date.now()
            var frameDelta = root.visualClockDeltaMs > 0 ? root.visualClockDeltaMs : root.anchorFrameTimerIntervalMs
            root.advanceAnimationFrame(frameDelta, frameNow)
        }
    }

    onRawDerivedVisualStateChanged: {
        root.updateVisualStateLatch(root.rawDerivedVisualState, false)
        requestAllAnchorLayersPaint()
    }

    onNormalizedStateChanged: {
        if (root.normalizedState === "speaking") {
            var now = Date.now()
            if (root.speakingAttackStartedMs <= 0
                    || (!root.visualSpeakingActive && root.speakingEnvelopeSmoothed <= 0.006))
                root.speakingAttackStartedMs = now
            if (root.rawSpeakingActive)
                root.lastBackendSpeakingMs = now
            if (root.rawSpeakingActive && root.audioReactiveAvailable) {
                root.lastSpeakingAudioReactiveAvailable = true
                root.lastSpeakingAudioReactiveSource = root.audioReactiveSource
            }
            root.visualSpeakingActive = true
            root.reactiveLevelTarget = root.rawSpeakingActive ? clamp01(root.rawPlaybackLevel) : root.reactiveLevelTarget
            root.reactiveEnvelopeLastUpdateMs = now
            root.finalSpeakingEnergy = Math.max(root.finalSpeakingEnergy, 0.012)
        }
        scheduleVisualState(root.normalizedState)
        requestAllAnchorLayersPaint()
    }
    onRawSpeakingLevelChanged: {
        var rawLevelNow = root.rawSpeakingActive ? clamp01(root.rawPlaybackLevel) : 0
        var rawUpdateNow = Date.now()
        root.reactiveLevelTarget = rawLevelNow
        root.reactiveEnvelopeLastUpdateMs = rawUpdateNow
        root.lastRawLevelUpdateMs = rawUpdateNow
        root.rawLevelUpdateCount += 1
        if (root.rawSpeakingActive
                && root.lastRawSpeakingLevelSample >= 0
                && root.reactiveLevelTarget < root.lastRawSpeakingLevelSample - 0.010) {
            root.speakingRawDropPending = true
            root.speakingRawDropHoldUntilMs = Math.max(root.speakingRawDropHoldUntilMs, rawUpdateNow + root.speakingRawDropHoldMs)
        }
        if (root.renderLoopDiagnosticsEnabled)
            root._speakingUpdateWindowCount += 1
    }
    function acceptCurrentAnchorPlaybackId() {
        var playbackId = root.currentAnchorPlaybackId
        if (playbackId.length <= 0)
            return
        if (root.lastAnchorPlaybackId.length > 0
                && root.lastAnchorPlaybackId !== playbackId)
            root.anchorPlaybackIdSwitchCount += 1
        root.lastAnchorPlaybackId = playbackId
        root.anchorAcceptedPlaybackId = playbackId
        root.anchorIgnoredPlaybackId = ""
    }
    function speakingEntryReason() {
        if (root.voiceVisualActive)
            return "voice_visual_active"
        if (root.voicePlaybackActive)
            return "playback_active"
        return root.visualState === "speaking" ? "visual_state_speaking" : "visual_state"
    }
    onFinalSpeakingEnergyChanged: {
        root.finalSpeakingEnergyUpdatedAtMs = Date.now()
    }
    onCurrentAnchorPlaybackIdChanged: {
        root.acceptCurrentAnchorPlaybackId()
    }
    onVisualSpeakingActiveChanged: {
        var now = Date.now()
        if (root.visualSpeakingActive) {
            root.acceptCurrentAnchorPlaybackId()
            root.anchorSpeakingEntryPlaybackId = root.currentAnchorPlaybackId
            root.anchorSpeakingEntryReason = root.speakingEntryReason()
            root.anchorSpeakingExitPlaybackId = ""
            root.anchorSpeakingExitReason = ""
            root.anchorSpeakingEnteredAtMs = now
            if (root.speakingStateEnteredAtMs <= 0)
                root.speakingStateEnteredAtMs = now
        } else {
            root.anchorSpeakingExitPlaybackId = root.currentAnchorPlaybackId.length > 0
                ? root.currentAnchorPlaybackId
                : root.anchorSpeakingEntryPlaybackId
            root.anchorSpeakingExitReason = root.anchorReleaseReason.length > 0
                ? root.anchorReleaseReason
                : (!root.voiceVisualActive ? "voice_visual_inactive" : "visual_speaking_inactive")
            root.anchorSpeakingExitedAtMs = now
        }
    }
    onVoiceVisualEnergyChanged: {
        root.markVoiceVisualTargetUpdate(root.voiceVisualActive)
    }
    onVoiceVisualActiveChanged: {
        root.markVoiceVisualTargetUpdate(root.voiceVisualActive)
    }
    onVoiceVisualLatestAgeMsChanged: {
        if ((root.voiceVisualAvailable || root.voiceVisualActive)
                && root.voiceVisualLatestAgeMs <= root.maxVoiceVisualStaleMs)
            root.markVoiceVisualTargetUpdate(root.voiceVisualActive)
        else if (root.voiceVisualTargetUpdatedAtMs > 0
                && root.voiceVisualLatestAgeMs > root.maxVoiceVisualStaleMs
                && !root.voiceVisualPlaybackHoldActive)
            root.releaseVoiceVisualSpeakingState(Date.now())
    }
    onVoiceVisualStateChanged: {
        if ((root.voiceVisualAvailable || root.voiceVisualActive)
                && root.voiceVisualLatestAgeMs <= root.maxVoiceVisualStaleMs)
            root.markVoiceVisualTargetUpdate(root.voiceVisualActive)
    }
    onTransitionProgressChanged: requestAnchorPaint()
    onEffectiveAnchorRendererChanged: requestAllAnchorLayersPaint()
    onWidthChanged: requestAllAnchorLayersPaint()
    onHeightChanged: requestAllAnchorLayersPaint()
    onVisibleChanged: requestAllAnchorLayersPaint()
    Component.onCompleted: {
        root.acceptCurrentAnchorPlaybackId()
        root.updateVisualStateLatch(root.rawDerivedVisualState, true)
        if (root.voiceVisualAvailable || root.voiceVisualActive)
            root.markVoiceVisualTargetUpdate(root.voiceVisualActive)
        if (root.normalizedState === "speaking") {
            var now = Date.now()
            root.speakingAttackStartedMs = now
            if (root.rawSpeakingActive)
                root.lastBackendSpeakingMs = now
            root.visualSpeakingActive = true
            root.reactiveLevelTarget = root.rawSpeakingActive ? clamp01(root.rawPlaybackLevel) : 0
            root.reactiveEnvelope = Math.min(root.reactiveLevelTarget * 0.16, 0.10)
            root.reactiveEnvelopeLastUpdateMs = now
            root.lastRawLevelUpdateMs = now
            root.proceduralSpeechEnergy = root.proceduralSpeechEnergyAt(now)
            root.visualSpeechEnergy = Math.max(root.proceduralSpeechEnergy, root.reactiveEnvelope * 0.84, 0.045)
            root.finalSpeakingEnergy = Math.max(root.finalSpeakingEnergy, Math.min(root.visualSpeechEnergy * 0.42, 0.065))
            root.speakingEnvelopeSmoothed = Math.max(0.012, Math.min(root.finalSpeakingEnergy * 0.70, 0.055))
            root.outerMotionSmoothed = Math.max(0.008, Math.min(root.finalSpeakingEnergy * 0.58, 0.045))
            root.speakingTargetEnvelope = root.speakingEnvelopeSmoothed
            root.outerMotionTarget = root.outerMotionSmoothed
            root.lastSpeakingTargetEnvelope = root.speakingTargetEnvelope
            root.lastOuterMotionTarget = root.outerMotionTarget
            if (root.rawSpeakingActive && root.audioReactiveAvailable) {
                root.lastSpeakingAudioReactiveAvailable = true
                root.lastSpeakingAudioReactiveSource = root.audioReactiveSource
            }
        }
        if (root.visualSpeakingActive && root.anchorSpeakingEntryPlaybackId.length <= 0) {
            root.anchorSpeakingEntryPlaybackId = root.currentAnchorPlaybackId
            root.anchorSpeakingEntryReason = root.speakingEntryReason()
        }
        commitVisualState(root.normalizedState, true)
        requestAllAnchorLayersPaint()
    }

    Item {
        id: anchorFace
        width: Math.max(80, Math.min(root.width, root.height - root.labelBandHeight))
        height: width
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top

        Canvas {
            id: anchorCanvas
            anchors.fill: parent
            visible: root.legacyBlobRendererActive
            antialiasing: true
            renderTarget: Canvas.FramebufferObject
            renderStrategy: Canvas.Threaded

            onPaint: {
                if (!visible)
                    return
                root.qmlAnchorPaintCount += 1
                root.qmlLastPaintTimeMs = Date.now()
                if (root.renderLoopDiagnosticsEnabled)
                    root._anchorPaintWindowCount += 1
                var ctx = getContext("2d")
                if (ctx.reset)
                    ctx.reset()
                ctx.clearRect(0, 0, width, height)
                if (width <= 0 || height <= 0)
                    return

                var cx = width / 2
                var cy = height / 2
                var radius = Math.min(width, height) * 0.44
                var targetState = root.visualState
                var sourceState = root.previousVisualState.length > 0 ? root.previousVisualState : targetState
                var transitionBlend = root.transitionBlendProgress
                var transitioning = root.stateTransitionActive && sourceState !== targetState
                var accent = root.accentColor
                var glow = root.haloColor
                var muted = transitioning
                    ? (transitionBlend >= 0.5 ? targetState === "unavailable" : sourceState === "unavailable")
                    : targetState === "unavailable"

                function activeAlphaForState(stateName) {
                    if (stateName === "unavailable")
                        return root.finalAnchorOpacityFloor
                    if (stateName === "mock_dev")
                        return 0.58
                    if (isIdlePresenceState(stateName))
                        return root.idleActiveAlphaFloor
                    return 0.78
                }

                var activeAlpha = transitioning
                    ? root.mixNumber(activeAlphaForState(sourceState), activeAlphaForState(targetState), transitionBlend)
                    : activeAlphaForState(targetState)
                var breath = Math.sin(root.phase * Math.PI * 0.34)
                var counterBreath = Math.cos(root.phase * Math.PI * 0.22)
                var idleLife = root.idleMotionActive ? root.idlePulseMin + (root.idlePulseMax - root.idlePulseMin) * root.idleBreathValue : 0
                var stateArrival = transitioning ? transitionBlend : 1.0
                var speakLevel = root.finalSpeakingEnergy
                var speakDynamics = root.envelopeExpandedEnergy
                var speakTransient = root.envelopeTransientEnergy
                var speakReactive = root.anchorUsesPlaybackEnvelope
                    ? clamp01(speakLevel * 0.44 + speakDynamics * 0.82 + speakTransient * 0.44)
                    : speakLevel
                var outerSpeakLevel = root.outerMotionSmoothed
                var pulse = root.effectiveIntensity * 0.28 + speakLevel * 0.16 + speakDynamics * 0.20 + speakTransient * 0.12 + root.effectiveAudioLevel * 0.10 + idleLife
                var outerScale = root.idleMotionActive ? 1 : 1 + (muted ? 0 : breath * (0.003 + pulse * 0.005))
                var ringSoftness = Math.max(0.35, Math.min(0.8, root.visualSoftness))
                var depthShift = muted ? 0 : counterBreath * radius * 0.005
                var horizonShift = muted ? 0 : Math.sin(root.orbit * 0.34) * radius * (0.012 + (root.idleMotionActive ? sf.anchorIdleBearingDriftStrength : 0))
                var organicDriftAngle = root.organicMotionTimeMs / Math.max(1, root.idleDriftCycleMs) * Math.PI * 2
                var organicOffsetX = root.idleMotionActive ? root.organicSecondaryValue * radius * 0.0063 : 0
                var organicOffsetY = root.idleMotionActive ? root.organicDriftValue * radius * 0.0051 : 0

                function finalAlpha(alpha, minimumFinalAlpha) {
                    return Math.max(alpha * activeAlpha, minimumFinalAlpha || 0)
                }

                function circle(radiusValue, lineWidth, alpha, colorValue, minimumFinalAlpha) {
                    ctx.beginPath()
                    ctx.arc(cx, cy, radiusValue, 0, Math.PI * 2)
                    ctx.lineWidth = lineWidth
                    ctx.strokeStyle = root.colorString(colorValue || accent, finalAlpha(alpha, minimumFinalAlpha))
                    ctx.stroke()
                }

                function filledGlow(radiusValue, alpha, colorValue, minimumFinalAlpha) {
                    var gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, radiusValue)
                    gradient.addColorStop(0, root.colorString(colorValue || accent, finalAlpha(alpha, minimumFinalAlpha)))
                    gradient.addColorStop(0.62, root.colorString(colorValue || accent, finalAlpha(alpha * 0.18, (minimumFinalAlpha || 0) * 0.22)))
                    gradient.addColorStop(1, root.colorString(colorValue || accent, 0))
                    ctx.beginPath()
                    ctx.arc(cx, cy, radiusValue, 0, Math.PI * 2)
                    ctx.fillStyle = gradient
                    ctx.fill()
                }

                function glassDisc(radiusValue, alpha, minimumFinalAlpha) {
                    var gradient = ctx.createRadialGradient(cx - radiusValue * 0.25, cy - radiusValue * 0.34, radiusValue * 0.12, cx, cy, radiusValue)
                    var floor = minimumFinalAlpha || 0
                    gradient.addColorStop(0, root.colorString(sf.textPrimary, finalAlpha(alpha * 0.34, floor * 0.40)))
                    gradient.addColorStop(0.30, root.colorString(sf.signalCyan, finalAlpha(alpha * 0.13, floor * 0.26)))
                    gradient.addColorStop(0.72, root.colorString(sf.deepBlue, finalAlpha(alpha * 0.46, floor * 0.36)))
                    gradient.addColorStop(1, root.colorString(sf.abyss, finalAlpha(alpha * 0.70, floor * 0.30)))
                    ctx.beginPath()
                    ctx.arc(cx, cy, radiusValue, 0, Math.PI * 2)
                    ctx.fillStyle = gradient
                    ctx.fill()
                }

                function depthRim(radiusValue, alpha) {
                    ctx.beginPath()
                    ctx.arc(cx + depthShift, cy + depthShift, radiusValue, 0, Math.PI * 2)
                    ctx.lineWidth = sf.anchorStrokeHeavy + 0.8
                    ctx.strokeStyle = root.colorString(sf.abyss, alpha * root.depthShadowOpacity)
                    ctx.stroke()
                    ctx.beginPath()
                    ctx.arc(cx - depthShift * 0.35, cy - depthShift * 0.35, radiusValue * 0.98, 0, Math.PI * 2)
                    ctx.lineWidth = sf.anchorStrokePrimary
                    ctx.strokeStyle = root.colorString(sf.textPrimary, alpha * 0.12 * activeAlpha)
                    ctx.stroke()
                }

                function arc(radiusValue, start, sweep, lineWidth, alpha, colorValue, minimumFinalAlpha) {
                    ctx.beginPath()
                    ctx.arc(cx, cy, radiusValue, start, start + sweep)
                    ctx.lineWidth = lineWidth
                    ctx.lineCap = "round"
                    ctx.strokeStyle = root.colorString(colorValue || accent, finalAlpha(alpha, minimumFinalAlpha))
                    ctx.stroke()
                }

                function organicLensPath(radiusValue, deform, angleOffset) {
                    var steps = 28
                    ctx.beginPath()
                    for (var step = 0; step <= steps; ++step) {
                        var angle = (Math.PI * 2 * step / steps) + angleOffset
                        var local = 1
                            + deform * Math.sin(angle * 2.0 + root.organicMotionTimeMs / Math.max(1, root.idlePrimaryCycleMs) * Math.PI * 2)
                            + deform * 0.58 * Math.sin(angle * 3.0 - root.organicMotionTimeMs / Math.max(1, root.idleSecondaryCycleMs) * Math.PI * 2)
                        var px = cx + organicOffsetX + Math.cos(angle) * radiusValue * local
                        var py = cy + organicOffsetY + Math.sin(angle) * radiusValue * local
                        if (step === 0)
                            ctx.moveTo(px, py)
                        else
                            ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                }

                function rotatingRingFragments(alpha) {
                    if (!root.ringFragmentsActive)
                        return
                    var cycles = [
                        sf.durationAnchorRingFragmentMin,
                        26000,
                        34000,
                        sf.durationAnchorRingFragmentMax
                    ]
                    var radii = [0.92, 0.74, 0.61, 0.47]
                    var sweeps = [0.11, 0.085, 0.13, 0.075]
                    for (var fragment = 0; fragment < root.ringFragmentCount; ++fragment) {
                        var direction = fragment % 2 === 0 ? 1 : -1
                        var cycle = cycles[fragment % cycles.length]
                        var angle = direction * (root.ringFragmentPhase * Math.PI * 2 / (cycle / 1000.0)) + fragment * Math.PI * 0.56
                        var colorValue = fragment === 1 && (targetState === "approval_required" || targetState === "acting") ? sf.brass
                            : fragment === 2 && targetState === "mock_dev" ? sf.devViolet
                            : fragment === 3 ? sf.lineStrong : accent
                        arc(radius * radii[fragment % radii.length], angle, Math.PI * sweeps[fragment % sweeps.length], sf.anchorStrokeHairline, alpha * (1 - fragment * 0.12), colorValue)
                    }
                }

                function helmCrown(radiusValue, alpha) {
                    var crownColor = targetState === "approval_required" || targetState === "acting" ? sf.brass : accent
                    var top = cy - radiusValue * 1.055
                    ctx.beginPath()
                    ctx.moveTo(cx, top - radiusValue * 0.085)
                    ctx.lineTo(cx - radiusValue * 0.044, top + radiusValue * 0.026)
                    ctx.lineTo(cx + radiusValue * 0.044, top + radiusValue * 0.026)
                    ctx.closePath()
                    ctx.fillStyle = root.colorString(crownColor, alpha * activeAlpha)
                    ctx.fill()

                    ctx.beginPath()
                    ctx.moveTo(cx - radiusValue * 0.12, top + radiusValue * 0.055)
                    ctx.lineTo(cx - radiusValue * 0.048, top + radiusValue * 0.055)
                    ctx.moveTo(cx + radiusValue * 0.048, top + radiusValue * 0.055)
                    ctx.lineTo(cx + radiusValue * 0.12, top + radiusValue * 0.055)
                    ctx.lineWidth = sf.anchorStrokePrimary
                    ctx.lineCap = "round"
                    ctx.strokeStyle = root.colorString(sf.lineStrong, alpha * 0.62 * activeAlpha)
                    ctx.stroke()
                }

                function outerSignatureClamp(radiusValue, alpha, minimumFinalAlpha) {
                    var clampColor = targetState === "approval_required" || targetState === "acting" ? sf.brass : sf.signalCyan
                    var secondaryColor = targetState === "failed" ? sf.danger : targetState === "blocked" ? sf.amber : accent
                    var floor = minimumFinalAlpha || 0
                    arc(radiusValue, -Math.PI * 0.63, Math.PI * 0.23, sf.anchorStrokeHeavy, alpha, clampColor, floor)
                    arc(radiusValue, -Math.PI * 0.37, Math.PI * 0.10, sf.anchorStrokePrimary, alpha * 0.62, secondaryColor, floor * 0.64)
                    arc(radiusValue * 0.965, Math.PI * 0.18, Math.PI * 0.10, sf.anchorStrokeHairline, alpha * 0.58, secondaryColor, floor * 0.54)
                    arc(radiusValue * 0.965, Math.PI * 0.82, Math.PI * 0.08, sf.anchorStrokeHairline, alpha * 0.38, sf.lineStrong, floor * 0.38)
                }

                function ticks(radiusValue, alpha, minimumFinalAlpha) {
                    ctx.save()
                    ctx.translate(cx, cy)
                    var majorStep = Math.max(1, Math.round(sf.anchorBearingTickCount / 4))
                    var mediumStep = Math.max(1, Math.round(sf.anchorBearingTickCount / 8))
                    var floor = minimumFinalAlpha || 0
                    for (var index = 0; index < sf.anchorBearingTickCount; ++index) {
                        var major = index % majorStep === 0
                        var quarter = index % mediumStep === 0
                        var length = major ? radius * 0.12 : quarter ? radius * 0.078 : radius * 0.038
                        ctx.save()
                        ctx.rotate((Math.PI * 2 / sf.anchorBearingTickCount) * index)
                        ctx.beginPath()
                        ctx.moveTo(0, -radiusValue)
                        ctx.lineTo(0, -radiusValue + length)
                        ctx.lineWidth = major ? sf.anchorStrokeHeavy : quarter ? sf.anchorStrokePrimary : sf.anchorStrokeHairline
                        ctx.strokeStyle = root.colorString(
                            major ? accent : sf.lineStrong,
                            finalAlpha(major ? alpha : alpha * 0.56, major ? floor : floor * 0.48)
                        )
                        ctx.stroke()
                        ctx.restore()
                    }
                    ctx.restore()
                }

                function quadrantMarks(radiusValue, alpha) {
                    ctx.save()
                    ctx.translate(cx, cy)
                    for (var mark = 0; mark < 4; ++mark) {
                        ctx.save()
                        ctx.rotate(Math.PI * 0.5 * mark)
                        ctx.beginPath()
                        ctx.moveTo(0, -radiusValue * 0.96)
                        ctx.lineTo(-radiusValue * 0.032, -radiusValue * 0.89)
                        ctx.lineTo(radiusValue * 0.032, -radiusValue * 0.89)
                        ctx.closePath()
                        ctx.fillStyle = root.colorString(mark === 0 ? accent : sf.lineStrong, (mark === 0 ? alpha : alpha * 0.48) * activeAlpha)
                        ctx.fill()
                        ctx.restore()
                    }
                    ctx.restore()
                }

                function centerAperture(radiusValue, alpha, stateName, featureAlpha) {
                    if (stateName === undefined || stateName === null || stateName.length <= 0)
                        stateName = targetState
                    var centerArrival = featureAlpha === undefined || featureAlpha === null ? stateArrival : featureAlpha
                    var stateSizeBias = stateName === "listening" || stateName === "capturing" ? 0.07 + root.effectiveAudioLevel * 0.04
                        : stateName === "speaking" ? 0.055 + speakLevel * 0.045 + speakDynamics * 0.040 + speakTransient * 0.028
                        : stateName === "transcribing" ? 0.045
                        : stateName === "thinking" ? 0.030
                        : stateName === "acting" ? 0.035
                        : stateName === "approval_required" ? 0.015
                        : stateName === "blocked" ? 0.005
                        : stateName === "failed" ? 0.010
                        : stateName === "mock_dev" ? 0.035
                        : stateName === "unavailable" ? -0.12
                        : 0.025
                    var blobRadius = Math.max(radius * 0.25, radiusValue * (1.02 + stateSizeBias))
                    var stateRimColor = stateName === "approval_required" || stateName === "acting" ? sf.brass
                        : stateName === "blocked" ? sf.amber
                        : stateName === "failed" ? sf.danger
                        : stateName === "mock_dev" ? sf.devViolet
                        : accent
                    var idleBlobFloor = isIdlePresenceState(stateName)
                        ? root.idleBlobOpacityFloor * Math.max(0.18, centerArrival)
                        : 0
                    var blobAlpha = muted ? Math.max(alpha * 0.42, root.finalBlobOpacity) : Math.max(alpha, idleBlobFloor)

                    ctx.beginPath()
                    ctx.arc(cx + radius * 0.018, cy + radius * 0.026, blobRadius * 1.20, 0, Math.PI * 2)
                    ctx.fillStyle = root.colorString(sf.abyss, blobAlpha * sf.anchorCenterLensShadowOpacity)
                    ctx.fill()

                    var blobCx = cx + organicOffsetX
                    var blobCy = cy + organicOffsetY
                    var blobTime = root.organicMotionTimeMs
                    var blobPrimary = blobTime / Math.max(1, root.blobPrimaryCycleMs) * Math.PI * 2
                    var blobSecondary = blobTime / Math.max(1, root.blobSecondaryCycleMs) * Math.PI * 2
                    var blobDrift = blobTime / Math.max(1, root.blobDriftCycleMs) * Math.PI * 2
                    var blobShimmer = blobTime / Math.max(1, sf.durationAnchorBlobShimmer) * Math.PI * 2
                    var blobDeform = muted ? 0.010
                        : stateName === "speaking" ? sf.anchorBlobSpeakingDeformStrength * (0.54 + speakLevel * 0.24 + speakDynamics * 1.08 + speakTransient * 0.55)
                        : root.idleMotionActive ? sf.anchorBlobIdleDeformStrength
                        : sf.anchorBlobDeformStrength * (0.72 + root.effectiveIntensity * 0.40)

                    function blobRadiusAt(angle, pointIndex) {
                        var audioRipple = stateName === "speaking" ? (speakLevel * 0.024 + speakDynamics * 0.074 + speakTransient * 0.050) * root.speakingAudioReactiveStrengthBoost * Math.sin(angle * 5.0 + root.speakingPhase * 1.75) : 0
                        var receiveRipple = stateName === "listening" || stateName === "capturing" ? root.effectiveAudioLevel * 0.030 * Math.sin(angle * 4.0 + root.wavePhase) : 0
                        var diagnostic = stateName === "failed" && pointIndex % 9 === 0 ? -0.070 : 0
                        return 1
                            + blobDeform * Math.sin(angle * 2.0 + blobPrimary)
                            + blobDeform * 0.58 * Math.sin(angle * 3.0 - blobSecondary + 0.8)
                            + blobDeform * 0.36 * Math.sin(angle * 5.0 + blobDrift * 0.72)
                            + audioRipple
                            + receiveRipple
                            + diagnostic
                    }

                    function blobPath(radiusScale, phaseOffset) {
                        var points = Math.max(12, root.blobPointCount)
                        var coordinates = []
                        for (var point = 0; point < points; ++point) {
                            var angle = Math.PI * 2 * point / points + phaseOffset
                            var localRadius = blobRadius * radiusScale * blobRadiusAt(angle, point)
                            coordinates.push({
                                "x": blobCx + Math.cos(angle) * localRadius,
                                "y": blobCy + Math.sin(angle) * localRadius
                            })
                        }
                        ctx.beginPath()
                        for (var index = 0; index < coordinates.length; ++index) {
                            var current = coordinates[index]
                            var next = coordinates[(index + 1) % coordinates.length]
                            var midX = (current.x + next.x) * 0.5
                            var midY = (current.y + next.y) * 0.5
                            if (index === 0)
                                ctx.moveTo(midX, midY)
                            ctx.quadraticCurveTo(next.x, next.y, (next.x + coordinates[(index + 2) % coordinates.length].x) * 0.5, (next.y + coordinates[(index + 2) % coordinates.length].y) * 0.5)
                        }
                        ctx.closePath()
                    }

                    var blobGlow = sf.anchorBlobGlowOpacity + (root.idleMotionActive ? sf.anchorOrganicGlowShift * root.idleBreathValue : 0) + speakLevel * 0.36 * root.speakingAudioReactiveStrengthBoost
                    var blobGlowAlpha = muted ? root.finalCenterGlowOpacity : Math.max(blobGlow * 0.22, isIdlePresenceState(stateName) ? root.idleCenterGlowFloor : 0)
                    filledGlow(blobRadius * (1.88 + speakLevel * 0.30 * root.speakingAudioReactiveStrengthBoost), blobGlowAlpha, stateRimColor, Math.max(root.minimumCenterLensOpacity * 0.30, root.finalCenterGlowOpacity * 0.58))
                    var blobGradient = ctx.createRadialGradient(
                        blobCx - blobRadius * 0.22,
                        blobCy - blobRadius * 0.30,
                        blobRadius * 0.08,
                        blobCx,
                        blobCy,
                        blobRadius * 1.18
                    )
                    blobGradient.addColorStop(0, root.colorString(sf.textPrimary, finalAlpha(blobAlpha * 0.62, root.finalBlobOpacity * 0.48)))
                    blobGradient.addColorStop(0.18, root.colorString(stateRimColor, finalAlpha(blobAlpha * (0.82 + speakLevel * 0.20 * root.speakingAudioReactiveStrengthBoost), root.finalBlobOpacity * 0.64)))
                    blobGradient.addColorStop(0.56, root.colorString(sf.signalCyan, finalAlpha(blobAlpha * 0.30, root.finalBlobOpacity * 0.30)))
                    blobGradient.addColorStop(0.78, root.colorString(sf.deepBlue, finalAlpha(blobAlpha * 0.70, root.finalBlobOpacity * 0.42)))
                    blobGradient.addColorStop(1, root.colorString(sf.abyss, finalAlpha(blobAlpha * 0.92, root.finalBlobOpacity * 0.36)))
                    blobPath(1.0, organicDriftAngle * 0.06)
                    ctx.fillStyle = blobGradient
                    ctx.fill()

                    var shimmerX = blobCx + root.apertureShimmerOffsetX * blobRadius
                    var shimmerY = blobCy + root.apertureShimmerOffsetY * blobRadius
                    var shimmerAlpha = muted
                        ? Math.max(root.apertureShimmerOpacityMin * 0.48, root.finalCenterGlowOpacity * 0.36)
                        : root.apertureShimmerOpacity * (0.90 + root.idleBreathValue * 0.13 + speakLevel * 0.22) * activeAlpha
                    ctx.save()
                    blobPath(0.94, organicDriftAngle * 0.06)
                    ctx.clip()
                    var shimmerGradient = ctx.createRadialGradient(
                        shimmerX - blobRadius * 0.035,
                        shimmerY - blobRadius * 0.030,
                        blobRadius * 0.010,
                        shimmerX,
                        shimmerY,
                        blobRadius * sf.anchorApertureShimmerRadiusRatio
                    )
                    shimmerGradient.addColorStop(0, root.colorString(sf.textPrimary, shimmerAlpha * 0.78))
                    shimmerGradient.addColorStop(0.34, root.colorString(stateRimColor, shimmerAlpha * 0.48))
                    shimmerGradient.addColorStop(0.72, root.colorString(sf.signalCyan, shimmerAlpha * 0.20))
                    shimmerGradient.addColorStop(1, root.colorString(sf.signalCyan, 0))
                    ctx.fillStyle = shimmerGradient
                    ctx.fillRect(blobCx - blobRadius, blobCy - blobRadius, blobRadius * 2, blobRadius * 2)

                    ctx.save()
                    ctx.translate(shimmerX, shimmerY)
                    ctx.rotate(-0.72 + Math.sin(root.apertureShimmerSecondaryPhase) * 0.16)
                    ctx.scale(1.82, 0.64)
                    ctx.beginPath()
                    ctx.arc(0, 0, blobRadius * 0.22, -Math.PI * 0.76, Math.PI * 0.42)
                    ctx.lineWidth = sf.anchorStrokeHairline + 0.08
                    ctx.lineCap = "round"
                    ctx.strokeStyle = root.colorString(sf.textPrimary, shimmerAlpha * 0.76)
                    ctx.stroke()
                    ctx.restore()
                    ctx.restore()

                    blobPath(1.018, organicDriftAngle * 0.06)
                    ctx.lineWidth = sf.anchorStrokePrimary + (stateName === "approval_required" ? 0.55 : 0)
                    ctx.strokeStyle = root.colorString(stateRimColor, finalAlpha(muted ? 0.16 : sf.anchorBlobRimOpacity + speakLevel * 0.24 * root.speakingAudioReactiveStrengthBoost, root.minimumCenterLensOpacity))
                    ctx.stroke()

                    blobPath(0.68, -organicDriftAngle * 0.08)
                    ctx.lineWidth = sf.anchorStrokeHairline
                    ctx.strokeStyle = root.colorString(sf.lineStrong, finalAlpha(muted ? 0.08 : 0.12 + root.idleBreathValue * 0.05, root.minimumCenterLensOpacity * 0.38))
                    ctx.stroke()

                    var crossAlpha = muted ? root.finalBearingTickOpacity * 0.34 : 0.080 * activeAlpha
                    ctx.beginPath()
                    ctx.moveTo(blobCx - blobRadius * 0.42, blobCy)
                    ctx.lineTo(blobCx + blobRadius * 0.42, blobCy)
                    ctx.moveTo(blobCx, blobCy - blobRadius * 0.42)
                    ctx.lineTo(blobCx, blobCy + blobRadius * 0.42)
                    ctx.lineWidth = sf.anchorStrokeHairline
                    ctx.strokeStyle = root.colorString(sf.lineStrong, crossAlpha)
                    ctx.stroke()

                    if (stateName === "transcribing") {
                        for (var tick = 0; tick < 8; ++tick)
                            arc(blobRadius * 1.18, tick * Math.PI * 0.25 + root.wavePhase * 0.055, Math.PI * 0.045, sf.anchorStrokeHairline, 0.14 * centerArrival, tick % 2 === 0 ? accent : sf.lineStrong)
                    } else if (stateName === "acting") {
                        var actionAngle = -Math.PI * 0.5 + Math.sin(root.phase * 0.52) * 0.035
                        ctx.beginPath()
                        ctx.moveTo(blobCx, blobCy)
                        ctx.lineTo(blobCx + Math.cos(actionAngle) * blobRadius * 1.18, blobCy + Math.sin(actionAngle) * blobRadius * 1.18)
                        ctx.lineWidth = sf.anchorStrokePrimary
                        ctx.lineCap = "round"
                        ctx.strokeStyle = root.colorString(sf.brass, 0.22 * centerArrival * activeAlpha)
                        ctx.stroke()
                    } else if (stateName === "speaking") {
                        var speakingBoost = root.speakingExpressionBoost * centerArrival
                        circle(blobRadius * (0.82 + speakReactive * 0.070 * root.speakingAudioReactiveStrengthBoost), sf.anchorStrokeHairline + speakReactive * 0.20 * root.speakingAudioReactiveStrengthBoost, (0.11 + speakReactive * 0.16) * speakingBoost, accent)
                        circle(blobRadius * (1.34 + (outerSpeakLevel * 0.05 + speakDynamics * 0.10) * root.speakingAudioReactiveStrengthBoost), sf.anchorStrokeHairline + (outerSpeakLevel * 0.08 + speakDynamics * 0.10) * root.speakingAudioReactiveStrengthBoost, (0.07 + speakReactive * 0.12) * speakingBoost, sf.signalCyan)
                        arc(blobRadius * 1.58, root.speakingPhase * 0.50, Math.PI * (0.16 + speakReactive * 0.24 * root.speakingAudioReactiveStrengthBoost), sf.anchorStrokeHairline, (0.10 + speakReactive * 0.15) * speakingBoost, sf.signalCyan)
                        arc(blobRadius * 1.82, -root.speakingPhase * 0.34 + Math.PI * 0.15, Math.PI * (0.09 + (outerSpeakLevel * 0.08 + speakDynamics * 0.14) * root.speakingAudioReactiveStrengthBoost), sf.anchorStrokeHairline, (0.06 + speakReactive * 0.11) * speakingBoost, sf.seaGreen)
                    } else if (stateName === "approval_required") {
                        arc(blobRadius * 1.22, -Math.PI * 0.72, Math.PI * 0.34, sf.anchorStrokePrimary, 0.24 * centerArrival, sf.brass)
                        arc(blobRadius * 1.22, Math.PI * 0.28, Math.PI * 0.34, sf.anchorStrokePrimary, 0.16 * centerArrival, sf.copper)
                    } else if (stateName === "blocked") {
                        arc(blobRadius * 1.20, -Math.PI * 0.18, Math.PI * 0.26, sf.anchorStrokePrimary, 0.20 * centerArrival, sf.amber)
                    } else if (stateName === "failed") {
                        arc(blobRadius * 1.18, Math.PI * 0.04, Math.PI * 0.18, sf.anchorStrokePrimary, 0.20 * centerArrival, sf.danger)
                        ctx.beginPath()
                        ctx.moveTo(blobCx + blobRadius * 0.10, blobCy - blobRadius * 0.26)
                        ctx.lineTo(blobCx + blobRadius * 0.25, blobCy - blobRadius * 0.06)
                        ctx.lineTo(blobCx + blobRadius * 0.12, blobCy + blobRadius * 0.20)
                        ctx.lineWidth = sf.anchorStrokeHairline
                        ctx.strokeStyle = root.colorString(sf.danger, 0.16 * centerArrival * activeAlpha)
                        ctx.stroke()
                    } else if (stateName === "mock_dev") {
                        arc(blobRadius * 1.15, root.orbit * 0.18, Math.PI * 0.30, sf.anchorStrokeHairline, 0.20 * centerArrival, sf.devViolet)
                    }

                    arc(blobRadius * 0.88, -Math.PI * 0.72 + Math.sin(blobShimmer) * 0.018, Math.PI * 0.34, sf.anchorStrokeHairline, muted ? 0.04 : 0.15 + root.apertureShimmerOpacity * 0.62, sf.textPrimary)
                    ctx.beginPath()
                    ctx.arc(blobCx, blobCy, Math.max(2.2, blobRadius * (0.13 + speakLevel * 0.025)), 0, Math.PI * 2)
                    ctx.fillStyle = root.colorString(
                        stateRimColor,
                        Math.max(
                            muted ? root.finalSignalPointOpacity : (root.centerPearlStrength + (root.idleMotionActive ? sf.anchorIdleLensPulseStrength * (0.35 + root.idleBreathValue * 0.65) : 0)) * activeAlpha,
                            root.minimumSignalPointOpacity
                        )
                    )
                    ctx.fill()
                }

                function horizonLine(radiusValue, alpha) {
                    ctx.save()
                    ctx.beginPath()
                    ctx.arc(cx, cy, radiusValue * 0.77, 0, Math.PI * 2)
                    ctx.clip()
                    ctx.beginPath()
                    ctx.moveTo(cx - radiusValue * 0.72, cy + horizonShift)
                    ctx.lineTo(cx + radiusValue * 0.72, cy + horizonShift)
                    ctx.lineWidth = sf.anchorStrokeHairline
                    ctx.strokeStyle = root.colorString(sf.lineStrong, alpha * activeAlpha)
                    ctx.stroke()
                    ctx.beginPath()
                    ctx.moveTo(cx, cy - radiusValue * 0.72)
                    ctx.lineTo(cx, cy + radiusValue * 0.72)
                    ctx.strokeStyle = root.colorString(accent, alpha * 0.62 * activeAlpha)
                    ctx.stroke()
                    for (var notch = -2; notch <= 2; ++notch) {
                        if (notch === 0)
                            continue
                        ctx.beginPath()
                        ctx.moveTo(cx + notch * radiusValue * 0.16, cy + horizonShift - radiusValue * 0.018)
                        ctx.lineTo(cx + notch * radiusValue * 0.16, cy + horizonShift + radiusValue * 0.018)
                        ctx.strokeStyle = root.colorString(sf.lineStrong, alpha * 0.48 * activeAlpha)
                        ctx.stroke()
                    }
                    ctx.restore()
                }

                function sonarArcs(alpha) {
                    arc(radius * 0.44, Math.PI * 1.05, Math.PI * 0.35, sf.anchorStrokeHairline, alpha * 0.52, sf.lineStrong)
                    arc(radius * 0.58, Math.PI * 1.01, Math.PI * 0.44, sf.anchorStrokeHairline, alpha * 0.44, sf.signalCyan)
                    arc(radius * 0.72, Math.PI * 0.98, Math.PI * 0.52, sf.anchorStrokeHairline, alpha * 0.34, sf.lineStrong)
                }

                function etchedSegments(radiusValue, alpha) {
                    var segmentSweep = Math.PI * 0.16
                    for (var segment = 0; segment < 6; ++segment) {
                        var start = segment * Math.PI / 3 + Math.sin(root.phase * 0.22 + segment) * 0.006
                        arc(radiusValue, start, segmentSweep, sf.anchorStrokeHairline, alpha * (segment % 2 === 0 ? 1 : 0.62), segment % 3 === 0 ? accent : sf.lineStrong)
                    }
                }

                function segmentedProcessingRing(radiusValue, alpha) {
                    for (var segment = 0; segment < 10; ++segment) {
                        var start = segment * Math.PI * 0.2 + root.wavePhase * 0.08
                        arc(radiusValue, start, Math.PI * 0.055, sf.anchorStrokeHairline, alpha * (segment % 2 === 0 ? 1 : 0.62), segment % 3 === 0 ? accent : sf.lineStrong)
                    }
                }

                function diagnosticBreak(radiusValue, alpha) {
                    arc(radiusValue, -Math.PI * 0.08, Math.PI * 0.09, sf.anchorStrokeHeavy, alpha, sf.danger)
                    arc(radiusValue, Math.PI * 0.92, Math.PI * 0.09, sf.anchorStrokePrimary, alpha * 0.72, sf.copper)
                    ctx.beginPath()
                    ctx.moveTo(cx + radiusValue * 0.18, cy - radiusValue * 0.18)
                    ctx.lineTo(cx + radiusValue * 0.30, cy - radiusValue * 0.06)
                    ctx.lineTo(cx + radiusValue * 0.20, cy + radiusValue * 0.05)
                    ctx.lineWidth = sf.anchorStrokeHairline
                    ctx.lineCap = "round"
                    ctx.strokeStyle = root.colorString(sf.danger, alpha * 0.55 * activeAlpha)
                    ctx.stroke()
                }

                function compassNeedles(radiusValue, alpha) {
                    ctx.save()
                    ctx.translate(cx, cy)
                    for (var arm = 0; arm < 4; ++arm) {
                        ctx.save()
                        ctx.rotate(Math.PI * 0.5 * arm + (arm === 0 ? Math.sin(root.orbit) * 0.01 : 0))
                        ctx.beginPath()
                        ctx.moveTo(0, -radiusValue * 0.16)
                        ctx.lineTo(0, -radiusValue * 0.68)
                        ctx.lineWidth = arm === 0 ? sf.anchorStrokeHeavy : sf.anchorStrokePrimary
                        ctx.strokeStyle = root.colorString(arm === 0 ? accent : sf.lineStrong, (arm === 0 ? alpha : alpha * 0.46) * activeAlpha)
                        ctx.stroke()
                        ctx.restore()
                    }
                    ctx.restore()
                }

                function waveform(radiusValue, alpha) {
                    var level = Math.max(root.effectiveAudioLevel, root.visualSpeakingActive ? root.finalSpeakingEnergy : root.effectiveSpeakingLevel)
                    var bars = 24
                    ctx.save()
                    ctx.translate(cx, cy)
                    for (var bar = 0; bar < bars; ++bar) {
                        var angle = Math.PI * 2 * bar / bars
                        var carrier = 0.38 + Math.abs(Math.sin(root.wavePhase * 1.12 + bar * 0.58)) * 0.48
                        var barLength = radius * (0.014 + carrier * (0.022 + level * 0.064))
                        ctx.save()
                        ctx.rotate(angle)
                        ctx.beginPath()
                        ctx.moveTo(0, -radiusValue)
                        ctx.lineTo(0, -radiusValue - barLength)
                        ctx.lineWidth = sf.anchorStrokePrimary
                        ctx.strokeStyle = root.colorString(accent, alpha * (0.35 + carrier * 0.55) * activeAlpha)
                        ctx.stroke()
                        ctx.restore()
                    }
                    ctx.restore()
                }

                function directionalTrace(alpha) {
                    for (var trace = -1; trace <= 1; ++trace) {
                        var angle = -Math.PI * 0.5 + trace * 0.22 + Math.sin(root.phase * 0.72 + trace) * 0.014
                        ctx.beginPath()
                        ctx.moveTo(cx + Math.cos(angle) * radius * 0.22, cy + Math.sin(angle) * radius * 0.22)
                        ctx.lineTo(cx + Math.cos(angle) * radius * 0.92, cy + Math.sin(angle) * radius * 0.92)
                        ctx.lineWidth = trace === 0 ? sf.anchorStrokeHeavy : sf.anchorStrokePrimary
                        ctx.strokeStyle = root.colorString(trace === 0 ? sf.brass : accent, alpha * (trace === 0 ? 1 : 0.62) * activeAlpha)
                        ctx.stroke()
                    }
                }

                function drawMotionFeatures(stateName, featureAlpha) {
                    var profileName = profileForState(stateName)
                    if (featureAlpha <= 0)
                        return
                    if (profileName === "alignment") {
                        arc(radius * 0.88, -Math.PI * 0.52, Math.PI * 0.23, sf.anchorStrokeHeavy, 0.28 * featureAlpha, sf.seaGreen)
                        arc(radius * 0.88, Math.PI * 0.48, Math.PI * 0.23, sf.anchorStrokePrimary, 0.18 * featureAlpha, sf.signalCyan)
                        arc(radius * 0.63, -Math.PI * 0.50, Math.PI * 0.13, sf.anchorStrokeHairline, 0.15 * featureAlpha, sf.brass)
                    } else if (profileName === "listening_wave") {
                        if (stateName === "transcribing")
                            segmentedProcessingRing(radius * 0.49, 0.23 * featureAlpha)
                        else
                            waveform(radius * 0.46, (0.26 + root.effectiveAudioLevel * 0.14) * featureAlpha)
                        arc(radius * 0.68, root.orbit, Math.PI * 0.22, sf.anchorStrokePrimary, 0.18 * featureAlpha, sf.seaGreen)
                        arc(radius * 0.53, -root.orbit * 0.44 + Math.PI * 0.18, Math.PI * 0.14, sf.anchorStrokeHairline, 0.13 * featureAlpha, sf.signalCyan)
                    } else if (profileName === "orbit") {
                        arc(radius * 0.71, root.orbit, Math.PI * 0.38, sf.anchorStrokeHeavy, 0.25 * featureAlpha, sf.signalCyan)
                        arc(radius * 0.50, -root.orbit * 0.54 + Math.PI, Math.PI * 0.20, sf.anchorStrokePrimary, 0.17 * featureAlpha, accent)
                        arc(radius * 0.86, root.orbit * 0.30 + Math.PI * 0.10, Math.PI * 0.10, sf.anchorStrokeHairline, 0.13 * featureAlpha, sf.lineStrong)
                    } else if (profileName === "directional_trace") {
                        directionalTrace(0.23 * featureAlpha)
                        arc(radius * 0.88, -Math.PI * 0.12, Math.PI * 0.18, sf.anchorStrokeHeavy, 0.23 * featureAlpha, sf.brass)
                        arc(radius * 0.73, -Math.PI * 0.08, Math.PI * 0.11, sf.anchorStrokePrimary, 0.14 * featureAlpha, sf.copper)
                    } else if (profileName === "radiating") {
                        var speak = root.finalSpeakingEnergy
                        var speakWave = root.speakingPhase
                        var radiance = root.anchorUsesPlaybackEnvelope
                            ? clamp01(speak * 0.46 + root.envelopeExpandedEnergy * 0.78 + root.envelopeTransientEnergy * 0.42)
                            : speak
                        var expression = root.speakingExpressionBoost * featureAlpha
                        circle(radius * (0.46 + radiance * 0.11 * root.speakingAudioReactiveStrengthBoost + Math.sin(speakWave * 0.72) * (0.006 + root.envelopeExpandedEnergy * 0.010)), sf.anchorStrokePrimary + radiance * 1.12 * root.speakingAudioReactiveStrengthBoost, (0.10 + radiance * 0.19) * expression, accent)
                        circle(radius * (0.65 + radiance * 0.07 * root.speakingAudioReactiveStrengthBoost + Math.sin(speakWave * 0.58 + 0.8) * (0.005 + root.envelopeExpandedEnergy * 0.009)), sf.anchorStrokeHairline + radiance * 0.50 * root.speakingAudioReactiveStrengthBoost, (0.06 + radiance * 0.14) * expression, accent)
                        waveform(radius * 0.40, (0.21 + radiance * 0.22 * root.speakingAudioReactiveStrengthBoost) * expression)
                        arc(radius * 0.86, -Math.PI * 0.72, Math.PI * (0.12 + radiance * 0.10 * root.speakingAudioReactiveStrengthBoost), sf.anchorStrokeHairline, (0.10 + radiance * 0.13) * expression, sf.signalCyan)
                        arc(radius * 0.98, speakWave * 0.30 + Math.PI * 0.22, Math.PI * (0.08 + (outerSpeakLevel * 0.06 + root.envelopeExpandedEnergy * 0.14) * root.speakingAudioReactiveStrengthBoost), sf.anchorStrokeHairline, (0.06 + radiance * 0.11) * expression, sf.seaGreen)
                    } else if (profileName === "approval_halo") {
                        arc(radius * 0.91, 0.16, Math.PI * 0.25, sf.anchorStrokeHeavy, 0.30 * featureAlpha, sf.amber)
                        arc(radius * 0.91, Math.PI + 0.16, Math.PI * 0.25, sf.anchorStrokePrimary, 0.21 * featureAlpha, sf.copper)
                        arc(radius * 0.62, Math.PI * 0.08, Math.PI * 0.18, sf.anchorStrokeHairline, 0.15 * featureAlpha, sf.brass)
                        outerSignatureClamp(radius * 1.035, 0.24 * featureAlpha)
                    } else if (profileName === "warning_halo") {
                        arc(radius * 0.91, 0.18, Math.PI * 0.18, sf.anchorStrokeHeavy, 0.25 * featureAlpha, sf.amber)
                        arc(radius * 0.91, Math.PI + 0.18, Math.PI * 0.18, sf.anchorStrokePrimary, 0.18 * featureAlpha, sf.copper)
                        arc(radius * 0.70, Math.PI * 0.92, Math.PI * 0.12, sf.anchorStrokeHairline, 0.12 * featureAlpha, sf.amber)
                    } else if (profileName === "failure") {
                        arc(radius * 0.88, Math.PI * 0.08, Math.PI * 0.14, sf.anchorStrokeHeavy, 0.24 * featureAlpha, sf.danger)
                        arc(radius * 0.88, Math.PI * 1.08, Math.PI * 0.14, sf.anchorStrokePrimary, 0.17 * featureAlpha, sf.copper)
                        arc(radius * 0.55, Math.PI * 0.54, Math.PI * 0.10, sf.anchorStrokeHairline, 0.10 * featureAlpha, sf.danger)
                        diagnosticBreak(radius * 0.72, 0.16 * featureAlpha)
                    } else if (profileName === "dev_trace") {
                        arc(radius * 0.69, root.orbit, Math.PI * 0.30, sf.anchorStrokePrimary, 0.25 * featureAlpha, sf.devViolet)
                        arc(radius * 0.84, -root.orbit * 0.45, Math.PI * 0.11, sf.anchorStrokeHairline, 0.17 * featureAlpha, sf.devViolet)
                        arc(radius * 0.46, Math.PI * 1.22, Math.PI * 0.13, sf.anchorStrokeHairline, 0.13 * featureAlpha, sf.devViolet)
                    }
                }

                filledGlow(radius * 1.22, 0.075, sf.deepBlue, Math.max(root.minimumRingOpacity * 0.18, root.finalRingOpacity * 0.18))
                filledGlow(radius * (1.15 + pulse * 0.045), muted ? root.finalCenterGlowOpacity * 0.42 : sf.anchorHaloOpacity + pulse * 0.035, glow, Math.max(root.minimumRingOpacity * 0.30, root.finalRingOpacity * 0.30))
                glassDisc(radius * 0.96, muted ? root.instrumentGlassOpacity * 0.58 : root.instrumentGlassOpacity, Math.max(root.minimumCenterLensOpacity * 0.48, root.finalBlobOpacity * 0.30))
                filledGlow(radius * 0.70, muted ? root.finalCenterGlowOpacity * 0.64 : Math.max(0.040 + pulse * 0.048, isIdlePresenceState(targetState) ? root.idleCenterGlowFloor : 0), accent, Math.max(root.minimumCenterLensOpacity * (isIdlePresenceState(targetState) ? 0.56 : 0.30), root.finalCenterGlowOpacity * 0.54))
                depthRim(radius * 1.005 * outerScale, muted ? 0.46 : sf.anchorBezelOpacity)
                outerSignatureClamp(radius * 1.045 * outerScale, muted ? root.finalRingOpacity * 0.44 : root.outerClampStrength + pulse * 0.018, Math.max(root.minimumRingOpacity * 0.62, root.finalRingOpacity * 0.58))

                circle(radius * 1.0 * outerScale, sf.anchorStrokeHairline, muted ? 0.11 : 0.22 + pulse * 0.072, accent, root.finalRingOpacity)
                etchedSegments(radius * 0.91, muted ? 0.035 : 0.145)
                rotatingRingFragments(muted ? root.finalVisibilityFloorForKind("fragment", targetState) : Math.max(sf.anchorRingFragmentOpacity + idleLife * 0.22 + (targetState === "speaking" ? root.envelopeExpandedEnergy * 0.10 : 0), isIdlePresenceState(targetState) ? root.idleFragmentOpacityFloor : root.finalVisibilityFloorForKind("fragment", targetState)))
                circle(radius * 0.79, sf.anchorStrokePrimary, muted ? 0.09 : 0.22 * ringSoftness, sf.lineStrong, Math.max(root.minimumRingOpacity * 0.70, root.finalRingOpacity * 0.62))
                sonarArcs(muted ? 0.04 : 0.155)
                horizonLine(radius, muted ? 0.045 : sf.anchorHorizonOpacity)
                circle(radius * 0.57, sf.anchorStrokeHairline, muted ? 0.07 : 0.145, accent, Math.max(root.minimumRingOpacity * 0.55, root.finalRingOpacity * 0.48))
                circle(radius * 0.32, sf.anchorStrokePrimary, muted ? 0.10 : 0.29 + pulse * 0.10, accent, Math.max(root.minimumCenterLensOpacity, root.finalBlobOpacity * 0.72))

                ticks(radius * 1.0, muted ? 0.10 : 0.25, root.finalBearingTickOpacity)
                quadrantMarks(radius, muted ? 0.07 : 0.20)
                helmCrown(radius, muted ? 0.04 : root.headingMarkerStrength + pulse * 0.026)
                compassNeedles(radius, muted ? 0.075 : 0.155)

                if (transitioning)
                    drawMotionFeatures(sourceState, (1.0 - transitionBlend) * 0.82)
                drawMotionFeatures(targetState, stateArrival)

                filledGlow(radius * (root.centerLensRadiusRatio * 1.14 + speakLevel * 0.020 + speakDynamics * 0.035), muted ? 0.035 : 0.11 + speakLevel * 0.10 + speakDynamics * 0.15 + speakTransient * 0.06, accent, Math.max(root.minimumCenterLensOpacity * 0.72, root.finalCenterGlowOpacity * 0.70))
                if (transitioning)
                    centerAperture(radius * root.centerLensRadiusRatio, (muted ? root.centerApertureStrength * 0.28 : root.centerApertureStrength + speakLevel * 0.025 + speakDynamics * 0.035) * (1.0 - transitionBlend) * 0.82, sourceState, (1.0 - transitionBlend) * 0.82)
                centerAperture(radius * root.centerLensRadiusRatio, muted ? root.centerApertureStrength * 0.36 : root.centerApertureStrength + speakLevel * 0.035 + speakDynamics * 0.055, targetState, stateArrival)
                circle(radius * root.centerLensRadiusRatio * 1.10, sf.anchorStrokePrimary, muted ? 0.08 : 0.20 + pulse * 0.046 + speakDynamics * 0.040, accent, Math.max(root.minimumCenterLensOpacity, root.finalBlobOpacity * 0.70))
            }
        }

        StormforgeAnchorFrame {
            id: anchorFrameLayer
            anchors.fill: parent
            anchorCore: root
            visible: root.staticFrameLayerEnabled && root.visible
        }

        StormforgeAnchorDynamicCore {
            id: anchorDynamicLayer
            anchors.fill: parent
            anchorCore: root
            visible: root.ar3SplitRendererActive && root.visible
        }

        StormforgeAnchorLegacyBlobQsgCore {
            id: anchorLegacyBlobQsgLayer
            anchors.fill: parent
            anchorCore: root
            visible: root.qsgCandidateRendererActive && root.visible
        }
    }

    Column {
        id: labelColumn
        visible: !root.compact
        anchors.top: anchorFace.bottom
        anchors.topMargin: sf.space1
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(parent.width, 260)
        spacing: 1

        Text {
            width: parent.width
            text: root.resolvedLabel
            color: sf.stateText(root.visualState)
            font.family: "Segoe UI"
            font.weight: Font.DemiBold
            font.pixelSize: sf.fontBody
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            opacity: root.visualState === "unavailable" ? Math.max(root.minimumLabelOpacity, 0.64) : 1.0
            Behavior on color {
                ColorAnimation {
                    duration: root.stateTransitionDurationMs
                    easing.type: Easing.InOutCubic
                }
            }
            Behavior on opacity {
                NumberAnimation {
                    duration: root.stateTransitionDurationMs
                    easing.type: Easing.InOutCubic
                }
            }
        }

        Text {
            width: parent.width
            text: root.resolvedSublabel
            visible: text.length > 0
            color: sf.textMuted
            font.family: "Segoe UI"
            font.pixelSize: sf.fontXs
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            opacity: 0.84
            Behavior on color {
                ColorAnimation {
                    duration: root.stateTransitionDurationMs
                    easing.type: Easing.InOutCubic
                }
            }
            Behavior on opacity {
                NumberAnimation {
                    duration: root.stateTransitionDurationMs
                    easing.type: Easing.InOutCubic
                }
            }
        }
    }
}
