import QtQuick 2.15

QtObject {
    id: root

    readonly property string foundationVersion: "UI-P1"
    readonly property string paletteName: "stormforge"

    readonly property color abyss: "#02070b"
    readonly property color slate: "#071119"
    readonly property color stormBlue: "#0e2635"
    readonly property color deepBlue: "#0b1b28"
    readonly property color glassFill: "#0b1720"
    readonly property color glassFillRaised: "#102532"
    readonly property color panelFill: "#0d1b24"
    readonly property color railFill: "#08131b"
    readonly property color textPrimary: "#edf7fb"
    readonly property color textSecondary: "#a8c2cb"
    readonly property color textMuted: "#6f8c99"
    readonly property color lineSoft: "#254555"
    readonly property color lineStrong: "#5f8fa2"
    readonly property color signalCyan: "#8ed5ea"
    readonly property color seaGreen: "#78d6bf"
    readonly property color brass: "#caa25c"
    readonly property color copper: "#bd7a53"
    readonly property color amber: "#d8b260"
    readonly property color danger: "#e2837b"
    readonly property color stale: "#8997a0"
    readonly property color devViolet: "#a69be8"
    readonly property color unavailable: "#5c6971"

    readonly property real opacityGhostVeil: 0.08
    readonly property real opacityGlass: 0.74
    readonly property real opacityPanel: 0.9
    readonly property real opacityMuted: 0.54
    readonly property real opacityDisabled: 0.34
    readonly property real strokeOpacitySoft: 0.42
    readonly property real strokeOpacityStrong: 0.82
    readonly property real glowOpacitySoft: 0.18
    readonly property real glowOpacityStrong: 0.34
    readonly property real shadowOpacity: 0.22

    readonly property int space1: 4
    readonly property int space2: 8
    readonly property int space3: 12
    readonly property int space4: 16
    readonly property int space5: 24
    readonly property int space6: 32
    readonly property int space7: 48

    readonly property int fontXs: 10
    readonly property int fontSm: 11
    readonly property int fontBody: 13
    readonly property int fontTitle: 15
    readonly property int fontDeckTitle: 18
    readonly property int fontDisplay: 24

    readonly property int radiusTiny: 5
    readonly property int radiusControl: 8
    readonly property int radiusChip: 12
    readonly property int radiusCard: 14
    readonly property int radiusPanel: 18

    readonly property int elevationFlat: 0
    readonly property int elevationLow: 1
    readonly property int elevationMedium: 2
    readonly property int elevationHigh: 3

    readonly property int durationFast: 140
    readonly property int durationBase: 220
    readonly property int durationSlow: 360
    readonly property int durationReveal: 520
    readonly property int durationAnchorPulse: 5000
    readonly property int durationAnchorOrbit: 9800
    readonly property int durationAnchorIdleBreath: 9200
    readonly property int durationAnchorStateTransition: 420
    readonly property int durationAnchorStateMinimumDwell: 140

    readonly property real anchorStrokeHairline: 0.75
    readonly property real anchorStrokePrimary: 1.15
    readonly property real anchorStrokeHeavy: 1.75
    readonly property real anchorHaloOpacity: 0.10
    readonly property real anchorVisualSoftness: 0.60
    readonly property real anchorInnerGlassOpacity: 0.12
    readonly property real anchorDepthShadowOpacity: 0.18
    readonly property real anchorBezelOpacity: 0.30
    readonly property real anchorHorizonOpacity: 0.18
    readonly property real anchorSweepOpacity: 0.16
    readonly property real anchorMotionRestraint: 0.78
    readonly property real anchorHeadingMarkerOpacity: 0.34
    readonly property real anchorOuterClampOpacity: 0.28
    readonly property real anchorCenterApertureOpacity: 0.24
    readonly property real anchorSignalPointOpacity: 0.38
    readonly property real anchorCrownAccentOpacity: 0.30
    readonly property real anchorCenterLensRadiusRatio: 0.31
    readonly property real anchorCenterLensRimOpacity: 0.31
    readonly property real anchorCenterLensShadowOpacity: 0.22
    readonly property real anchorCenterLensHighlightOpacity: 0.26
    readonly property real anchorCenterIrisOpacity: 0.22
    readonly property real anchorCenterPetalOpacity: 0.18
    readonly property real anchorCenterPearlOpacity: 0.46
    readonly property real anchorCenterMotionRestraint: 0.62
    readonly property real anchorIdleMinimumRingOpacity: 0.16
    readonly property real anchorIdleMinimumCenterLensOpacity: 0.17
    readonly property real anchorIdleMinimumBearingTickOpacity: 0.11
    readonly property real anchorIdleMinimumSignalPointOpacity: 0.18
    readonly property real anchorIdleMinimumLabelOpacity: 0.74
    readonly property real anchorIdlePulseMinOpacity: 0.055
    readonly property real anchorIdlePulseMaxOpacity: 0.16
    readonly property real anchorIdleLensPulseStrength: 0.060
    readonly property real anchorIdleApertureShimmerOpacity: 0.045
    readonly property real anchorIdleBearingDriftStrength: 0.012
    readonly property real anchorUnavailableMinimumRingOpacity: 0.055
    readonly property real anchorUnavailableMinimumCenterLensOpacity: 0.060
    readonly property real anchorUnavailableMinimumBearingTickOpacity: 0.040
    readonly property real anchorUnavailableMinimumSignalPointOpacity: 0.055
    readonly property real anchorUnavailableMinimumLabelOpacity: 0.56
    readonly property real anchorOrbitalSpeedScale: 0.42
    readonly property real anchorListeningRippleSpeedScale: 0.64
    readonly property real anchorSpeakingRadianceSpeedScale: 0.68
    readonly property real anchorWarningPulseLimit: 0.18
    readonly property int anchorCenterLensLayerCount: 7
    readonly property int anchorCenterApertureSegmentCount: 4
    readonly property int anchorDepthLayerCount: 7
    readonly property int anchorNauticalDetailCount: 8
    readonly property int anchorSignatureFeatureCount: 5
    readonly property int anchorBearingTickCount: 40

    readonly property int zBackground: 0
    readonly property int zSurface: 10
    readonly property int zOverlay: 30
    readonly property int zToast: 50

    function normalizeState(state) {
        var key = String(state || "idle").toLowerCase()
        if (key === "mock" || key === "dev" || key === "development")
            return "mock_dev"
        if (key === "approval" || key === "requires_approval" || key === "approval-required")
            return "approval_required"
        if (key === "ghost_ready")
            return "wake_detected"
        if (key === "ready")
            return "active"
        if (key === "routing")
            return "thinking"
        if (key === "executing")
            return "acting"
        if (key === "warning")
            return "blocked"
        if (key === "error")
            return "failed"
        if (key === "unverified_result")
            return "unverified"
        if (key === "confirmed" || key === "complete" || key === "completed")
            return "verified"
        return key
    }

    function stateAccent(state) {
        switch (normalizeState(state)) {
        case "active":
        case "ready":
        case "wake_detected":
        case "listening":
        case "capturing":
        case "transcribing":
        case "speaking":
        case "verified":
            return seaGreen
        case "thinking":
        case "routing":
        case "planned":
        case "running":
            return signalCyan
        case "acting":
        case "executing":
        case "recovery":
            return brass
        case "approval_required":
            return amber
        case "blocked":
            return amber
        case "failed":
            return danger
        case "stale":
        case "unverified":
            return stale
        case "mock_dev":
            return devViolet
        case "unavailable":
            return unavailable
        default:
            return lineStrong
        }
    }

    function stateFill(state) {
        var accent = stateAccent(state)
        var key = normalizeState(state)
        if (key === "failed" || key === "blocked")
            return Qt.rgba(accent.r, accent.g, accent.b, 0.14)
        if (key === "approval_required" || key === "recovery")
            return Qt.rgba(accent.r, accent.g, accent.b, 0.13)
        if (key === "verified" || key === "listening" || key === "speaking")
            return Qt.rgba(accent.r, accent.g, accent.b, 0.10)
        return Qt.rgba(accent.r, accent.g, accent.b, 0.08)
    }

    function stateStroke(state) {
        var accent = stateAccent(state)
        return Qt.rgba(accent.r, accent.g, accent.b, 0.62)
    }

    function stateGlow(state) {
        var accent = stateAccent(state)
        return Qt.rgba(accent.r, accent.g, accent.b, 0.22)
    }

    function stateText(state) {
        var key = normalizeState(state)
        if (key === "unavailable")
            return textMuted
        return textPrimary
    }
}
