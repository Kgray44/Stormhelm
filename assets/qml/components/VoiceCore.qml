import QtQuick 2.15

Item {
    id: root

    signal requestDeck()
    signal requestGhost()

    property string assistantState: "idle"
    property string shellMode: "ghost"
    property real phase: 0
    property real orbit: 0
    property real shimmer: 0
    property real variance: 0
    property color displayAccentColor: root.accentForState(root.assistantState)
    property real displayAmplitude: root.amplitudeForState(root.assistantState)

    function amplitudeForState(state) {
        return state === "listening" ? 0.12
             : state === "thinking" ? 0.08
             : state === "acting" ? 0.14
             : state === "speaking" ? 0.16
             : state === "warning" ? 0.05
             : 0.035
    }

    function accentForState(state) {
        return state === "acting" ? "#c09a60"
             : state === "listening" ? "#8dded8"
             : state === "thinking" ? "#8cc9e2"
             : state === "speaking" ? "#a8e7f3"
             : state === "warning" ? "#c7925c"
             : "#6baec7"
    }

    function rgba(colorValue, alphaValue) {
        return "rgba("
            + Math.round(colorValue.r * 255) + ","
            + Math.round(colorValue.g * 255) + ","
            + Math.round(colorValue.b * 255) + ","
            + alphaValue + ")"
    }

    NumberAnimation on phase {
        from: 0
        to: Math.PI * 2
        loops: Animation.Infinite
        duration: assistantState === "speaking" ? 1800
                 : assistantState === "acting" ? 2200
                 : assistantState === "listening" ? 2500
                 : assistantState === "thinking" ? 3600
                 : assistantState === "warning" ? 4200
                 : 5200
    }

    NumberAnimation on orbit {
        from: 0
        to: Math.PI * 2
        loops: Animation.Infinite
        duration: assistantState === "acting" ? 7200
                 : assistantState === "thinking" ? 10400
                 : assistantState === "warning" ? 8200
                 : 16000
    }

    NumberAnimation on shimmer {
        from: 0
        to: Math.PI * 2
        loops: Animation.Infinite
        duration: 9100
    }

    NumberAnimation on variance {
        from: 0
        to: Math.PI * 2
        loops: Animation.Infinite
        duration: 6700
    }

    Behavior on displayAccentColor {
        ColorAnimation { duration: 420 }
    }

    Behavior on displayAmplitude {
        NumberAnimation { duration: 320; easing.type: Easing.InOutQuad }
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
            var pulse = 1 + Math.sin(root.phase) * root.displayAmplitude
            var subtle = 1 + Math.sin(root.variance) * 0.03
            var accent = root.displayAccentColor

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

            glowFill(outerR * 1.06, root.shellMode === "ghost" ? 0.16 : 0.12)
            glowFill(outerR * 0.68, 0.08 + root.displayAmplitude * 0.08)

            circleStroke(outerR * 0.98, 1.0, 0.1)
            circleStroke(outerR * 0.82 * subtle, 1.2, 0.2)
            circleStroke(irisR * (0.98 + Math.sin(root.shimmer) * 0.01), 1.1, 0.18)

            drawBearingArc(outerR * 0.9, root.orbit + 0.12, Math.PI * 0.42, 2.0, 0.28)
            drawBearingArc(outerR * 0.74, root.orbit + Math.PI * 0.86, Math.PI * 0.24, 1.5, 0.18)
            drawBearingArc(outerR * 0.6, root.orbit + Math.PI * 1.42, Math.PI * 0.2, 1.3, 0.14)
            drawBearingArc(outerR * 0.5, -Math.PI * 0.58, Math.PI * 0.16, 1.0, 0.12)

            drawTicks(outerR * 1.02, 0.22)
            drawCompassArms(outerR, 0.24)

            if (root.assistantState === "listening" || root.assistantState === "speaking") {
                circleStroke(outerR * (0.52 + pulse * 0.16), 1.4, 0.18)
                circleStroke(outerR * (0.64 + pulse * 0.12), 1.1, 0.12)
            }

            if (root.assistantState === "thinking") {
                ringSegment(outerR * 0.46, root.orbit * 1.4, root.orbit * 1.4 + Math.PI * 0.44, 2.4, 0.34)
                ringSegment(outerR * 0.38, root.orbit * 0.9 + Math.PI, root.orbit * 0.9 + Math.PI * 1.26, 1.8, 0.2)
            }

            if (root.assistantState === "acting") {
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

            if (root.assistantState === "warning") {
                ringSegment(outerR * 0.88, 0.14, 0.94, 2.2, 0.34)
                ringSegment(outerR * 0.88, 2.28, 3.02, 2.2, 0.34)
            }

            drawHeart(heartR * pulse, 0.44 + root.displayAmplitude * 0.9, root.displayAmplitude * 0.46)
            circleStroke(heartR * 1.28, 1.2, 0.18)
        }
    }

    onPhaseChanged: coreCanvas.requestPaint()
    onOrbitChanged: coreCanvas.requestPaint()
    onShimmerChanged: coreCanvas.requestPaint()
    onVarianceChanged: coreCanvas.requestPaint()
    onAssistantStateChanged: {
        root.displayAccentColor = root.accentForState(root.assistantState)
        root.displayAmplitude = root.amplitudeForState(root.assistantState)
        coreCanvas.requestPaint()
    }
    onShellModeChanged: coreCanvas.requestPaint()
    onDisplayAccentColorChanged: coreCanvas.requestPaint()
    onDisplayAmplitudeChanged: coreCanvas.requestPaint()

    Component.onCompleted: {
        root.displayAccentColor = root.accentForState(root.assistantState)
        root.displayAmplitude = root.amplitudeForState(root.assistantState)
        coreCanvas.requestPaint()
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: -28
        text: root.assistantState === "idle" ? "Holding"
             : root.assistantState === "listening" ? "Listening"
             : root.assistantState === "thinking" ? "Thinking"
             : root.assistantState === "acting" ? "Acting"
             : root.assistantState === "speaking" ? "Speaking"
             : "Warning"
        color: "#c7dbe5"
        font.family: "Bahnschrift SemiCondensed"
        font.pixelSize: root.shellMode === "ghost" ? 13 : 12
        font.letterSpacing: 2.1
        opacity: 0.58
    }
}
