import QtQuick 2.15
import QtQuick.Shapes 1.15

Item {
    id: root

    property var anchorCore: null
    property int paintCount: 0
    property int requestPaintCount: 0
    property double lastPaintTimeMs: 0
    readonly property string rendererRole: "stormforge_anchor_dynamic_core_shape_renderer"
    readonly property bool canvasFreeDynamicRenderer: true

    readonly property bool coreReady: root.anchorCore !== null && root.anchorCore !== undefined
    readonly property real faceSize: Math.max(1, Math.min(width, height))
    readonly property real cx: width / 2
    readonly property real cy: height / 2
    readonly property real radius: root.faceSize * 0.44
    readonly property string targetState: root.coreReady ? root.anchorCore.visualState : "idle"
    readonly property string sourceState: root.coreReady && root.anchorCore.previousVisualState && root.anchorCore.previousVisualState.length > 0 ? root.anchorCore.previousVisualState : root.targetState
    readonly property real transitionBlend: root.coreReady ? root.anchorCore.transitionBlendProgress : 1
    readonly property bool transitioning: root.coreReady && root.anchorCore.stateTransitionActive && root.sourceState !== root.targetState
    readonly property bool muted: root.transitioning
        ? (root.transitionBlend >= 0.5 ? root.targetState === "unavailable" : root.sourceState === "unavailable")
        : root.targetState === "unavailable"
    readonly property real activeAlpha: root.transitioning
        ? mixNumber(root.activeAlphaForState(root.sourceState), root.activeAlphaForState(root.targetState), root.transitionBlend)
        : root.activeAlphaForState(root.targetState)
    readonly property bool idleMotionActive: root.coreReady ? root.anchorCore.idleMotionActive : false
    readonly property real idleLife: root.coreReady && root.idleMotionActive
        ? root.anchorCore.idlePulseMin + (root.anchorCore.idlePulseMax - root.anchorCore.idlePulseMin) * root.anchorCore.idleBreathValue
        : 0
    readonly property real stateArrival: root.transitioning ? root.transitionBlend : 1
    readonly property real speakLevel: root.coreReady ? root.anchorCore.finalSpeakingEnergy : 0
    readonly property real speakDynamics: root.coreReady ? root.anchorCore.envelopeExpandedEnergy : 0
    readonly property real speakTransient: root.coreReady ? root.anchorCore.envelopeTransientEnergy : 0
    readonly property real speakReactive: root.coreReady && root.anchorCore.anchorUsesPlaybackEnvelope
        ? clamp01(root.speakLevel * 0.44 + root.speakDynamics * 0.82 + root.speakTransient * 0.44)
        : root.speakLevel
    readonly property real pulse: root.coreReady
        ? root.anchorCore.effectiveIntensity * 0.22
            + root.speakLevel * 0.18
            + root.speakDynamics * 0.22
            + root.speakTransient * 0.14
            + root.anchorCore.effectiveAudioLevel * 0.10
            + root.idleLife
        : 0
    readonly property real organicDriftAngle: root.coreReady
        ? root.anchorCore.organicMotionTimeMs / Math.max(1, root.anchorCore.idleDriftCycleMs) * Math.PI * 2
        : 0
    readonly property real organicOffsetX: root.coreReady && root.idleMotionActive ? root.anchorCore.organicSecondaryValue * root.radius * 0.0063 : 0
    readonly property real organicOffsetY: root.coreReady && root.idleMotionActive ? root.anchorCore.organicDriftValue * root.radius * 0.0051 : 0
    readonly property real blobCx: root.cx + root.organicOffsetX
    readonly property real blobCy: root.cy + root.organicOffsetY
    readonly property real stateSizeBias: root.stateSizeBiasFor(root.targetState)
    readonly property real blobRadiusPx: Math.max(root.radius * 0.25, root.radius * (root.coreReady ? root.anchorCore.centerLensRadiusRatio : 0.31) * (1.02 + root.stateSizeBias))
    readonly property real blobGlowRadiusPx: root.blobRadiusPx * (1.82 + root.speakLevel * 0.34 * (root.coreReady ? root.anchorCore.speakingAudioReactiveStrengthBoost : 1))
    readonly property real blobDeformAmount: root.blobDeformFor(root.targetState)
    readonly property real blobScaleDrive: clamp01(root.speakLevel * 0.82 + root.speakDynamics * 0.18 + root.speakTransient * 0.10)
    readonly property real blobDeformationDrive: clamp01(
        (root.targetState === "speaking" ? root.speakLevel * 0.56 + root.speakDynamics * 0.78 + root.speakTransient * 0.34 : 0)
        + (root.idleMotionActive && root.coreReady ? root.anchorCore.idleBreathValue * 0.14 : 0)
    )
    readonly property real blobRadiusScale: root.blobRadiusPx / Math.max(1, root.radius * (root.coreReady ? root.anchorCore.centerLensRadiusRatio : 0.31))
    readonly property real radianceDrive: clamp01(root.targetState === "speaking"
        ? root.speakReactive
        : (root.coreReady && root.anchorCore.motionProfile === "listening_wave" ? root.anchorCore.effectiveAudioLevel * 0.42 : root.pulse * 0.20))
    readonly property real ringDrive: clamp01(0.18 + root.radianceDrive * 0.54 + (root.coreReady ? root.anchorCore.outerMotionSmoothed : 0) * 0.18 + root.speakDynamics * 0.18)
    readonly property color accentColor: root.coreReady ? root.anchorCore.accentColor : sf.signalCyan
    readonly property color stateRimColor: root.stateColorFor(root.targetState)

    function clamp01(value) {
        var number = Number(value)
        if (!isFinite(number))
            return 0
        return Math.max(0, Math.min(1, number))
    }

    function mixNumber(fromValue, toValue, amount) {
        var t = clamp01(amount)
        return Number(fromValue) + (Number(toValue) - Number(fromValue)) * t
    }

    function colorString(colorValue, alphaValue) {
        return Qt.rgba(colorValue.r, colorValue.g, colorValue.b, clamp01(alphaValue))
    }

    function activeAlphaForState(stateName) {
        if (!root.coreReady)
            return 0.78
        if (stateName === "unavailable")
            return root.anchorCore.finalAnchorOpacityFloor
        if (stateName === "mock_dev")
            return 0.58
        if (root.anchorCore.isIdlePresenceState(stateName))
            return root.anchorCore.idleActiveAlphaFloor
        return 0.78
    }

    function finalAlpha(alpha, minimumFinalAlpha) {
        return Math.max(alpha * root.activeAlpha, minimumFinalAlpha || 0)
    }

    function stateColorFor(stateName) {
        if (stateName === "approval_required" || stateName === "acting")
            return sf.brass
        if (stateName === "blocked")
            return sf.amber
        if (stateName === "failed")
            return sf.danger
        if (stateName === "mock_dev")
            return sf.devViolet
        return root.accentColor
    }

    function stateSizeBiasFor(stateName) {
        if (!root.coreReady)
            return 0.025
        if (stateName === "listening" || stateName === "capturing")
            return 0.07 + root.anchorCore.effectiveAudioLevel * 0.04
        if (stateName === "speaking")
            return 0.055 + root.speakLevel * 0.045 + root.speakDynamics * 0.040 + root.speakTransient * 0.028
        if (stateName === "transcribing")
            return 0.045
        if (stateName === "thinking")
            return 0.030
        if (stateName === "acting")
            return 0.035
        if (stateName === "approval_required")
            return 0.015
        if (stateName === "blocked")
            return 0.005
        if (stateName === "failed")
            return 0.010
        if (stateName === "mock_dev")
            return 0.035
        if (stateName === "unavailable")
            return -0.12
        return 0.025
    }

    function blobDeformFor(stateName) {
        if (!root.coreReady || root.muted)
            return 0.010
        if (stateName === "speaking") {
            return sf.anchorBlobSpeakingDeformStrength
                * (0.54 + root.speakLevel * 0.24 + root.speakDynamics * 1.08 + root.speakTransient * 0.55)
        }
        if (root.idleMotionActive)
            return sf.anchorBlobIdleDeformStrength
        return sf.anchorBlobDeformStrength * (0.72 + root.anchorCore.effectiveIntensity * 0.40)
    }

    function blobRadiusAt(angle, pointIndex) {
        if (!root.coreReady)
            return 1
        var audioRipple = root.targetState === "speaking"
            ? (root.speakLevel * 0.024 + root.speakDynamics * 0.074 + root.speakTransient * 0.050)
                * root.anchorCore.speakingAudioReactiveStrengthBoost
                * Math.sin(angle * 5.0 + root.anchorCore.speakingPhase * 1.75)
            : 0
        var receiveRipple = root.targetState === "listening" || root.targetState === "capturing"
            ? root.anchorCore.effectiveAudioLevel * 0.030 * Math.sin(angle * 4.0 + root.anchorCore.wavePhase)
            : 0
        var diagnostic = root.targetState === "failed" && pointIndex % 9 === 0 ? -0.070 : 0
        var blobTime = root.anchorCore.organicMotionTimeMs
        var blobPrimary = blobTime / Math.max(1, root.anchorCore.blobPrimaryCycleMs) * Math.PI * 2
        var blobSecondary = blobTime / Math.max(1, root.anchorCore.blobSecondaryCycleMs) * Math.PI * 2
        var blobDrift = blobTime / Math.max(1, root.anchorCore.blobDriftCycleMs) * Math.PI * 2
        return 1
            + root.blobDeformAmount * Math.sin(angle * 2.0 + blobPrimary)
            + root.blobDeformAmount * 0.58 * Math.sin(angle * 3.0 - blobSecondary + 0.8)
            + root.blobDeformAmount * 0.36 * Math.sin(angle * 5.0 + blobDrift * 0.72)
            + audioRipple
            + receiveRipple
            + diagnostic
    }

    function blobPathString(radiusScale, phaseOffset) {
        if (!root.coreReady || width <= 0 || height <= 0)
            return ""
        var points = Math.max(12, root.anchorCore.blobPointCount)
        var coords = []
        for (var point = 0; point < points; ++point) {
            var angle = Math.PI * 2 * point / points + phaseOffset
            var localRadius = root.blobRadiusPx * radiusScale * root.blobRadiusAt(angle, point)
            coords.push({
                "x": root.blobCx + Math.cos(angle) * localRadius,
                "y": root.blobCy + Math.sin(angle) * localRadius
            })
        }
        if (coords.length <= 0)
            return ""
        var firstMidX = (coords[0].x + coords[1 % coords.length].x) * 0.5
        var firstMidY = (coords[0].y + coords[1 % coords.length].y) * 0.5
        var path = "M " + firstMidX.toFixed(3) + " " + firstMidY.toFixed(3)
        for (var index = 0; index < coords.length; ++index) {
            var next = coords[(index + 1) % coords.length]
            var after = coords[(index + 2) % coords.length]
            var midX = (next.x + after.x) * 0.5
            var midY = (next.y + after.y) * 0.5
            path += " Q " + next.x.toFixed(3) + " " + next.y.toFixed(3)
                + " " + midX.toFixed(3) + " " + midY.toFixed(3)
        }
        return path + " Z"
    }

    function profileFor(stateName) {
        if (root.coreReady && root.anchorCore.profileForState)
            return root.anchorCore.profileForState(stateName)
        return stateName === "speaking" ? "radiating" : "breathing"
    }

    function requestDynamicPaint() {
        if (!root.visible || width <= 0 || height <= 0)
            return
        root.requestPaintCount += 1
        root.noteDynamicFrame(Date.now())
    }

    function noteDynamicFrame(now) {
        root.paintCount += 1
        root.lastPaintTimeMs = now
        if (root.coreReady && root.anchorCore.noteAnchorDynamicPaint)
            root.anchorCore.noteAnchorDynamicPaint(now)
    }

    onWidthChanged: requestDynamicPaint()
    onHeightChanged: requestDynamicPaint()
    onVisibleChanged: requestDynamicPaint()
    Component.onCompleted: requestDynamicPaint()

    StormforgeTokens {
        id: sf
    }

    Repeater {
        model: 5
        Rectangle {
            readonly property real sizeFactor: 1.05 + index * 0.24 + root.radianceDrive * 0.24
            width: root.blobGlowRadiusPx * sizeFactor
            height: width
            x: root.blobCx - width / 2
            y: root.blobCy - height / 2
            radius: width / 2
            color: root.colorString(root.stateRimColor, (0.030 - index * 0.004 + root.radianceDrive * 0.014) * root.activeAlpha)
            visible: root.coreReady
        }
    }

    Repeater {
        model: 4
        Shape {
            anchors.fill: parent
            visible: root.coreReady
            ShapePath {
                strokeWidth: sf.anchorStrokeHairline + (index === 0 ? root.radianceDrive * 0.42 : 0)
                strokeColor: root.colorString(
                    index === 1 ? sf.signalCyan : index === 2 ? sf.seaGreen : root.accentColor,
                    (0.16 - index * 0.025 + root.radianceDrive * 0.16) * root.activeAlpha
                )
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathAngleArc {
                    centerX: root.cx
                    centerY: root.cy
                    radiusX: root.radius * (0.44 + index * 0.13 + root.radianceDrive * (0.035 + index * 0.010))
                    radiusY: radiusX
                    startAngle: -120 + index * 82 + (root.coreReady ? root.anchorCore.speakingPhase * (12 - index * 2) : 0)
                    sweepAngle: 34 + root.radianceDrive * (24 - index * 3)
                }
            }
        }
    }

    Repeater {
        model: root.coreReady ? root.anchorCore.ringFragmentCount : 0
        Shape {
            anchors.fill: parent
            visible: root.coreReady && root.anchorCore.ringFragmentsActive
            readonly property var cycles: [sf.durationAnchorRingFragmentMin, 26000, 34000, sf.durationAnchorRingFragmentMax]
            readonly property var radii: [0.92, 0.74, 0.61, 0.47]
            readonly property var sweeps: [20, 15, 23, 14]
            readonly property int direction: index % 2 === 0 ? 1 : -1
            readonly property real cycle: cycles[index % cycles.length]
            readonly property real angle: direction * (root.anchorCore.ringFragmentPhase * 360 / (cycle / 1000.0)) + index * 32
            ShapePath {
                strokeWidth: sf.anchorStrokeHairline
                strokeColor: root.colorString(
                    index === 1 && (root.targetState === "approval_required" || root.targetState === "acting") ? sf.brass
                        : index === 2 && root.targetState === "mock_dev" ? sf.devViolet
                        : index === 3 ? sf.lineStrong : root.accentColor,
                    (0.20 + root.ringDrive * 0.12) * (1 - index * 0.12) * root.activeAlpha
                )
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathAngleArc {
                    centerX: root.cx
                    centerY: root.cy
                    radiusX: root.radius * radii[index % radii.length]
                    radiusY: radiusX
                    startAngle: angle
                    sweepAngle: sweeps[index % sweeps.length]
                }
            }
        }
    }

    Item {
        id: waveformLayer
        anchors.fill: parent
        visible: root.coreReady
            && (root.profileFor(root.targetState) === "radiating"
                || root.profileFor(root.targetState) === "listening_wave")
        Repeater {
            model: 24
            Rectangle {
                readonly property real angle: Math.PI * 2 * index / 24
                readonly property real carrier: root.coreReady ? 0.38 + Math.abs(Math.sin(root.anchorCore.wavePhase * 1.12 + index * 0.58)) * 0.48 : 0.5
                readonly property real spokeRadius: root.radius * 0.40
                width: sf.anchorStrokePrimary
                height: root.radius * (0.016 + carrier * (0.024 + Math.max(root.radianceDrive, root.coreReady ? root.anchorCore.effectiveAudioLevel : 0) * 0.062))
                radius: width / 2
                color: root.colorString(root.accentColor, (0.11 + root.radianceDrive * 0.16) * (0.35 + carrier * 0.55) * root.activeAlpha)
                x: root.cx + Math.cos(angle) * spokeRadius - width / 2
                y: root.cy + Math.sin(angle) * spokeRadius - height
                transformOrigin: Item.Bottom
                rotation: angle * 180 / Math.PI + 90
            }
        }
    }

    Shape {
        anchors.fill: parent
        visible: root.coreReady
        ShapePath {
            strokeWidth: 0
            fillColor: root.colorString(sf.abyss, (root.muted ? 0.18 : 0.28) * root.activeAlpha)
            PathSvg {
                path: root.blobPathString(1.18, root.organicDriftAngle * 0.04)
            }
        }
        ShapePath {
            strokeWidth: 0
            fillColor: root.colorString(root.stateRimColor, finalAlpha((root.muted ? 0.16 : 0.50 + root.speakLevel * 0.18), root.coreReady ? root.anchorCore.finalBlobOpacity * 0.42 : 0))
            PathSvg {
                path: root.blobPathString(1.0, root.organicDriftAngle * 0.06)
            }
        }
        ShapePath {
            strokeWidth: 0
            fillColor: root.colorString(sf.textPrimary, finalAlpha(root.muted ? 0.05 : 0.12 + root.speakLevel * 0.08, root.coreReady ? root.anchorCore.finalBlobOpacity * 0.18 : 0))
            PathSvg {
                path: root.blobPathString(0.62, -root.organicDriftAngle * 0.05)
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokePrimary + (root.targetState === "approval_required" ? 0.55 : 0) + root.radianceDrive * 0.22
            strokeColor: root.colorString(root.stateRimColor, finalAlpha(root.muted ? 0.16 : sf.anchorBlobRimOpacity + root.speakLevel * 0.24 * (root.coreReady ? root.anchorCore.speakingAudioReactiveStrengthBoost : 1), root.coreReady ? root.anchorCore.minimumCenterLensOpacity : 0))
            fillColor: "transparent"
            PathSvg {
                path: root.blobPathString(1.018, root.organicDriftAngle * 0.06)
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline
            strokeColor: root.colorString(sf.lineStrong, finalAlpha(root.muted ? 0.08 : 0.12 + (root.coreReady ? root.anchorCore.idleBreathValue : 0) * 0.05, root.coreReady ? root.anchorCore.minimumCenterLensOpacity * 0.38 : 0))
            fillColor: "transparent"
            PathSvg {
                path: root.blobPathString(0.68, -root.organicDriftAngle * 0.08)
            }
        }
    }

    Rectangle {
        width: root.blobRadiusPx * 0.72
        height: root.blobRadiusPx * 0.30
        radius: height / 2
        x: root.blobCx + (root.coreReady ? root.anchorCore.apertureShimmerOffsetX : 0) * root.blobRadiusPx - width / 2
        y: root.blobCy + (root.coreReady ? root.anchorCore.apertureShimmerOffsetY : 0) * root.blobRadiusPx - height / 2
        rotation: -42 + (root.coreReady ? Math.sin(root.anchorCore.apertureShimmerSecondaryPhase) * 9 : 0)
        color: root.colorString(sf.textPrimary, (root.muted ? 0.05 : 0.12 + (root.coreReady ? root.anchorCore.apertureShimmerOpacity : 0) * 0.58 + root.speakLevel * 0.04) * root.activeAlpha)
        visible: root.coreReady
    }

    Shape {
        anchors.fill: parent
        visible: root.coreReady
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline
            strokeColor: root.colorString(sf.lineStrong, (root.muted ? 0.035 : 0.080) * root.activeAlpha)
            fillColor: "transparent"
            PathMove { x: root.blobCx - root.blobRadiusPx * 0.42; y: root.blobCy }
            PathLine { x: root.blobCx + root.blobRadiusPx * 0.42; y: root.blobCy }
            PathMove { x: root.blobCx; y: root.blobCy - root.blobRadiusPx * 0.42 }
            PathLine { x: root.blobCx; y: root.blobCy + root.blobRadiusPx * 0.42 }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline + root.radianceDrive * 0.20
            strokeColor: root.colorString(root.accentColor, (0.12 + root.radianceDrive * 0.22) * root.activeAlpha)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.blobRadiusPx * (1.58 + root.radianceDrive * 0.22)
                radiusY: radiusX
                startAngle: root.coreReady ? root.anchorCore.speakingPhase * 28 : 0
                sweepAngle: root.targetState === "speaking" ? 30 + root.radianceDrive * 42 : 0
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline
            strokeColor: root.colorString(sf.seaGreen, (0.07 + root.radianceDrive * 0.14) * root.activeAlpha)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.blobRadiusPx * (1.82 + root.radianceDrive * 0.18)
                radiusY: radiusX
                startAngle: root.coreReady ? -root.anchorCore.speakingPhase * 19 + 22 : 22
                sweepAngle: root.targetState === "speaking" ? 22 + root.radianceDrive * 32 : 0
            }
        }
    }

    Shape {
        anchors.fill: parent
        visible: root.coreReady && root.profileFor(root.targetState) !== "radiating"
        ShapePath {
            strokeWidth: root.profileFor(root.targetState) === "directional_trace" ? sf.anchorStrokeHeavy : sf.anchorStrokePrimary
            strokeColor: root.colorString(
                root.profileFor(root.targetState) === "directional_trace" ? sf.brass
                    : root.profileFor(root.targetState) === "approval_halo" ? sf.amber
                    : root.profileFor(root.targetState) === "warning_halo" ? sf.amber
                    : root.profileFor(root.targetState) === "failure" ? sf.danger
                    : root.profileFor(root.targetState) === "dev_trace" ? sf.devViolet
                    : root.accentColor,
                0.20 * root.stateArrival * root.activeAlpha
            )
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.radius * (
                    root.profileFor(root.targetState) === "orbit" ? 0.71
                    : root.profileFor(root.targetState) === "alignment" ? 0.88
                    : root.profileFor(root.targetState) === "directional_trace" ? 0.88
                    : 0.91
                )
                radiusY: radiusX
                startAngle: root.profileFor(root.targetState) === "orbit" && root.coreReady ? root.anchorCore.orbit * 57.2958 : 12
                sweepAngle: root.profileFor(root.targetState) === "failure" ? 26
                    : root.profileFor(root.targetState) === "warning_halo" ? 34
                    : root.profileFor(root.targetState) === "approval_halo" ? 45
                    : 40
            }
        }
    }

    Rectangle {
        width: Math.max(2.2, root.blobRadiusPx * (0.13 + root.speakLevel * 0.025))
        height: width
        radius: width / 2
        x: root.blobCx - width / 2
        y: root.blobCy - height / 2
        color: root.colorString(
            root.stateRimColor,
            Math.max(
                root.muted && root.coreReady ? root.anchorCore.finalSignalPointOpacity : (root.coreReady ? root.anchorCore.centerPearlStrength + (root.idleMotionActive ? sf.anchorIdleLensPulseStrength * (0.35 + root.anchorCore.idleBreathValue * 0.65) : 0) : 0.5) * root.activeAlpha,
                root.coreReady ? root.anchorCore.minimumSignalPointOpacity : 0.2
            )
        )
        visible: root.coreReady
    }
}
