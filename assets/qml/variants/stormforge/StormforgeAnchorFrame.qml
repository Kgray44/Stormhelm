import QtQuick 2.15

Item {
    id: root

    property var anchorCore: null
    property int paintCount: 0
    property int requestPaintCount: 0
    property double lastPaintTimeMs: 0
    readonly property string rendererRole: "stormforge_anchor_static_frame"

    function requestFramePaint() {
        if (!root.visible || width <= 0 || height <= 0)
            return
        root.requestPaintCount += 1
        frameCanvas.requestPaint()
    }

    onWidthChanged: requestFramePaint()
    onHeightChanged: requestFramePaint()
    onVisibleChanged: requestFramePaint()
    Component.onCompleted: requestFramePaint()

    StormforgeTokens {
        id: sf
    }

    Canvas {
        id: frameCanvas
        anchors.fill: parent
        antialiasing: true
        renderTarget: Canvas.FramebufferObject
        renderStrategy: Canvas.Threaded

        onPaint: {
            root.paintCount += 1
            root.lastPaintTimeMs = Date.now()
            var core = root.anchorCore
            var ctx = getContext("2d")
            if (ctx.reset)
                ctx.reset()
            ctx.clearRect(0, 0, width, height)
            if (!core || width <= 0 || height <= 0)
                return

            var cx = width / 2
            var cy = height / 2
            var radius = Math.min(width, height) * 0.44
            var targetState = core.visualState
            var sourceState = core.previousVisualState && core.previousVisualState.length > 0 ? core.previousVisualState : targetState
            var transitionBlend = core.transitionBlendProgress
            var transitioning = core.stateTransitionActive && sourceState !== targetState
            var accent = core.accentColor
            var glow = core.haloColor
            var muted = transitioning
                ? (transitionBlend >= 0.5 ? targetState === "unavailable" : sourceState === "unavailable")
                : targetState === "unavailable"

            function activeAlphaForState(stateName) {
                if (stateName === "unavailable")
                    return core.finalAnchorOpacityFloor
                if (stateName === "mock_dev")
                    return 0.58
                if (core.isIdlePresenceState(stateName))
                    return core.idleActiveAlphaFloor
                return 0.78
            }

            var activeAlpha = transitioning
                ? core.mixNumber(activeAlphaForState(sourceState), activeAlphaForState(targetState), transitionBlend)
                : activeAlphaForState(targetState)
            var idleLife = core.idleMotionActive ? core.idlePulseMin + (core.idlePulseMax - core.idlePulseMin) * core.idleBreathValue : 0
            var pulse = core.effectiveIntensity * 0.24 + idleLife
            var ringSoftness = Math.max(0.35, Math.min(0.8, core.visualSoftness))
            var depthShift = muted ? 0 : radius * 0.003
            var horizonShift = muted ? 0 : radius * (core.isIdlePresenceState(targetState) ? sf.anchorIdleBearingDriftStrength * 0.38 : 0)

            function finalAlpha(alpha, minimumFinalAlpha) {
                return Math.max(alpha * activeAlpha, minimumFinalAlpha || 0)
            }

            function circle(radiusValue, lineWidth, alpha, colorValue, minimumFinalAlpha) {
                ctx.beginPath()
                ctx.arc(cx, cy, radiusValue, 0, Math.PI * 2)
                ctx.lineWidth = lineWidth
                ctx.strokeStyle = core.colorString(colorValue || accent, finalAlpha(alpha, minimumFinalAlpha))
                ctx.stroke()
            }

            function filledGlow(radiusValue, alpha, colorValue, minimumFinalAlpha) {
                var gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, radiusValue)
                gradient.addColorStop(0, core.colorString(colorValue || accent, finalAlpha(alpha, minimumFinalAlpha)))
                gradient.addColorStop(0.62, core.colorString(colorValue || accent, finalAlpha(alpha * 0.18, (minimumFinalAlpha || 0) * 0.22)))
                gradient.addColorStop(1, core.colorString(colorValue || accent, 0))
                ctx.beginPath()
                ctx.arc(cx, cy, radiusValue, 0, Math.PI * 2)
                ctx.fillStyle = gradient
                ctx.fill()
            }

            function glassDisc(radiusValue, alpha, minimumFinalAlpha) {
                var floor = minimumFinalAlpha || 0
                var gradient = ctx.createRadialGradient(
                    cx - radiusValue * 0.25,
                    cy - radiusValue * 0.34,
                    radiusValue * 0.12,
                    cx,
                    cy,
                    radiusValue
                )
                gradient.addColorStop(0, core.colorString(sf.textPrimary, finalAlpha(alpha * 0.34, floor * 0.40)))
                gradient.addColorStop(0.30, core.colorString(sf.signalCyan, finalAlpha(alpha * 0.13, floor * 0.26)))
                gradient.addColorStop(0.72, core.colorString(sf.deepBlue, finalAlpha(alpha * 0.46, floor * 0.36)))
                gradient.addColorStop(1, core.colorString(sf.abyss, finalAlpha(alpha * 0.70, floor * 0.30)))
                ctx.beginPath()
                ctx.arc(cx, cy, radiusValue, 0, Math.PI * 2)
                ctx.fillStyle = gradient
                ctx.fill()
            }

            function arc(radiusValue, start, sweep, lineWidth, alpha, colorValue, minimumFinalAlpha) {
                ctx.beginPath()
                ctx.arc(cx, cy, radiusValue, start, start + sweep)
                ctx.lineWidth = lineWidth
                ctx.lineCap = "round"
                ctx.strokeStyle = core.colorString(colorValue || accent, finalAlpha(alpha, minimumFinalAlpha))
                ctx.stroke()
            }

            function depthRim(radiusValue, alpha) {
                ctx.beginPath()
                ctx.arc(cx + depthShift, cy + depthShift, radiusValue, 0, Math.PI * 2)
                ctx.lineWidth = sf.anchorStrokeHeavy + 0.8
                ctx.strokeStyle = core.colorString(sf.abyss, alpha * core.depthShadowOpacity)
                ctx.stroke()
                ctx.beginPath()
                ctx.arc(cx - depthShift * 0.35, cy - depthShift * 0.35, radiusValue * 0.98, 0, Math.PI * 2)
                ctx.lineWidth = sf.anchorStrokePrimary
                ctx.strokeStyle = core.colorString(sf.textPrimary, alpha * 0.12 * activeAlpha)
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

            function etchedSegments(radiusValue, alpha) {
                for (var segment = 0; segment < 6; ++segment) {
                    var start = segment * Math.PI / 3
                    arc(radiusValue, start, Math.PI * 0.16, sf.anchorStrokeHairline, alpha * (segment % 2 === 0 ? 1 : 0.62), segment % 3 === 0 ? accent : sf.lineStrong)
                }
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
                    ctx.strokeStyle = core.colorString(
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
                    ctx.fillStyle = core.colorString(mark === 0 ? accent : sf.lineStrong, (mark === 0 ? alpha : alpha * 0.48) * activeAlpha)
                    ctx.fill()
                    ctx.restore()
                }
                ctx.restore()
            }

            function helmCrown(radiusValue, alpha) {
                var crownColor = targetState === "approval_required" || targetState === "acting" ? sf.brass : accent
                var top = cy - radiusValue * 1.055
                ctx.beginPath()
                ctx.moveTo(cx, top - radiusValue * 0.085)
                ctx.lineTo(cx - radiusValue * 0.044, top + radiusValue * 0.026)
                ctx.lineTo(cx + radiusValue * 0.044, top + radiusValue * 0.026)
                ctx.closePath()
                ctx.fillStyle = core.colorString(crownColor, alpha * activeAlpha)
                ctx.fill()
                ctx.beginPath()
                ctx.moveTo(cx - radiusValue * 0.12, top + radiusValue * 0.055)
                ctx.lineTo(cx - radiusValue * 0.048, top + radiusValue * 0.055)
                ctx.moveTo(cx + radiusValue * 0.048, top + radiusValue * 0.055)
                ctx.lineTo(cx + radiusValue * 0.12, top + radiusValue * 0.055)
                ctx.lineWidth = sf.anchorStrokePrimary
                ctx.lineCap = "round"
                ctx.strokeStyle = core.colorString(sf.lineStrong, alpha * 0.62 * activeAlpha)
                ctx.stroke()
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
                ctx.strokeStyle = core.colorString(sf.lineStrong, alpha * activeAlpha)
                ctx.stroke()
                ctx.beginPath()
                ctx.moveTo(cx, cy - radiusValue * 0.72)
                ctx.lineTo(cx, cy + radiusValue * 0.72)
                ctx.strokeStyle = core.colorString(accent, alpha * 0.62 * activeAlpha)
                ctx.stroke()
                for (var notch = -2; notch <= 2; ++notch) {
                    if (notch === 0)
                        continue
                    ctx.beginPath()
                    ctx.moveTo(cx + notch * radiusValue * 0.16, cy + horizonShift - radiusValue * 0.018)
                    ctx.lineTo(cx + notch * radiusValue * 0.16, cy + horizonShift + radiusValue * 0.018)
                    ctx.strokeStyle = core.colorString(sf.lineStrong, alpha * 0.48 * activeAlpha)
                    ctx.stroke()
                }
                ctx.restore()
            }

            function sonarArcs(alpha) {
                arc(radius * 0.44, Math.PI * 1.05, Math.PI * 0.35, sf.anchorStrokeHairline, alpha * 0.52, sf.lineStrong)
                arc(radius * 0.58, Math.PI * 1.01, Math.PI * 0.44, sf.anchorStrokeHairline, alpha * 0.44, sf.signalCyan)
                arc(radius * 0.72, Math.PI * 0.98, Math.PI * 0.52, sf.anchorStrokeHairline, alpha * 0.34, sf.lineStrong)
            }

            function compassNeedles(radiusValue, alpha) {
                ctx.save()
                ctx.translate(cx, cy)
                for (var arm = 0; arm < 4; ++arm) {
                    ctx.save()
                    ctx.rotate(Math.PI * 0.5 * arm)
                    ctx.beginPath()
                    ctx.moveTo(0, -radiusValue * 0.16)
                    ctx.lineTo(0, -radiusValue * 0.68)
                    ctx.lineWidth = arm === 0 ? sf.anchorStrokeHeavy : sf.anchorStrokePrimary
                    ctx.strokeStyle = core.colorString(arm === 0 ? accent : sf.lineStrong, (arm === 0 ? alpha : alpha * 0.46) * activeAlpha)
                    ctx.stroke()
                    ctx.restore()
                }
                ctx.restore()
            }

            filledGlow(radius * 1.22, 0.075, sf.deepBlue, Math.max(core.minimumRingOpacity * 0.18, core.finalRingOpacity * 0.18))
            filledGlow(radius * 1.15, muted ? core.finalCenterGlowOpacity * 0.42 : sf.anchorHaloOpacity + pulse * 0.020, glow, Math.max(core.minimumRingOpacity * 0.30, core.finalRingOpacity * 0.30))
            glassDisc(radius * 0.96, muted ? core.instrumentGlassOpacity * 0.58 : core.instrumentGlassOpacity, Math.max(core.minimumCenterLensOpacity * 0.48, core.finalBlobOpacity * 0.30))
            filledGlow(radius * 0.70, muted ? core.finalCenterGlowOpacity * 0.64 : Math.max(0.040 + pulse * 0.028, core.isIdlePresenceState(targetState) ? core.idleCenterGlowFloor : 0), accent, Math.max(core.minimumCenterLensOpacity * (core.isIdlePresenceState(targetState) ? 0.56 : 0.30), core.finalCenterGlowOpacity * 0.54))
            depthRim(radius * 1.005, muted ? 0.46 : sf.anchorBezelOpacity)
            outerSignatureClamp(radius * 1.045, muted ? core.finalRingOpacity * 0.44 : core.outerClampStrength + pulse * 0.012, Math.max(core.minimumRingOpacity * 0.62, core.finalRingOpacity * 0.58))
            circle(radius * 1.0, sf.anchorStrokeHairline, muted ? 0.11 : 0.22 + pulse * 0.050, accent, core.finalRingOpacity)
            etchedSegments(radius * 0.91, muted ? 0.035 : 0.135)
            circle(radius * 0.79, sf.anchorStrokePrimary, muted ? 0.09 : 0.22 * ringSoftness, sf.lineStrong, Math.max(core.minimumRingOpacity * 0.70, core.finalRingOpacity * 0.62))
            sonarArcs(muted ? 0.04 : 0.155)
            horizonLine(radius, muted ? 0.045 : sf.anchorHorizonOpacity)
            circle(radius * 0.57, sf.anchorStrokeHairline, muted ? 0.07 : 0.145, accent, Math.max(core.minimumRingOpacity * 0.55, core.finalRingOpacity * 0.48))
            circle(radius * 0.32, sf.anchorStrokePrimary, muted ? 0.10 : 0.26, accent, Math.max(core.minimumCenterLensOpacity, core.finalBlobOpacity * 0.72))
            ticks(radius * 1.0, muted ? 0.10 : 0.25, core.finalBearingTickOpacity)
            quadrantMarks(radius, muted ? 0.07 : 0.20)
            helmCrown(radius, muted ? 0.04 : core.headingMarkerStrength + pulse * 0.018)
            compassNeedles(radius, muted ? 0.075 : 0.155)
        }
    }
}
