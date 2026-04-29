import QtQuick 2.15

Item {
    id: root

    signal requestDeck()
    signal requestGhost()

    property string assistantState: "idle"
    property var voiceState: ({})
    property string anchorState: "idle"
    property bool speakingActive: false
    property real motionIntensity: 0.12
    property real audioLevel: 0
    property real smoothedAudioLevel: audioLevel
    property bool audioReactiveAvailable: false
    property string audioReactiveSource: "unavailable"
    property string statusLabel: ""
    readonly property string idleLoopMode: "continuous_time"
    property string shellMode: "ghost"
    property real phase: 0
    property real orbit: 0
    property real shimmer: 0
    property real variance: 0
    property real _lastMotionTick: 0
    property real adaptiveGlowBoost: 0.06
    property real adaptiveAnchorGlowBoost: 0.08
    property real adaptiveAnchorStrokeBoost: 0.12
    property real adaptiveAnchorFillBoost: 0.04
    property real adaptiveAnchorBackdropOpacity: 0.05
    property real adaptiveTone: 0
    property real adaptiveLabelContrast: 0.08
    property real visualAdaptiveGlowBoost: adaptiveGlowBoost
    property real visualAdaptiveAnchorGlowBoost: adaptiveAnchorGlowBoost
    property real visualAdaptiveAnchorStrokeBoost: adaptiveAnchorStrokeBoost
    property real visualAdaptiveAnchorFillBoost: adaptiveAnchorFillBoost
    property real visualAdaptiveAnchorBackdropOpacity: adaptiveAnchorBackdropOpacity
    property real visualAdaptiveTone: adaptiveTone
    property real visualAdaptiveLabelContrast: adaptiveLabelContrast
    property color displayAccentColor: root.accentForState(root.visualState())
    property real displayAmplitude: root.amplitudeForState(root.visualState())

    function visualState() {
        return root.anchorState && root.anchorState.length > 0 ? root.anchorState : root.assistantState
    }

    function amplitudeForState(state) {
        var base = state === "wake_detected" ? 0.10
                 : state === "listening" ? 0.14
                 : state === "transcribing" ? 0.10
                 : state === "thinking" ? 0.08
                 : state === "confirmation_required" ? 0.11
                 : state === "preparing_speech" ? 0.09
                 : state === "speaking" ? 0.12 + Math.min(0.11, root.smoothedAudioLevel * 0.16)
                 : state === "continuing_task" ? 0.06
                 : state === "acting" ? 0.14
                 : state === "interrupted" || state === "muted" ? 0.018
                 : state === "blocked" || state === "error" || state === "warning" ? 0.05
                 : state === "dormant" ? 0.018
                 : 0.035
        return Math.max(base, Math.min(0.23, root.motionIntensity * 0.22))
    }

    function accentForState(state) {
        return state === "acting" ? "#c09a60"
             : state === "wake_detected" ? "#9fd9f0"
             : state === "listening" ? "#8dded8"
             : state === "transcribing" ? "#9bd7c6"
             : state === "thinking" ? "#8cc9e2"
             : state === "confirmation_required" ? "#d3bd78"
             : state === "preparing_speech" ? "#9fd2ec"
             : state === "speaking" ? "#a8e7f3"
             : state === "interrupted" || state === "muted" ? "#8da3b0"
             : state === "blocked" || state === "error" || state === "warning" ? "#c7925c"
             : "#6baec7"
    }

    function motionSpeedForState(state) {
        return state === "speaking" ? 3.7 + Math.min(2.2, root.smoothedAudioLevel * 3.0)
             : state === "listening" ? 2.6
             : state === "transcribing" ? 2.2
             : state === "thinking" ? 1.7
             : state === "preparing_speech" ? 1.9
             : state === "wake_detected" ? 2.4
             : state === "interrupted" || state === "muted" ? 0.75
             : 1.15
    }

    function rgba(colorValue, alphaValue) {
        return "rgba("
            + Math.round(colorValue.r * 255) + ","
            + Math.round(colorValue.g * 255) + ","
            + Math.round(colorValue.b * 255) + ","
            + alphaValue + ")"
    }

    function toneColor(baseColor) {
        if (root.visualAdaptiveTone > 0) {
            return Qt.darker(baseColor, 1 + root.visualAdaptiveTone * 0.7)
        }
        if (root.visualAdaptiveTone < 0) {
            return Qt.lighter(baseColor, 1 + Math.abs(root.visualAdaptiveTone) * 0.45)
        }
        return baseColor
    }

    function contrastColor(baseColor, boost) {
        return Qt.lighter(root.toneColor(baseColor), 1 + boost)
    }

    Timer {
        id: motionClock
        interval: 33
        repeat: true
        running: true
        onTriggered: {
            var now = Date.now() / 1000.0
            if (root._lastMotionTick <= 0) {
                root._lastMotionTick = now
                return
            }
            var delta = Math.min(0.08, Math.max(0.0, now - root._lastMotionTick))
            root._lastMotionTick = now
            var speed = root.motionSpeedForState(root.visualState())
            root.phase += delta * speed
            root.orbit += delta * (0.38 + root.motionIntensity * 0.24)
            root.shimmer += delta * (0.58 + root.motionIntensity * 0.22)
            root.variance += delta * (0.74 + root.motionIntensity * 0.18)
            coreCanvas.requestPaint()
        }
    }

    Behavior on displayAccentColor {
        ColorAnimation { duration: 420 }
    }

    Behavior on displayAmplitude {
        NumberAnimation { duration: 320; easing.type: Easing.InOutQuad }
    }

    onAdaptiveGlowBoostChanged: root.visualAdaptiveGlowBoost = root.adaptiveGlowBoost
    onAdaptiveAnchorGlowBoostChanged: root.visualAdaptiveAnchorGlowBoost = root.adaptiveAnchorGlowBoost
    onAdaptiveAnchorStrokeBoostChanged: root.visualAdaptiveAnchorStrokeBoost = root.adaptiveAnchorStrokeBoost
    onAdaptiveAnchorFillBoostChanged: root.visualAdaptiveAnchorFillBoost = root.adaptiveAnchorFillBoost
    onAdaptiveAnchorBackdropOpacityChanged: root.visualAdaptiveAnchorBackdropOpacity = root.adaptiveAnchorBackdropOpacity
    onAdaptiveToneChanged: root.visualAdaptiveTone = root.adaptiveTone
    onAdaptiveLabelContrastChanged: root.visualAdaptiveLabelContrast = root.adaptiveLabelContrast

    Behavior on visualAdaptiveGlowBoost {
        NumberAnimation { duration: 560; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveAnchorGlowBoost {
        NumberAnimation { duration: 560; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveAnchorStrokeBoost {
        NumberAnimation { duration: 560; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveAnchorFillBoost {
        NumberAnimation { duration: 560; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveAnchorBackdropOpacity {
        NumberAnimation { duration: 560; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveTone {
        NumberAnimation { duration: 560; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveLabelContrast {
        NumberAnimation { duration: 560; easing.type: Easing.InOutCubic }
    }

    Canvas {
        id: coreCanvas
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)

            var cx = width / 2
            var cy = height / 2
            var outerR = Math.min(width, height) * 0.45
            var irisR = outerR * 0.75
            var heartR = outerR * 0.33
            var voiceVisualState = root.visualState()
            var safeAudioLevel = Math.max(0, Math.min(1, root.smoothedAudioLevel || root.audioLevel || 0))
            var speakingBoost = root.speakingActive ? (0.1 + safeAudioLevel * 0.22) : 0
            var pulse = 1 + Math.sin(root.phase) * (root.displayAmplitude + speakingBoost)
            var subtle = 1 + Math.sin(root.variance) * 0.03
            var accent = root.displayAccentColor
            var deckMode = root.shellMode === "deck"

            function circleStroke(radius, lineWidth, alpha) {
                ctx.beginPath()
                ctx.arc(cx, cy, radius, 0, Math.PI * 2)
                ctx.lineWidth = lineWidth
                ctx.strokeStyle = root.rgba(accent, alpha)
                ctx.stroke()
            }

            function ringSegment(radius, start, end, lineWidth, alpha) {
                ctx.beginPath()
                ctx.arc(cx, cy, radius, start, end)
                ctx.lineWidth = lineWidth
                ctx.strokeStyle = root.rgba(accent, alpha)
                ctx.lineCap = "round"
                ctx.stroke()
            }

            function glowFill(radius, alpha) {
                var gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius)
                gradient.addColorStop(0, root.rgba(accent, alpha))
                gradient.addColorStop(0.58, root.rgba(accent, alpha * 0.22))
                gradient.addColorStop(1, root.rgba(accent, 0))
                ctx.beginPath()
                ctx.fillStyle = gradient
                ctx.arc(cx, cy, radius, 0, Math.PI * 2)
                ctx.fill()
            }

            function darkBackdrop(radius, alpha) {
                var gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius)
                gradient.addColorStop(0, "rgba(6, 10, 14," + alpha + ")")
                gradient.addColorStop(0.58, "rgba(8, 12, 16," + (alpha * 0.45) + ")")
                gradient.addColorStop(1, "rgba(8, 12, 16,0)")
                ctx.beginPath()
                ctx.fillStyle = gradient
                ctx.arc(cx, cy, radius, 0, Math.PI * 2)
                ctx.fill()
            }

            function drawTicks(radius, alpha) {
                ctx.save()
                ctx.translate(cx, cy)
                for (var i = 0; i < 24; ++i) {
                    var angle = (Math.PI * 2 / 24) * i
                    var tickLength = i % 6 === 0 ? outerR * 0.13 : i % 3 === 0 ? outerR * 0.08 : outerR * 0.05
                    ctx.beginPath()
                    ctx.rotate(angle - (i === 0 ? 0 : (Math.PI * 2 / 24) * (i - 1)))
                    ctx.moveTo(0, -radius)
                    ctx.lineTo(0, -(radius - tickLength))
                    ctx.lineWidth = i % 6 === 0 ? 2.0 : i % 3 === 0 ? 1.3 : 0.9
                    ctx.strokeStyle = root.rgba(accent, i % 6 === 0 ? alpha : alpha * 0.58)
                    ctx.stroke()
                }
                ctx.restore()
            }

            function drawCompassArms(radius, alpha) {
                ctx.save()
                ctx.translate(cx, cy)
                for (var arm = 0; arm < 4; ++arm) {
                    ctx.save()
                    ctx.rotate((Math.PI / 2) * arm + Math.sin(root.orbit + arm) * 0.01)
                    ctx.beginPath()
                    ctx.moveTo(0, -radius * 0.12)
                    ctx.lineTo(0, -radius * 0.72)
                    ctx.lineWidth = arm === 0 ? 2.2 : 1.4
                    ctx.strokeStyle = root.rgba(accent, arm === 0 ? alpha : alpha * 0.62)
                    ctx.stroke()

                    ctx.beginPath()
                    ctx.moveTo(0, -radius * 0.82)
                    ctx.lineTo(radius * 0.032, -radius * 0.69)
                    ctx.lineTo(0, -radius * 0.75)
                    ctx.lineTo(-radius * 0.032, -radius * 0.69)
                    ctx.closePath()
                    ctx.fillStyle = root.rgba(accent, alpha * (arm === 0 ? 0.84 : 0.46))
                    ctx.fill()
                    ctx.restore()
                }
                ctx.restore()
            }

            function drawBearingArc(radius, start, sweep, lineWidth, alpha) {
                ctx.beginPath()
                ctx.arc(cx, cy, radius, start, start + sweep)
                ctx.lineWidth = lineWidth
                ctx.strokeStyle = root.rgba(accent, alpha)
                ctx.lineCap = "round"
                ctx.stroke()
            }

            function drawHeart(radius, alpha, wobble) {
                ctx.beginPath()
                for (var i = 0; i <= 48; ++i) {
                    var angle = (Math.PI * 2 / 48) * i
                    var offset = 1 + Math.sin(root.phase * 1.8 + angle * 3.1) * wobble
                    var x = cx + Math.cos(angle) * radius * offset
                    var y = cy + Math.sin(angle) * radius * offset
                    if (i === 0) {
                        ctx.moveTo(x, y)
                    } else {
                        ctx.lineTo(x, y)
                    }
                }
                ctx.closePath()
                ctx.fillStyle = root.rgba(accent, alpha)
                ctx.fill()
            }

            if (deckMode) {
                var deckGradient = ctx.createRadialGradient(cx, cy, outerR * 0.18, cx, cy, outerR * 1.08)
                deckGradient.addColorStop(0, "rgba(8, 13, 18, 0.82)")
                deckGradient.addColorStop(0.66, "rgba(12, 18, 24, 0.34)")
                deckGradient.addColorStop(1, "rgba(12, 18, 24, 0.0)")
                ctx.beginPath()
                ctx.fillStyle = deckGradient
                ctx.arc(cx, cy, outerR * 1.08, 0, Math.PI * 2)
                ctx.fill()
            }

            darkBackdrop(outerR * 1.02, root.visualAdaptiveAnchorBackdropOpacity)

            glowFill(outerR * 1.08, (root.shellMode === "ghost" ? 0.16 : 0.15) + root.visualAdaptiveGlowBoost * 0.28 + root.visualAdaptiveAnchorGlowBoost * 0.56)
            glowFill(outerR * 0.74, 0.08 + root.displayAmplitude * 0.08 + root.visualAdaptiveGlowBoost * 0.14 + root.visualAdaptiveAnchorGlowBoost * 0.34 + root.visualAdaptiveAnchorFillBoost * 0.1)

            circleStroke(outerR * 0.98, 1.0 + root.visualAdaptiveAnchorStrokeBoost * 1.45, 0.12 + root.visualAdaptiveLabelContrast * 0.18 + root.visualAdaptiveAnchorStrokeBoost * 0.34)
            circleStroke(outerR * 0.82 * subtle, 1.2 + root.visualAdaptiveAnchorStrokeBoost * 1.15, 0.22 + root.visualAdaptiveLabelContrast * 0.14 + root.visualAdaptiveAnchorStrokeBoost * 0.27)
            circleStroke(irisR * (0.98 + Math.sin(root.shimmer) * 0.01), 1.1 + root.visualAdaptiveAnchorStrokeBoost * 0.92, 0.2 + root.visualAdaptiveLabelContrast * 0.12 + root.visualAdaptiveAnchorStrokeBoost * 0.24)

            drawBearingArc(outerR * 0.9, root.orbit + 0.12, Math.PI * 0.42, 2.0 + root.visualAdaptiveAnchorStrokeBoost * 1.55, 0.32 + root.visualAdaptiveAnchorStrokeBoost * 0.28)
            drawBearingArc(outerR * 0.74, root.orbit + Math.PI * 0.86, Math.PI * 0.24, 1.5 + root.visualAdaptiveAnchorStrokeBoost * 0.92, 0.18 + root.visualAdaptiveAnchorStrokeBoost * 0.16)
            drawBearingArc(outerR * 0.6, root.orbit + Math.PI * 1.42, Math.PI * 0.2, 1.3 + root.visualAdaptiveAnchorStrokeBoost * 0.68, 0.14 + root.visualAdaptiveAnchorStrokeBoost * 0.13)
            drawBearingArc(outerR * 0.5, -Math.PI * 0.58, Math.PI * 0.16, 1.0 + root.visualAdaptiveAnchorStrokeBoost * 0.48, 0.12 + root.visualAdaptiveAnchorStrokeBoost * 0.1)

            drawTicks(outerR * 1.02, 0.22 + root.visualAdaptiveAnchorStrokeBoost * 0.16)
            drawCompassArms(outerR, 0.24 + root.visualAdaptiveAnchorStrokeBoost * 0.18)

            if (voiceVisualState === "listening" || voiceVisualState === "speaking") {
                circleStroke(outerR * (0.52 + pulse * 0.16), 1.4, 0.18)
                circleStroke(outerR * (0.64 + pulse * 0.12), 1.1, 0.12)
            }

            if (root.speakingActive) {
                circleStroke(outerR * (0.46 + safeAudioLevel * 0.16 + Math.sin(root.phase * 1.4) * 0.025), 1.1 + safeAudioLevel * 2.4, 0.12 + safeAudioLevel * 0.24)
                circleStroke(outerR * (0.68 + safeAudioLevel * 0.1 + Math.sin(root.phase * 1.1 + 0.9) * 0.02), 0.9 + safeAudioLevel * 1.6, 0.08 + safeAudioLevel * 0.16)
                ringSegment(outerR * (0.78 + safeAudioLevel * 0.08), root.phase * 0.8, root.phase * 0.8 + Math.PI * (0.26 + safeAudioLevel * 0.22), 1.6 + safeAudioLevel * 1.8, 0.16 + safeAudioLevel * 0.22)
            }

            if (voiceVisualState === "thinking") {
                ringSegment(outerR * 0.46, root.orbit * 1.4, root.orbit * 1.4 + Math.PI * 0.44, 2.4, 0.34)
                ringSegment(outerR * 0.38, root.orbit * 0.9 + Math.PI, root.orbit * 0.9 + Math.PI * 1.26, 1.8, 0.2)
            }

            if (voiceVisualState === "acting" || voiceVisualState === "continuing_task") {
                for (var traceIndex = -1; traceIndex <= 1; ++traceIndex) {
                    var traceAngle = Math.PI * 0.5 + traceIndex * 0.24 + Math.sin(root.phase + traceIndex) * 0.03
                    ctx.beginPath()
                    ctx.moveTo(cx + Math.cos(traceAngle) * outerR * 0.18, cy + Math.sin(traceAngle) * outerR * 0.18)
                    ctx.lineTo(cx + Math.cos(traceAngle) * outerR * 0.9, cy + Math.sin(traceAngle) * outerR * 0.9)
                    ctx.lineWidth = traceIndex === 0 ? 2.2 : 1.4
                    ctx.strokeStyle = root.rgba(accent, traceIndex === 0 ? 0.28 : 0.18)
                    ctx.stroke()
                }
            }

            if (voiceVisualState === "warning" || voiceVisualState === "blocked" || voiceVisualState === "error" || voiceVisualState === "confirmation_required") {
                ringSegment(outerR * 0.88, 0.14, 0.94, 2.2, 0.34)
                ringSegment(outerR * 0.88, 2.28, 3.02, 2.2, 0.34)
            }

            drawHeart(heartR * pulse, 0.44 + root.displayAmplitude * 0.9 + root.visualAdaptiveAnchorFillBoost * 0.56, root.displayAmplitude * 0.46)
            circleStroke(heartR * 1.28, 1.2 + root.visualAdaptiveAnchorStrokeBoost * 0.6, 0.18 + root.visualAdaptiveAnchorStrokeBoost * 0.18 + root.visualAdaptiveAnchorFillBoost * 0.08)
        }
    }

    onPhaseChanged: coreCanvas.requestPaint()
    onOrbitChanged: coreCanvas.requestPaint()
    onShimmerChanged: coreCanvas.requestPaint()
    onVarianceChanged: coreCanvas.requestPaint()
    onAssistantStateChanged: {
        root.displayAccentColor = root.accentForState(root.visualState())
        root.displayAmplitude = root.amplitudeForState(root.visualState())
        coreCanvas.requestPaint()
    }
    onAnchorStateChanged: {
        root.displayAccentColor = root.accentForState(root.visualState())
        root.displayAmplitude = root.amplitudeForState(root.visualState())
        coreCanvas.requestPaint()
    }
    onSpeakingActiveChanged: coreCanvas.requestPaint()
    onMotionIntensityChanged: {
        root.displayAmplitude = root.amplitudeForState(root.visualState())
        coreCanvas.requestPaint()
    }
    onAudioLevelChanged: coreCanvas.requestPaint()
    onSmoothedAudioLevelChanged: {
        root.displayAmplitude = root.amplitudeForState(root.visualState())
        coreCanvas.requestPaint()
    }
    onAudioReactiveAvailableChanged: coreCanvas.requestPaint()
    onShellModeChanged: coreCanvas.requestPaint()
    onDisplayAccentColorChanged: coreCanvas.requestPaint()
    onDisplayAmplitudeChanged: coreCanvas.requestPaint()
    onVisualAdaptiveGlowBoostChanged: coreCanvas.requestPaint()
    onVisualAdaptiveAnchorGlowBoostChanged: coreCanvas.requestPaint()
    onVisualAdaptiveAnchorStrokeBoostChanged: coreCanvas.requestPaint()
    onVisualAdaptiveAnchorFillBoostChanged: coreCanvas.requestPaint()
    onVisualAdaptiveAnchorBackdropOpacityChanged: coreCanvas.requestPaint()
    onVisualAdaptiveToneChanged: coreCanvas.requestPaint()
    onVisualAdaptiveLabelContrastChanged: coreCanvas.requestPaint()

    Component.onCompleted: {
        root._lastMotionTick = Date.now() / 1000.0
        root.displayAccentColor = root.accentForState(root.visualState())
        root.displayAmplitude = root.amplitudeForState(root.visualState())
        coreCanvas.requestPaint()
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: -28
        text: root.statusLabel && root.statusLabel.length > 0 ? root.statusLabel
             : root.visualState() === "dormant" ? "Dormant"
             : root.visualState() === "idle" ? "Holding"
             : root.visualState() === "wake_detected" ? "Wake"
             : root.visualState() === "listening" ? "Listening"
             : root.visualState() === "transcribing" ? "Transcribing"
             : root.visualState() === "thinking" ? "Thinking"
             : root.visualState() === "confirmation_required" ? "Confirm"
             : root.visualState() === "preparing_speech" ? "Preparing"
             : root.visualState() === "continuing_task" ? "Continuing"
             : root.visualState() === "acting" ? "Acting"
             : root.visualState() === "speaking" ? "Speaking"
             : root.visualState() === "muted" ? "Muted"
             : root.visualState() === "interrupted" ? "Interrupted"
             : "Warning"
        color: root.contrastColor("#c7dbe5", root.visualAdaptiveLabelContrast * 0.3)
        font.family: "Bahnschrift SemiCondensed"
        font.pixelSize: root.shellMode === "ghost" ? 14 : 13
        font.letterSpacing: 2.1
        opacity: 0.76
        style: Text.Raised
        styleColor: Qt.rgba(0.01, 0.04, 0.07, 0.16 + root.visualAdaptiveLabelContrast * 0.22)
    }
}
