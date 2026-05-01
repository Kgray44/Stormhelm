import QtQuick 2.15

Item {
    id: root

    property var voiceState: ({})
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

    readonly property bool finalAnchorImplemented: true
    readonly property string componentRole: "stormforge_anchor_core"
    readonly property string visualTuningVersion: "UI-P2A.5"
    readonly property string idlePresenceHotfixVersion: "UI-P2A.4A"
    readonly property string stateStabilityVersion: "UI-P2A.5"
    readonly property string signatureSilhouette: "helm_crown_lens_aperture"
    readonly property string centerLensSignature: "living_helm_lens"
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
    readonly property string normalizedState: resolveState()
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
    readonly property bool idleMotionActive: isIdlePresenceState(root.visualState) && !root.disabled && root.visible
    readonly property real idleBreathValue: root.idleMotionActive ? 0.5 + Math.sin(root.phase * Math.PI * 0.34) * 0.5 : 0
    readonly property real idlePulseMin: sf.anchorIdlePulseMinOpacity
    readonly property real idlePulseMax: sf.anchorIdlePulseMaxOpacity
    readonly property int idleBreathDurationMs: sf.durationAnchorIdleBreath
    readonly property real lensPulseStrength: sf.anchorIdleLensPulseStrength
    readonly property real orbitalSpeedScale: sf.anchorOrbitalSpeedScale
    readonly property real listeningRippleSpeedScale: sf.anchorListeningRippleSpeedScale
    readonly property real speakingRadianceSpeedScale: sf.anchorSpeakingRadianceSpeedScale
    readonly property real warningPulseLimit: sf.anchorWarningPulseLimit
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
    readonly property string audioReactiveSource: textValue(voiceValue("voice_audio_reactive_source", voiceValue("audio_reactive_source", "unavailable")), "unavailable")
    readonly property bool audioReactiveAvailable: boolValue(voiceValue("voice_audio_reactive_available", voiceValue("audio_reactive_available", false)))
    readonly property real effectiveSpeakingLevel: root.normalizedState === "speaking" ? clamp01(firstNumber(
        root.speakingLevel,
        voiceValue("voice_center_blob_scale_drive", undefined),
        voiceValue("voice_center_blob_drive", undefined),
        voiceValue("audioDriveLevel", undefined),
        voiceValue("voice_visual_drive_level", undefined),
        root.audioLevel
    )) : 0
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
        root.effectiveSpeakingLevel,
        0
    ))
    readonly property real effectiveIntensity: clamp01(root.disabled ? 0 : firstNumber(
        root.intensity,
        voiceValue("voice_motion_intensity", undefined),
        root.pulseStrength,
        root.effectiveSpeakingLevel,
        root.effectiveAudioLevel,
        0.14
    ))
    readonly property color accentColor: sf.stateAccent(root.visualState)
    readonly property color haloColor: sf.stateGlow(root.visualState)
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

    function voiceValue(key, fallback) {
        if (!root.voiceState || root.voiceState[key] === undefined || root.voiceState[key] === null)
            return fallback
        return root.voiceState[key]
    }

    function hasVoiceValue(key) {
        return !!root.voiceState && root.voiceState[key] !== undefined && root.voiceState[key] !== null
    }

    function hasVoicePayload() {
        return hasVoiceValue("voice_anchor_state")
            || hasVoiceValue("voice_current_phase")
            || hasVoiceValue("active_playback_status")
            || hasVoiceValue("speaking_visual_active")
            || hasVoiceValue("active_capture_id")
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
        if (key === "mock" || key === "dev" || key === "development")
            return "mock_dev"
        if (key === "disabled" || key === "offline")
            return "unavailable"
        if (key === "ghost_ready" || key === "signal_acquired" || key === "signal_acquire" || key === "wake")
            return "wake_detected"
        if (key === "routing" || key === "processing" || key === "synthesizing" || key === "preparing" || key === "preparing_speech" || key === "requested")
            return "thinking"
        if (key === "executing" || key === "continuing_task")
            return "acting"
        if (key === "capture" || key === "capture_active")
            return "capturing"
        if (key === "approval" || key === "confirmation_required" || key === "requires_approval")
            return "approval_required"
        if (key === "warning")
            return "blocked"
        if (key === "error")
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

    function playbackSupportsSpeaking(playbackKey) {
        return playbackKey === "started" || playbackKey === "playing" || playbackKey === "active"
    }

    function resolveState() {
        if (root.disabled)
            return "unavailable"

        var explicit = normalizeStateName(root.state)
        var phase = normalizeStateName(voiceValue("voice_current_phase", ""))
        var anchor = normalizeStateName(voiceValue("voice_anchor_state", ""))
        var playback = textKey(voiceValue("active_playback_status", ""))
        var assistant = normalizeStateName(root.assistantState)
        var states = [explicit, phase, anchor, assistant]
        var voiceBacked = hasVoicePayload()
        var speakingRequested = anyStateInList(states, ["speaking"]) || playback === "playback_active" || playback === "playing" || playback === "active"
        var speakingSupported = boolValue(voiceValue("speaking_visual_active", false)) || playbackSupportsSpeaking(playback)

        if (anyStateInList(states, ["unavailable"]) || playback === "muted" || playback === "interrupted")
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
        switch (stateName) {
        case "speaking":
            return root.audioReactiveAvailable ? root.audioReactiveSource.replace(/_/g, " ") : "visual source unavailable"
        case "approval_required":
            return "Operator confirmation"
        case "blocked":
            return "Held at boundary"
        case "failed":
            return "Needs diagnosis"
        case "unavailable":
            return "Voice offline"
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
            return sf.anchorSpeakingRadianceSpeedScale + root.effectiveSpeakingLevel * 0.50
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
            return "receptive_open_aperture"
        case "transcribing":
            return "segmented_processing_lens"
        case "thinking":
            return "slow_internal_iris"
        case "acting":
            return "bearing_directed_lens"
        case "speaking":
            return "radiant_voice_lens"
        case "approval_required":
            return "brass_locked_lens"
        case "blocked":
            return "amber_bound_lens"
        case "failed":
            return "fractured_diagnostic_lens"
        case "mock_dev":
            return "synthetic_violet_lens"
        default:
            return "calm_helm_lens"
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
        anchorCanvas.requestPaint()
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
        root.requestAnchorPaint()
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

    property real phase: 0
    property real orbit: 0
    property real wavePhase: 0

    Timer {
        id: stateHoldTimer
        repeat: false
        interval: root.stateMinimumDwellMs
        onTriggered: {
            if (root.pendingVisualState.length > 0)
                root.commitVisualState(root.pendingVisualState, false)
        }
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
            root.requestAnchorPaint()
        }
    }

    Timer {
        interval: root.motionProfile === "breathing" ? 50 : 32
        repeat: true
        running: root.visible && root.animationRunning
        onTriggered: {
            var stateBoost = root.motionSpeedScale * sf.anchorMotionRestraint
            var idleStep = interval / Math.max(1, sf.durationAnchorIdleBreath) * 40.0
            root.phase += root.idleMotionActive ? idleStep : interval / 1000.0 * stateBoost
            root.orbit += interval / 1000.0 * (0.16 + stateBoost * 0.26 + root.effectiveIntensity * 0.12)
            root.wavePhase += interval / 1000.0 * (
                0.48
                + root.effectiveAudioLevel * sf.anchorListeningRippleSpeedScale
                + root.effectiveSpeakingLevel * sf.anchorSpeakingRadianceSpeedScale
            )
            root.requestAnchorPaint()
        }
    }

    onNormalizedStateChanged: {
        scheduleVisualState(root.normalizedState)
        requestAnchorPaint()
    }
    onEffectiveSpeakingLevelChanged: requestAnchorPaint()
    onEffectiveAudioLevelChanged: requestAnchorPaint()
    onEffectiveIntensityChanged: requestAnchorPaint()
    onTransitionProgressChanged: requestAnchorPaint()
    onWidthChanged: requestAnchorPaint()
    onHeightChanged: requestAnchorPaint()
    onVisibleChanged: requestAnchorPaint()
    Component.onCompleted: {
        commitVisualState(root.normalizedState, true)
        requestAnchorPaint()
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
            antialiasing: true

            onPaint: {
                var ctx = getContext("2d")
                if (ctx.reset)
                    ctx.reset()
                ctx.clearRect(0, 0, width, height)
                if (width <= 0 || height <= 0)
                    return

                var cx = width / 2
                var cy = height / 2
                var radius = Math.min(width, height) * 0.44
                var accent = root.accentColor
                var glow = root.haloColor
                var muted = root.visualState === "unavailable"
                var activeAlpha = muted ? 0.16 : root.visualState === "mock_dev" ? 0.58 : 0.78
                var breath = Math.sin(root.phase * Math.PI * 0.34)
                var counterBreath = Math.cos(root.phase * Math.PI * 0.22)
                var idleLife = root.idleMotionActive ? root.idlePulseMin + (root.idlePulseMax - root.idlePulseMin) * root.idleBreathValue : 0
                var transitionEase = 0.82 + root.transitionProgress * 0.18
                activeAlpha = activeAlpha * transitionEase
                var pulse = root.effectiveIntensity * 0.42 + root.effectiveSpeakingLevel * 0.30 + root.effectiveAudioLevel * 0.10 + idleLife
                var outerScale = 1 + (muted ? 0 : breath * (0.003 + pulse * 0.005 + (root.idleMotionActive ? sf.anchorIdleBearingDriftStrength * 0.20 : 0)))
                var ringSoftness = Math.max(0.35, Math.min(0.8, root.visualSoftness))
                var depthShift = muted ? 0 : counterBreath * radius * 0.005
                var horizonShift = muted ? 0 : Math.sin(root.orbit * 0.34) * radius * (0.012 + (root.idleMotionActive ? sf.anchorIdleBearingDriftStrength : 0))

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

                function helmCrown(radiusValue, alpha) {
                    var crownColor = root.visualState === "approval_required" || root.visualState === "acting" ? sf.brass : accent
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
                    var clampColor = root.visualState === "approval_required" || root.visualState === "acting" ? sf.brass : sf.signalCyan
                    var secondaryColor = root.visualState === "failed" ? sf.danger : root.visualState === "blocked" ? sf.amber : accent
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

                function centerAperture(radiusValue, alpha) {
                    var stateName = root.visualState
                    var openAmount = 0.02
                    if (stateName === "wake_detected" || stateName === "ready")
                        openAmount = 0.05
                    else if (stateName === "idle")
                        openAmount = 0.025 + root.idleBreathValue * 0.018
                    else if (stateName === "listening" || stateName === "capturing")
                        openAmount = 0.20 + root.effectiveAudioLevel * 0.08
                    else if (stateName === "transcribing")
                        openAmount = 0.12
                    else if (stateName === "thinking")
                        openAmount = 0.10
                    else if (stateName === "acting")
                        openAmount = 0.09
                    else if (stateName === "speaking")
                        openAmount = 0.13 + root.effectiveSpeakingLevel * 0.08
                    else if (stateName === "approval_required")
                        openAmount = -0.015
                    else if (stateName === "blocked")
                        openAmount = 0.00
                    else if (stateName === "failed")
                        openAmount = 0.02
                    else if (stateName === "mock_dev")
                        openAmount = 0.08
                    else if (stateName === "unavailable")
                        openAmount = -0.10

                    var localPulse = muted ? 0 : Math.sin(root.phase * Math.PI * 0.30) * radiusValue * (0.012 + (root.idleMotionActive ? sf.anchorIdleLensPulseStrength * 0.16 : 0))
                    var lensRadius = Math.max(radius * 0.21, radiusValue * (1 + openAmount) + localPulse)
                    var stateRimColor = stateName === "approval_required" || stateName === "acting" ? sf.brass
                        : stateName === "blocked" ? sf.amber
                        : stateName === "failed" ? sf.danger
                        : stateName === "mock_dev" ? sf.devViolet
                        : accent
                    var lensAlpha = muted ? alpha * 0.28 : alpha

                    ctx.beginPath()
                    ctx.arc(cx + radius * 0.018, cy + radius * 0.026, lensRadius * 1.14, 0, Math.PI * 2)
                    ctx.fillStyle = root.colorString(sf.abyss, lensAlpha * sf.anchorCenterLensShadowOpacity)
                    ctx.fill()

                    var apertureGradient = ctx.createRadialGradient(cx - lensRadius * 0.24, cy - lensRadius * 0.30, lensRadius * 0.08, cx, cy, lensRadius * 1.05)
                    apertureGradient.addColorStop(0, root.colorString(sf.textPrimary, lensAlpha * sf.anchorCenterLensHighlightOpacity * activeAlpha))
                    apertureGradient.addColorStop(0.22, root.colorString(stateRimColor, lensAlpha * 0.58 * activeAlpha))
                    apertureGradient.addColorStop(0.56, root.colorString(sf.deepBlue, lensAlpha * 0.44 * activeAlpha))
                    apertureGradient.addColorStop(0.84, root.colorString(sf.abyss, lensAlpha * 0.70 * activeAlpha))
                    apertureGradient.addColorStop(1, root.colorString(sf.abyss, lensAlpha * 0.92 * activeAlpha))
                    ctx.beginPath()
                    ctx.arc(cx, cy, lensRadius * 1.02, 0, Math.PI * 2)
                    ctx.fillStyle = apertureGradient
                    ctx.fill()

                    circle(lensRadius * 1.08, sf.anchorStrokePrimary + 0.20, muted ? 0.09 : sf.anchorCenterLensRimOpacity, stateRimColor, root.minimumCenterLensOpacity)
                    circle(lensRadius * 0.73, sf.anchorStrokeHairline, muted ? 0.06 : sf.anchorCenterIrisOpacity, accent, root.minimumCenterLensOpacity * 0.58)
                    circle(lensRadius * 0.45, sf.anchorStrokeHairline, muted ? 0.05 : sf.anchorCenterIrisOpacity * 0.78, sf.lineStrong, root.minimumCenterLensOpacity * 0.46)

                    var irisDrift = stateName === "thinking" ? root.orbit * 0.18
                        : stateName === "mock_dev" ? -root.orbit * 0.16
                        : stateName === "transcribing" ? root.wavePhase * 0.035
                        : 0
                    var petalAlpha = muted ? 0.035 : sf.anchorCenterPetalOpacity + openAmount * 0.18 + (root.idleMotionActive ? sf.anchorIdleApertureShimmerOpacity * root.idleBreathValue : 0)
                    for (var petal = 0; petal < sf.anchorCenterApertureSegmentCount; ++petal) {
                        var angle = -Math.PI * 0.5 + petal * Math.PI * 0.5 + irisDrift
                        var spread = 0.10 + Math.max(0, openAmount) * 0.18
                        var inner = lensRadius * (0.30 + Math.max(0, openAmount) * 0.18)
                        var outer = lensRadius * (0.78 + Math.max(0, openAmount) * 0.14)
                        ctx.beginPath()
                        ctx.moveTo(cx + Math.cos(angle - spread) * inner, cy + Math.sin(angle - spread) * inner)
                        ctx.lineTo(cx + Math.cos(angle) * outer, cy + Math.sin(angle) * outer)
                        ctx.lineTo(cx + Math.cos(angle + spread) * inner, cy + Math.sin(angle + spread) * inner)
                        ctx.closePath()
                        ctx.fillStyle = root.colorString(
                            petal === 0 ? stateRimColor : sf.lineStrong,
                            finalAlpha(petalAlpha * (petal === 0 ? 1.0 : 0.62), root.minimumCenterLensOpacity * (petal === 0 ? 0.42 : 0.28))
                        )
                        ctx.fill()
                    }

                    var crossAlpha = muted ? 0.035 : 0.12 * activeAlpha
                    ctx.beginPath()
                    ctx.moveTo(cx - lensRadius * 0.46, cy)
                    ctx.lineTo(cx + lensRadius * 0.46, cy)
                    ctx.moveTo(cx, cy - lensRadius * 0.46)
                    ctx.lineTo(cx, cy + lensRadius * 0.46)
                    ctx.lineWidth = sf.anchorStrokeHairline
                    ctx.strokeStyle = root.colorString(sf.lineStrong, crossAlpha)
                    ctx.stroke()

                    if (stateName === "transcribing") {
                        for (var tick = 0; tick < 8; ++tick)
                            arc(lensRadius * 0.95, tick * Math.PI * 0.25 + root.wavePhase * 0.055, Math.PI * 0.045, sf.anchorStrokeHairline, 0.14, tick % 2 === 0 ? accent : sf.lineStrong)
                    } else if (stateName === "acting") {
                        var actionAngle = -Math.PI * 0.5 + Math.sin(root.phase * 0.52) * 0.035
                        ctx.beginPath()
                        ctx.moveTo(cx, cy)
                        ctx.lineTo(cx + Math.cos(actionAngle) * lensRadius * 0.98, cy + Math.sin(actionAngle) * lensRadius * 0.98)
                        ctx.lineWidth = sf.anchorStrokePrimary
                        ctx.lineCap = "round"
                        ctx.strokeStyle = root.colorString(sf.brass, 0.22 * activeAlpha)
                        ctx.stroke()
                    } else if (stateName === "speaking") {
                        circle(lensRadius * (0.72 + root.effectiveSpeakingLevel * 0.12), sf.anchorStrokeHairline, 0.12 + root.effectiveSpeakingLevel * 0.12, accent)
                        circle(lensRadius * (1.22 + root.effectiveOuterMotion * 0.08), sf.anchorStrokeHairline, 0.07 + root.effectiveSpeakingLevel * 0.08, sf.signalCyan)
                    } else if (stateName === "approval_required") {
                        arc(lensRadius * 1.12, -Math.PI * 0.72, Math.PI * 0.34, sf.anchorStrokePrimary, 0.24, sf.brass)
                        arc(lensRadius * 1.12, Math.PI * 0.28, Math.PI * 0.34, sf.anchorStrokePrimary, 0.16, sf.copper)
                    } else if (stateName === "blocked") {
                        arc(lensRadius * 1.10, -Math.PI * 0.18, Math.PI * 0.26, sf.anchorStrokePrimary, 0.20, sf.amber)
                    } else if (stateName === "failed") {
                        arc(lensRadius * 1.08, Math.PI * 0.04, Math.PI * 0.18, sf.anchorStrokePrimary, 0.20, sf.danger)
                        ctx.beginPath()
                        ctx.moveTo(cx + lensRadius * 0.10, cy - lensRadius * 0.26)
                        ctx.lineTo(cx + lensRadius * 0.25, cy - lensRadius * 0.06)
                        ctx.lineTo(cx + lensRadius * 0.12, cy + lensRadius * 0.20)
                        ctx.lineWidth = sf.anchorStrokeHairline
                        ctx.strokeStyle = root.colorString(sf.danger, 0.16 * activeAlpha)
                        ctx.stroke()
                    } else if (stateName === "mock_dev") {
                        arc(lensRadius * 1.02, root.orbit * 0.18, Math.PI * 0.30, sf.anchorStrokeHairline, 0.20, sf.devViolet)
                    }

                    arc(lensRadius * 0.84, -Math.PI * 0.72, Math.PI * 0.34, sf.anchorStrokeHairline, muted ? 0.05 : 0.19 + (root.idleMotionActive ? sf.anchorIdleApertureShimmerOpacity * 0.65 : 0), sf.textPrimary)
                    ctx.beginPath()
                    ctx.arc(cx, cy, Math.max(2.0, lensRadius * 0.145), 0, Math.PI * 2)
                    ctx.fillStyle = root.colorString(
                        stateRimColor,
                        Math.max(
                            muted ? 0.035 : (root.centerPearlStrength + (root.idleMotionActive ? sf.anchorIdleLensPulseStrength * root.idleBreathValue : 0)) * activeAlpha,
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
                    var level = Math.max(root.effectiveAudioLevel, root.effectiveSpeakingLevel)
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

                filledGlow(radius * 1.22, 0.075, sf.deepBlue, root.minimumRingOpacity * 0.18)
                filledGlow(radius * (1.15 + pulse * 0.045), muted ? 0.024 : sf.anchorHaloOpacity + pulse * 0.035, glow, root.minimumRingOpacity * 0.30)
                glassDisc(radius * 0.96, muted ? root.instrumentGlassOpacity * 0.34 : root.instrumentGlassOpacity, root.minimumCenterLensOpacity * 0.48)
                filledGlow(radius * 0.70, muted ? 0.020 : 0.040 + pulse * 0.048, accent, root.minimumCenterLensOpacity * 0.30)
                depthRim(radius * 1.005 * outerScale, muted ? 0.34 : sf.anchorBezelOpacity)
                outerSignatureClamp(radius * 1.045 * outerScale, muted ? 0.035 : root.outerClampStrength + pulse * 0.018, root.minimumRingOpacity * 0.62)

                circle(radius * 1.0 * outerScale, sf.anchorStrokeHairline, muted ? 0.11 : 0.20 + pulse * 0.065, accent, root.minimumRingOpacity)
                etchedSegments(radius * 0.91, muted ? 0.035 : 0.13)
                circle(radius * 0.79, sf.anchorStrokePrimary, muted ? 0.09 : 0.20 * ringSoftness, sf.lineStrong, root.minimumRingOpacity * 0.70)
                sonarArcs(muted ? 0.04 : 0.14)
                horizonLine(radius, muted ? 0.045 : sf.anchorHorizonOpacity)
                circle(radius * 0.57, sf.anchorStrokeHairline, muted ? 0.07 : 0.13, accent, root.minimumRingOpacity * 0.55)
                circle(radius * 0.32, sf.anchorStrokePrimary, muted ? 0.10 : 0.26 + pulse * 0.09, accent, root.minimumCenterLensOpacity)

                ticks(radius * 1.0, muted ? 0.10 : 0.25, root.minimumBearingTickOpacity)
                quadrantMarks(radius, muted ? 0.07 : 0.20)
                helmCrown(radius, muted ? 0.04 : root.headingMarkerStrength + pulse * 0.026)
                compassNeedles(radius, muted ? 0.075 : 0.155)

                if (root.motionProfile === "alignment") {
                    arc(radius * 0.88, -Math.PI * 0.52, Math.PI * 0.23, sf.anchorStrokeHeavy, 0.28, sf.seaGreen)
                    arc(radius * 0.88, Math.PI * 0.48, Math.PI * 0.23, sf.anchorStrokePrimary, 0.18, sf.signalCyan)
                    arc(radius * 0.63, -Math.PI * 0.50, Math.PI * 0.13, sf.anchorStrokeHairline, 0.15, sf.brass)
                } else if (root.motionProfile === "listening_wave") {
                    if (root.visualState === "transcribing")
                        segmentedProcessingRing(radius * 0.49, 0.23)
                    else
                        waveform(radius * 0.46, 0.26 + root.effectiveAudioLevel * 0.14)
                    arc(radius * 0.68, root.orbit, Math.PI * 0.22, sf.anchorStrokePrimary, 0.18, sf.seaGreen)
                    arc(radius * 0.53, -root.orbit * 0.44 + Math.PI * 0.18, Math.PI * 0.14, sf.anchorStrokeHairline, 0.13, sf.signalCyan)
                } else if (root.motionProfile === "orbit") {
                    arc(radius * 0.71, root.orbit, Math.PI * 0.38, sf.anchorStrokeHeavy, 0.25, sf.signalCyan)
                    arc(radius * 0.50, -root.orbit * 0.54 + Math.PI, Math.PI * 0.20, sf.anchorStrokePrimary, 0.17, accent)
                    arc(radius * 0.86, root.orbit * 0.30 + Math.PI * 0.10, Math.PI * 0.10, sf.anchorStrokeHairline, 0.13, sf.lineStrong)
                } else if (root.motionProfile === "directional_trace") {
                    directionalTrace(0.23)
                    arc(radius * 0.88, -Math.PI * 0.12, Math.PI * 0.18, sf.anchorStrokeHeavy, 0.23, sf.brass)
                    arc(radius * 0.73, -Math.PI * 0.08, Math.PI * 0.11, sf.anchorStrokePrimary, 0.14, sf.copper)
                } else if (root.motionProfile === "radiating") {
                    var speak = root.effectiveSpeakingLevel
                    circle(radius * (0.46 + speak * 0.10 + Math.sin(root.phase * 0.72) * 0.010), sf.anchorStrokePrimary + speak * 1.05, 0.11 + speak * 0.16, accent)
                    circle(radius * (0.65 + speak * 0.07 + Math.sin(root.phase * 0.58 + 0.8) * 0.009), sf.anchorStrokeHairline + root.effectiveOuterMotion * 0.48, 0.07 + speak * 0.11, accent)
                    waveform(radius * 0.40, 0.23 + speak * 0.16)
                    arc(radius * 0.86, -Math.PI * 0.72, Math.PI * 0.12, sf.anchorStrokeHairline, 0.12 + speak * 0.08, sf.signalCyan)
                } else if (root.motionProfile === "approval_halo") {
                    arc(radius * 0.91, 0.16, Math.PI * 0.25, sf.anchorStrokeHeavy, 0.30, sf.amber)
                    arc(radius * 0.91, Math.PI + 0.16, Math.PI * 0.25, sf.anchorStrokePrimary, 0.21, sf.copper)
                    arc(radius * 0.62, Math.PI * 0.08, Math.PI * 0.18, sf.anchorStrokeHairline, 0.15, sf.brass)
                    outerSignatureClamp(radius * 1.035, 0.24)
                } else if (root.motionProfile === "warning_halo") {
                    arc(radius * 0.91, 0.18, Math.PI * 0.18, sf.anchorStrokeHeavy, 0.25, sf.amber)
                    arc(radius * 0.91, Math.PI + 0.18, Math.PI * 0.18, sf.anchorStrokePrimary, 0.18, sf.copper)
                    arc(radius * 0.70, Math.PI * 0.92, Math.PI * 0.12, sf.anchorStrokeHairline, 0.12, sf.amber)
                } else if (root.motionProfile === "failure") {
                    arc(radius * 0.88, Math.PI * 0.08, Math.PI * 0.14, sf.anchorStrokeHeavy, 0.24, sf.danger)
                    arc(radius * 0.88, Math.PI * 1.08, Math.PI * 0.14, sf.anchorStrokePrimary, 0.17, sf.copper)
                    arc(radius * 0.55, Math.PI * 0.54, Math.PI * 0.10, sf.anchorStrokeHairline, 0.10, sf.danger)
                    diagnosticBreak(radius * 0.72, 0.16)
                } else if (root.motionProfile === "dev_trace") {
                    arc(radius * 0.69, root.orbit, Math.PI * 0.30, sf.anchorStrokePrimary, 0.25, sf.devViolet)
                    arc(radius * 0.84, -root.orbit * 0.45, Math.PI * 0.11, sf.anchorStrokeHairline, 0.17, sf.devViolet)
                    arc(radius * 0.46, Math.PI * 1.22, Math.PI * 0.13, sf.anchorStrokeHairline, 0.13, sf.devViolet)
                }

                filledGlow(radius * (root.centerLensRadiusRatio * 1.12 + root.effectiveSpeakingLevel * 0.035), muted ? 0.035 : 0.11 + root.effectiveSpeakingLevel * 0.13, accent, root.minimumCenterLensOpacity * 0.70)
                centerAperture(radius * root.centerLensRadiusRatio, muted ? root.centerApertureStrength * 0.36 : root.centerApertureStrength + root.effectiveSpeakingLevel * 0.05)
                circle(radius * root.centerLensRadiusRatio * 1.10, sf.anchorStrokePrimary, muted ? 0.08 : 0.20 + pulse * 0.04, accent, root.minimumCenterLensOpacity)
            }
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
        }
    }
}
