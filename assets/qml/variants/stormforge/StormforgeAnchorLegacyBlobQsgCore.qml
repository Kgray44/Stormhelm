import QtQuick 2.15
import QtQuick.Shapes 1.15

Item {
    id: root

    property var anchorCore: null
    property int paintCount: 0
    property int requestPaintCount: 0
    property double lastPaintTimeMs: 0
    property string lastPaintedPlaybackId: ""

    readonly property string rendererRole: "stormforge_anchor_legacy_blob_qsg_candidate"
    readonly property bool canvasFreeDynamicRenderer: true
    readonly property bool usesFullLegacyPaintPath: false
    readonly property bool preservesLegacyBlobReference: true
    readonly property bool legacyBlobCloneRenderer: true
    readonly property string officialLegacyBlobReferenceSource: "legacy_blob_reference_center_aperture"
    readonly property string qsgReflectionParityVersion: "AR10"
    readonly property string qsgReflectionShape: "legacy_glint"
    readonly property bool qsgReflectionRoundedRectDisabled: true
    readonly property bool qsgReflectionUsesLegacyGeometry: true
    readonly property bool qsgReflectionAnimated: true
    readonly property string qsgBlobEdgeFeatherVersion: "AR10"
    readonly property bool qsgBlobEdgeFeatherEnabled: true
    readonly property bool qsgBlobEdgeFeatherMatchesLegacySoftness: true
    readonly property real qsgReflectionOffsetX: root.coreReady ? root.anchorCore.apertureShimmerOffsetX : 0
    readonly property real qsgReflectionOffsetY: root.coreReady ? root.anchorCore.apertureShimmerOffsetY : 0
    readonly property real qsgReflectionOpacity: root.coreReady
        ? (root.muted
            ? Math.max(root.anchorCore.apertureShimmerOpacityMin * 0.48, root.anchorCore.finalCenterGlowOpacity * 0.36)
            : root.anchorCore.apertureShimmerOpacity * (0.90 + root.anchorCore.idleBreathValue * 0.13 + root.speakLevel * 0.22) * root.activeAlpha)
        : 0
    readonly property real qsgReflectionSoftness: sf.anchorApertureShimmerRadiusRatio
    readonly property bool qsgReflectionClipInsideBlob: true
    readonly property real qsgBlobEdgeFeatherOpacity: root.coreReady
        ? root.finalAlpha(
            root.muted ? 0.030 : 0.058 + root.speakLevel * 0.024 + root.speakDynamics * 0.018,
            root.anchorCore.minimumCenterLensOpacity * 0.14
        )
        : 0

    readonly property bool coreReady: root.anchorCore !== null && root.anchorCore !== undefined
    readonly property string qsgRendererPlaybackId: root.coreReady ? root.anchorCore.currentAnchorPlaybackId : ""
    readonly property string qsgRendererReceivedEnergyForPlaybackId: root.qsgRendererPlaybackId
    readonly property string qsgRendererPaintedPlaybackId: root.lastPaintedPlaybackId
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
        ? root.mixNumber(root.activeAlphaForState(root.sourceState), root.activeAlphaForState(root.targetState), root.transitionBlend)
        : root.activeAlphaForState(root.targetState)
    readonly property real stateArrival: root.transitioning ? root.transitionBlend : 1

    readonly property real speakLevel: root.coreReady ? root.anchorCore.finalSpeakingEnergy : 0
    readonly property real speakDynamics: root.coreReady ? root.anchorCore.envelopeExpandedEnergy : 0
    readonly property real speakTransient: root.coreReady ? root.anchorCore.envelopeTransientEnergy : 0
    readonly property real speakReactive: root.coreReady && root.anchorCore.anchorUsesPlaybackEnvelope
        ? root.clamp01(root.speakLevel * 0.44 + root.speakDynamics * 0.82 + root.speakTransient * 0.44)
        : root.speakLevel
    readonly property real outerSpeakLevel: root.coreReady ? root.anchorCore.outerMotionSmoothed : 0

    readonly property bool idleMotionActive: root.coreReady ? root.anchorCore.idleMotionActive : false
    readonly property real idleLife: root.coreReady && root.idleMotionActive
        ? root.anchorCore.idlePulseMin + (root.anchorCore.idlePulseMax - root.anchorCore.idlePulseMin) * root.anchorCore.idleBreathValue
        : 0
    readonly property real organicDriftAngle: root.coreReady
        ? root.anchorCore.organicMotionTimeMs / Math.max(1, root.anchorCore.idleDriftCycleMs) * Math.PI * 2
        : 0
    readonly property real organicOffsetX: root.coreReady && root.idleMotionActive ? root.anchorCore.organicSecondaryValue * root.radius * 0.0063 : 0
    readonly property real organicOffsetY: root.coreReady && root.idleMotionActive ? root.anchorCore.organicDriftValue * root.radius * 0.0051 : 0
    readonly property real blobCx: root.cx + root.organicOffsetX
    readonly property real blobCy: root.cy + root.organicOffsetY
    readonly property real stateSizeBias: root.stateSizeBiasFor(root.targetState)
    readonly property real blobRadiusPx: Math.max(
        root.radius * 0.25,
        root.radius * (root.coreReady ? root.anchorCore.centerLensRadiusRatio : 0.31) * (1.02 + root.stateSizeBias)
    )
    readonly property real blobDeformAmount: root.blobDeformFor(root.targetState)
    readonly property real blobGlowAlpha: root.muted
        ? (root.coreReady ? root.anchorCore.finalCenterGlowOpacity : 0.04)
        : Math.max(
            (sf.anchorBlobGlowOpacity
                + (root.idleMotionActive && root.coreReady ? sf.anchorOrganicGlowShift * root.anchorCore.idleBreathValue : 0)
                + root.speakLevel * 0.36 * (root.coreReady ? root.anchorCore.speakingAudioReactiveStrengthBoost : 1)) * 0.22,
            root.coreReady && root.anchorCore.isIdlePresenceState(root.targetState) ? root.anchorCore.idleCenterGlowFloor : 0
        )
    readonly property real blobAlpha: root.muted
        ? Math.max(root.centerApertureAlpha * 0.42, root.coreReady ? root.anchorCore.finalBlobOpacity : 0)
        : Math.max(root.centerApertureAlpha, root.idleBlobFloor)
    readonly property real idleBlobFloor: root.coreReady && root.anchorCore.isIdlePresenceState(root.targetState)
        ? root.anchorCore.idleBlobOpacityFloor * Math.max(0.18, root.stateArrival)
        : 0
    readonly property real centerApertureAlpha: root.coreReady
        ? (root.muted
            ? root.anchorCore.centerApertureStrength * 0.36
            : root.anchorCore.centerApertureStrength + root.speakLevel * 0.035 + root.speakDynamics * 0.055)
        : 0.55

    readonly property color accentColor: root.coreReady ? root.anchorCore.accentColor : sf.signalCyan
    readonly property color stateRimColor: root.stateColorFor(root.targetState)
    readonly property color glowColor: root.coreReady ? root.anchorCore.haloColor : sf.signalCyan
    readonly property real blobScaleDrive: root.coreReady ? root.anchorCore.blobScaleDrive : 0
    readonly property real blobDeformationDrive: root.coreReady ? root.anchorCore.blobDeformationDrive : 0
    readonly property real blobRadiusScale: root.coreReady ? root.anchorCore.blobRadiusScale : 1
    readonly property real radianceDrive: root.coreReady ? root.anchorCore.radianceDrive : 0
    readonly property real ringDrive: root.coreReady ? root.anchorCore.ringDrive : 0
    readonly property real reflectionX: root.blobCx + root.qsgReflectionOffsetX * root.blobRadiusPx
    readonly property real reflectionY: root.blobCy + root.qsgReflectionOffsetY * root.blobRadiusPx
    readonly property real reflectionRotationRadians: -0.72 + (root.coreReady ? Math.sin(root.anchorCore.apertureShimmerSecondaryPhase) * 0.16 : 0)

    function clamp01(value) {
        var number = Number(value)
        if (!isFinite(number))
            return 0
        return Math.max(0, Math.min(1, number))
    }

    function mixNumber(fromValue, toValue, amount) {
        var t = root.clamp01(amount)
        return Number(fromValue) + (Number(toValue) - Number(fromValue)) * t
    }

    function colorString(colorValue, alphaValue) {
        return Qt.rgba(colorValue.r, colorValue.g, colorValue.b, root.clamp01(alphaValue))
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

    function legacyGlintArcPathString() {
        if (!root.coreReady || width <= 0 || height <= 0)
            return ""
        var start = -Math.PI * 0.76
        var end = Math.PI * 0.42
        var steps = 18
        var radiusValue = root.blobRadiusPx * 0.22
        var scaleX = 1.82
        var scaleY = 0.64
        var cosRot = Math.cos(root.reflectionRotationRadians)
        var sinRot = Math.sin(root.reflectionRotationRadians)
        var path = ""
        for (var index = 0; index <= steps; ++index) {
            var t = start + (end - start) * index / steps
            var localX = Math.cos(t) * radiusValue * scaleX
            var localY = Math.sin(t) * radiusValue * scaleY
            var x = root.reflectionX + localX * cosRot - localY * sinRot
            var y = root.reflectionY + localX * sinRot + localY * cosRot
            path += (index === 0 ? "M " : " L ") + x.toFixed(3) + " " + y.toFixed(3)
        }
        return path
    }

    function ringFragmentAngleDegrees(fragment) {
        if (!root.coreReady)
            return 0
        var cycles = [sf.durationAnchorRingFragmentMin, 26000, 34000, sf.durationAnchorRingFragmentMax]
        var direction = fragment % 2 === 0 ? 1 : -1
        var cycle = cycles[fragment % cycles.length]
        var angle = direction * (root.anchorCore.ringFragmentPhase * Math.PI * 2 / (cycle / 1000.0)) + fragment * Math.PI * 0.56
        return angle * 180 / Math.PI
    }

    function ringFragmentRadiusRatio(fragment) {
        var radii = [0.92, 0.74, 0.61, 0.47]
        return radii[fragment % radii.length]
    }

    function ringFragmentSweepDegrees(fragment) {
        var sweeps = [0.11, 0.085, 0.13, 0.075]
        return Math.PI * sweeps[fragment % sweeps.length] * 180 / Math.PI
    }

    function ringFragmentColor(fragment) {
        if (fragment === 1 && (root.targetState === "approval_required" || root.targetState === "acting"))
            return sf.brass
        if (fragment === 2 && root.targetState === "mock_dev")
            return sf.devViolet
        if (fragment === 3)
            return sf.lineStrong
        return root.accentColor
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
        root.lastPaintedPlaybackId = root.qsgRendererPlaybackId
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
        model: root.coreReady ? root.anchorCore.ringFragmentCount : 0
        Shape {
            anchors.fill: parent
            visible: root.coreReady && root.anchorCore.ringFragmentsActive
            ShapePath {
                strokeWidth: sf.anchorStrokeHairline
                strokeColor: root.colorString(
                    root.ringFragmentColor(index),
                    root.finalAlpha(
                        (root.muted
                            ? root.anchorCore.finalVisibilityFloorForKind("fragment", root.targetState)
                            : Math.max(
                                sf.anchorRingFragmentOpacity + root.idleLife * 0.22 + (root.targetState === "speaking" ? root.speakDynamics * 0.10 : 0),
                                root.anchorCore.isIdlePresenceState(root.targetState)
                                    ? root.anchorCore.idleFragmentOpacityFloor
                                    : root.anchorCore.finalVisibilityFloorForKind("fragment", root.targetState)
                            )) * (1 - index * 0.12),
                        0
                    )
                )
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathAngleArc {
                    centerX: root.cx
                    centerY: root.cy
                    radiusX: root.radius * root.ringFragmentRadiusRatio(index)
                    radiusY: radiusX
                    startAngle: root.ringFragmentAngleDegrees(index)
                    sweepAngle: root.ringFragmentSweepDegrees(index)
                }
            }
        }
    }

    Shape {
        anchors.fill: parent
        visible: root.coreReady && root.profileFor(root.targetState) === "radiating"
        ShapePath {
            strokeWidth: sf.anchorStrokePrimary + root.radianceDrive * 1.12 * (root.coreReady ? root.anchorCore.speakingAudioReactiveStrengthBoost : 1)
            strokeColor: root.colorString(root.accentColor, (0.10 + root.radianceDrive * 0.19) * root.anchorCore.speakingExpressionBoost * root.stateArrival * root.activeAlpha)
            fillColor: "transparent"
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.radius * (0.46 + root.radianceDrive * 0.11 * root.anchorCore.speakingAudioReactiveStrengthBoost + Math.sin(root.anchorCore.speakingPhase * 0.72) * (0.006 + root.speakDynamics * 0.010))
                radiusY: radiusX
                startAngle: 0
                sweepAngle: 360
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline + root.radianceDrive * 0.50 * root.anchorCore.speakingAudioReactiveStrengthBoost
            strokeColor: root.colorString(root.accentColor, (0.06 + root.radianceDrive * 0.14) * root.anchorCore.speakingExpressionBoost * root.stateArrival * root.activeAlpha)
            fillColor: "transparent"
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.radius * (0.65 + root.radianceDrive * 0.07 * root.anchorCore.speakingAudioReactiveStrengthBoost + Math.sin(root.anchorCore.speakingPhase * 0.58 + 0.8) * (0.005 + root.speakDynamics * 0.009))
                radiusY: radiusX
                startAngle: 0
                sweepAngle: 360
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline
            strokeColor: root.colorString(sf.signalCyan, (0.10 + root.radianceDrive * 0.13) * root.anchorCore.speakingExpressionBoost * root.stateArrival * root.activeAlpha)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.radius * 0.86
                radiusY: radiusX
                startAngle: -130
                sweepAngle: (0.12 + root.radianceDrive * 0.10 * root.anchorCore.speakingAudioReactiveStrengthBoost) * 180
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline
            strokeColor: root.colorString(sf.seaGreen, (0.06 + root.radianceDrive * 0.11) * root.anchorCore.speakingExpressionBoost * root.stateArrival * root.activeAlpha)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.radius * 0.98
                radiusY: radiusX
                startAngle: root.anchorCore.speakingPhase * 17.1887 + 40
                sweepAngle: (0.08 + (root.outerSpeakLevel * 0.06 + root.speakDynamics * 0.14) * root.anchorCore.speakingAudioReactiveStrengthBoost) * 180
            }
        }
    }

    Repeater {
        model: 3
        Rectangle {
            readonly property real scaleFactor: index === 0 ? 2.26 : index === 1 ? 1.72 : 1.28
            width: root.blobRadiusPx * scaleFactor * (1 + root.speakLevel * 0.10)
            height: width
            x: root.blobCx - width / 2
            y: root.blobCy - height / 2
            radius: width / 2
            color: root.colorString(
                index === 0 ? root.stateRimColor : index === 1 ? sf.signalCyan : sf.deepBlue,
                root.finalAlpha(root.blobGlowAlpha * (index === 0 ? 0.16 : index === 1 ? 0.08 : 0.12), (root.coreReady ? root.anchorCore.minimumCenterLensOpacity : 0) * 0.04)
            )
            visible: root.coreReady
        }
    }

    Rectangle {
        width: root.blobRadiusPx * 2.40
        height: width
        x: root.blobCx + root.radius * 0.018 - width / 2
        y: root.blobCy + root.radius * 0.026 - height / 2
        radius: width / 2
        color: root.colorString(sf.abyss, root.blobAlpha * sf.anchorCenterLensShadowOpacity)
        visible: root.coreReady
    }

    Shape {
        anchors.fill: parent
        visible: root.coreReady
        ShapePath {
            strokeWidth: 0
            fillGradient: RadialGradient {
                centerX: root.blobCx
                centerY: root.blobCy
                centerRadius: root.blobRadiusPx * 1.18
                focalX: root.blobCx - root.blobRadiusPx * 0.22
                focalY: root.blobCy - root.blobRadiusPx * 0.30
                focalRadius: root.blobRadiusPx * 0.08
                GradientStop { position: 0.00; color: root.colorString(sf.textPrimary, root.finalAlpha(root.blobAlpha * 0.62, root.coreReady ? root.anchorCore.finalBlobOpacity * 0.48 : 0)) }
                GradientStop { position: 0.18; color: root.colorString(root.stateRimColor, root.finalAlpha(root.blobAlpha * (0.82 + root.speakLevel * 0.20 * (root.coreReady ? root.anchorCore.speakingAudioReactiveStrengthBoost : 1)), root.coreReady ? root.anchorCore.finalBlobOpacity * 0.64 : 0)) }
                GradientStop { position: 0.56; color: root.colorString(sf.signalCyan, root.finalAlpha(root.blobAlpha * 0.30, root.coreReady ? root.anchorCore.finalBlobOpacity * 0.30 : 0)) }
                GradientStop { position: 0.78; color: root.colorString(sf.deepBlue, root.finalAlpha(root.blobAlpha * 0.70, root.coreReady ? root.anchorCore.finalBlobOpacity * 0.42 : 0)) }
                GradientStop { position: 1.00; color: root.colorString(sf.abyss, root.finalAlpha(root.blobAlpha * 0.92, root.coreReady ? root.anchorCore.finalBlobOpacity * 0.36 : 0)) }
            }
            PathSvg {
                path: root.blobPathString(1.0, root.organicDriftAngle * 0.06)
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokePrimary + (root.targetState === "approval_required" ? 0.55 : 0) + (root.qsgBlobEdgeFeatherEnabled ? 0.22 : 0)
            strokeColor: root.colorString(root.stateRimColor, root.finalAlpha(root.muted ? 0.16 : sf.anchorBlobRimOpacity + root.speakLevel * 0.24 * (root.coreReady ? root.anchorCore.speakingAudioReactiveStrengthBoost : 1) + root.qsgBlobEdgeFeatherOpacity * 0.18, root.coreReady ? root.anchorCore.minimumCenterLensOpacity : 0))
            fillColor: "transparent"
            PathSvg {
                path: root.blobPathString(1.018, root.organicDriftAngle * 0.06)
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline
            strokeColor: root.colorString(sf.lineStrong, root.finalAlpha(root.muted ? 0.08 : 0.12 + (root.coreReady ? root.anchorCore.idleBreathValue : 0) * 0.05, root.coreReady ? root.anchorCore.minimumCenterLensOpacity * 0.38 : 0))
            fillColor: "transparent"
            PathSvg {
                path: root.blobPathString(0.68, -root.organicDriftAngle * 0.08)
            }
        }
    }

    Shape {
        anchors.fill: parent
        visible: root.coreReady
        ShapePath {
            strokeWidth: 0
            fillGradient: RadialGradient {
                centerX: root.reflectionX
                centerY: root.reflectionY
                centerRadius: root.blobRadiusPx * sf.anchorApertureShimmerRadiusRatio
                focalX: root.reflectionX - root.blobRadiusPx * 0.035
                focalY: root.reflectionY - root.blobRadiusPx * 0.030
                focalRadius: root.blobRadiusPx * 0.010
                GradientStop { position: 0.00; color: root.colorString(sf.textPrimary, root.qsgReflectionOpacity * 0.78) }
                GradientStop { position: 0.34; color: root.colorString(root.stateRimColor, root.qsgReflectionOpacity * 0.48) }
                GradientStop { position: 0.72; color: root.colorString(sf.signalCyan, root.qsgReflectionOpacity * 0.20) }
                GradientStop { position: 1.00; color: root.colorString(sf.signalCyan, 0) }
            }
            PathSvg {
                path: root.blobPathString(0.94, root.organicDriftAngle * 0.06)
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline + 0.08
            strokeColor: root.colorString(sf.textPrimary, root.qsgReflectionOpacity * 0.76)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg {
                path: root.legacyGlintArcPathString()
            }
        }
    }

    Shape {
        anchors.fill: parent
        visible: root.coreReady
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline
            strokeColor: root.colorString(sf.lineStrong, (root.muted ? root.anchorCore.finalBearingTickOpacity * 0.34 : 0.080) * root.activeAlpha)
            fillColor: "transparent"
            PathMove { x: root.blobCx - root.blobRadiusPx * 0.42; y: root.blobCy }
            PathLine { x: root.blobCx + root.blobRadiusPx * 0.42; y: root.blobCy }
            PathMove { x: root.blobCx; y: root.blobCy - root.blobRadiusPx * 0.42 }
            PathLine { x: root.blobCx; y: root.blobCy + root.blobRadiusPx * 0.42 }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline
            strokeColor: root.colorString(sf.textPrimary, root.muted ? 0.04 : 0.15 + root.anchorCore.apertureShimmerOpacity * 0.62)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.blobCx
                centerY: root.blobCy
                radiusX: root.blobRadiusPx * 0.88
                radiusY: radiusX
                startAngle: -130 + Math.sin(root.anchorCore.organicMotionTimeMs / Math.max(1, sf.durationAnchorBlobShimmer) * 360) * 1.0
                sweepAngle: 61
            }
        }
    }

    Shape {
        anchors.fill: parent
        visible: root.coreReady && root.targetState === "speaking"
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline + root.speakReactive * 0.20 * root.anchorCore.speakingAudioReactiveStrengthBoost
            strokeColor: root.colorString(root.accentColor, (0.11 + root.speakReactive * 0.16) * root.anchorCore.speakingExpressionBoost * root.stateArrival * root.activeAlpha)
            fillColor: "transparent"
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.blobRadiusPx * (0.82 + root.speakReactive * 0.070 * root.anchorCore.speakingAudioReactiveStrengthBoost)
                radiusY: radiusX
                startAngle: 0
                sweepAngle: 360
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline + (root.outerSpeakLevel * 0.08 + root.speakDynamics * 0.10) * root.anchorCore.speakingAudioReactiveStrengthBoost
            strokeColor: root.colorString(sf.signalCyan, (0.07 + root.speakReactive * 0.12) * root.anchorCore.speakingExpressionBoost * root.stateArrival * root.activeAlpha)
            fillColor: "transparent"
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.blobRadiusPx * (1.34 + (root.outerSpeakLevel * 0.05 + root.speakDynamics * 0.10) * root.anchorCore.speakingAudioReactiveStrengthBoost)
                radiusY: radiusX
                startAngle: 0
                sweepAngle: 360
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline
            strokeColor: root.colorString(sf.signalCyan, (0.10 + root.speakReactive * 0.15) * root.anchorCore.speakingExpressionBoost * root.stateArrival * root.activeAlpha)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.blobRadiusPx * 1.58
                radiusY: radiusX
                startAngle: root.anchorCore.speakingPhase * 28.6479
                sweepAngle: (0.16 + root.speakReactive * 0.24 * root.anchorCore.speakingAudioReactiveStrengthBoost) * 180
            }
        }
        ShapePath {
            strokeWidth: sf.anchorStrokeHairline
            strokeColor: root.colorString(sf.seaGreen, (0.06 + root.speakReactive * 0.11) * root.anchorCore.speakingExpressionBoost * root.stateArrival * root.activeAlpha)
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: root.cx
                centerY: root.cy
                radiusX: root.blobRadiusPx * 1.82
                radiusY: radiusX
                startAngle: -root.anchorCore.speakingPhase * 19.4806 + 27
                sweepAngle: (0.09 + (root.outerSpeakLevel * 0.08 + root.speakDynamics * 0.14) * root.anchorCore.speakingAudioReactiveStrengthBoost) * 180
            }
        }
    }

    Shape {
        anchors.fill: parent
        visible: root.coreReady && root.targetState !== "speaking"
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
                root.muted && root.coreReady
                    ? root.anchorCore.finalSignalPointOpacity
                    : (root.coreReady ? root.anchorCore.centerPearlStrength + (root.idleMotionActive ? sf.anchorIdleLensPulseStrength * (0.35 + root.anchorCore.idleBreathValue * 0.65) : 0) : 0.5) * root.activeAlpha,
                root.coreReady ? root.anchorCore.minimumSignalPointOpacity : 0.2
            )
        )
        visible: root.coreReady
    }
}
