import QtQuick 2.15

Item {
    id: root

    objectName: "stormforgeVolumetricFogLayer"

    property var config: ({})
    property string rendererType: "shader"
    readonly property string fogMode: normalizedString("mode", "volumetric")
    readonly property string quality: normalizedQuality(normalizedString("quality", "medium"))
    readonly property int configuredQualitySamples: sampleCountForQuality()
    readonly property bool fogEnabledRequested: boolValue("enabled", false)
    readonly property bool fallbackEnabled: root.fogEnabledRequested && root.fogMode === "fallback"
    readonly property bool hasRenderableGeometry: root.width > 0 && root.height > 0
    readonly property bool active: root.fogEnabledRequested
        && root.fogMode === "volumetric"
        && root.quality !== "off"
        && root.configuredQualitySamples > 0
        && root.hasRenderableGeometry
    readonly property bool fogActive: root.active
    readonly property bool shaderEnabled: root.active
    readonly property bool fogVisible: root.visible && root.opacity > 0.0
    readonly property bool animationRunning: phaseAnimation.running
    readonly property int qualitySamples: root.active ? root.configuredQualitySamples : 0
    readonly property real intensity: root.active ? clampNumber(numberValue("intensity", 0.35), 0.0, 1.0) : 0.0
    readonly property real density: clampNumber(numberValue("density", 0.62), 0.0, 1.0)
    readonly property real driftSpeed: clampNumber(numberValue("driftSpeed", 0.055), 0.01, 0.12)
    readonly property string driftDirection: normalizedDriftDirection(normalizedString("driftDirection", "right_to_left"))
    readonly property real driftDirectionX: clampNumber(numberValue("driftDirectionX", directionXForDrift(root.driftDirection)), -1.0, 1.0)
    readonly property real driftDirectionY: clampNumber(numberValue("driftDirectionY", directionYForDrift(root.driftDirection)), -0.35, 0.35)
    readonly property real flowScale: clampNumber(numberValue("flowScale", 1.0), 0.2, 2.0)
    readonly property real crosswindWobble: clampNumber(numberValue("crosswindWobble", 0.18), 0.0, 0.4)
    readonly property real rollingSpeed: clampNumber(numberValue("rollingSpeed", 0.035), 0.005, 0.08)
    readonly property real wispStretch: clampNumber(numberValue("wispStretch", 1.8), 0.8, 2.8)
    readonly property real noiseScale: clampNumber(numberValue("noiseScale", 1.12), 0.35, 2.4)
    readonly property real edgeDensity: boolValue("edgeFog", true)
        ? clampNumber(numberValue("edgeDensity", 0.88), 0.0, 1.0)
        : 0.0
    readonly property real lowerFogBias: clampNumber(numberValue("lowerFogBias", 0.45), 0.0, 1.0)
    readonly property real centerClearRadius: clampNumber(numberValue("centerClearRadius", 0.40), 0.08, 0.72)
    property real centerClearStrength: clampNumber(numberValue("centerClearStrength", 0.65), 0.0, 1.0)
    readonly property real foregroundAmount: boolValue("foregroundWisps", true)
        ? clampNumber(numberValue("foregroundAmount", 0.18), 0.0, 0.24)
        : 0.0
    property real foregroundOpacityLimit: boolValue("foregroundWisps", true)
        ? clampNumber(numberValue("foregroundOpacityLimit", 0.08), 0.0, 0.16)
        : 0.0
    readonly property real opacityLimit: clampNumber(numberValue("opacityLimit", 0.22), 0.02, 0.28)
    property real protectedCenterX: clampNumber(numberValue("protectedCenterX", 0.50), 0.0, 1.0)
    property real protectedCenterY: clampNumber(numberValue("protectedCenterY", 0.58), 0.0, 1.0)
    property real protectedRadius: clampNumber(numberValue("protectedRadius", 0.36), 0.08, 0.72)
    property real anchorCenterX: clampNumber(numberValue("anchorCenterX", 0.50), 0.0, 1.0)
    property real anchorCenterY: clampNumber(numberValue("anchorCenterY", 0.30), 0.0, 1.0)
    property real anchorRadius: clampNumber(numberValue("anchorRadius", 0.18), 0.08, 0.40)
    property real cardClearStrength: clampNumber(numberValue("cardClearStrength", 0.72), 0.0, 1.0)
    readonly property bool motionEnabled: boolValue("motion", true)
    readonly property bool debugVisible: boolValue("debugVisible", false)
    readonly property real debugIntensityMultiplier: clampNumber(numberValue("debugIntensityMultiplier", 3.0), 1.0, 8.0)
    readonly property bool debugTint: boolValue("debugTint", true)
    readonly property real effectiveOpacity: root.active ? root.opacity * Math.max(root.intensity, 0.001) : 0.0
    readonly property real layerWidth: root.width
    readonly property real layerHeight: root.height
    readonly property real zLayer: root.z
    readonly property string renderMode: root.debugVisible && root.active
        ? "debug_visible"
        : (root.active ? "shader" : (root.fallbackEnabled ? "fallback_requested" : "disabled"))
    readonly property string disabledReason: disabledReasonForState()
    readonly property var maskStrengths: ({
        "centerClearStrength": root.centerClearStrength,
        "cardClearStrength": root.cardClearStrength,
        "protectedRadius": root.protectedRadius,
        "anchorRadius": root.anchorRadius,
        "lowerFogBias": root.lowerFogBias,
        "edgeDensity": root.edgeDensity,
        "foregroundOpacityLimit": root.foregroundOpacityLimit
    })
    readonly property var motionControls: ({
        "driftDirection": root.driftDirection,
        "driftDirectionX": root.driftDirectionX,
        "driftDirectionY": root.driftDirectionY,
        "driftSpeed": root.driftSpeed,
        "flowScale": root.flowScale,
        "crosswindWobble": root.crosswindWobble,
        "rollingSpeed": root.rollingSpeed,
        "wispStretch": root.wispStretch
    })
    property real phase: 0.0

    visible: root.active
    opacity: root.active ? 1.0 : 0.0
    clip: false

    function valueFor(key, fallback) {
        if (!root.config || root.config[key] === undefined || root.config[key] === null) {
            return fallback
        }
        return root.config[key]
    }

    function normalizedString(key, fallback) {
        return String(valueFor(key, fallback)).toLowerCase()
    }

    function normalizedQuality(value) {
        if (value === "off" || value === "low" || value === "medium" || value === "high") {
            return value
        }
        return "medium"
    }

    function normalizedDriftDirection(value) {
        if (value === "right_to_left" || value === "left_to_right" || value === "still") {
            return value
        }
        return "right_to_left"
    }

    function directionXForDrift(value) {
        if (value === "left_to_right") {
            return 1.0
        }
        if (value === "still") {
            return 0.0
        }
        return -1.0
    }

    function directionYForDrift(value) {
        if (value === "still") {
            return 0.0
        }
        return 0.05
    }

    function boolValue(key, fallback) {
        var value = valueFor(key, fallback)
        if (typeof value === "boolean") {
            return value
        }
        if (typeof value === "string") {
            var normalized = value.toLowerCase()
            if (normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on") {
                return true
            }
            if (normalized === "0" || normalized === "false" || normalized === "no" || normalized === "off") {
                return false
            }
        }
        return Boolean(value)
    }

    function numberValue(key, fallback) {
        var parsed = Number(valueFor(key, fallback))
        return isNaN(parsed) ? fallback : parsed
    }

    function clampNumber(value, minimum, maximum) {
        return Math.min(maximum, Math.max(minimum, value))
    }

    function sampleCountForQuality() {
        var configured = Number(valueFor("qualitySamples", 0))
        if (!isNaN(configured) && configured > 0) {
            return Math.min(28, Math.max(0, Math.round(configured)))
        }
        if (root.quality === "low") {
            return 8
        }
        if (root.quality === "high") {
            return 24
        }
        return 14
    }

    function disabledReasonForState() {
        if (root.active) {
            return ""
        }
        if (!root.fogEnabledRequested) {
            return "disabled_by_config"
        }
        if (root.fallbackEnabled) {
            return "fallback_mode"
        }
        if (root.quality === "off") {
            return "quality_off"
        }
        if (root.configuredQualitySamples <= 0) {
            return "zero_samples"
        }
        if (!root.hasRenderableGeometry) {
            return "zero_geometry"
        }
        return "inactive"
    }

    onActiveChanged: {
        if (!root.active) {
            root.phase = 0.0
        }
    }

    StormforgeTokens {
        id: sf
    }

    NumberAnimation {
        id: phaseAnimation
        target: root
        property: "phase"
        from: 0.0
        to: 10000.0
        duration: 520000000
        loops: Animation.Infinite
        running: root.active && root.motionEnabled
    }

    ShaderEffect {
        anchors.fill: parent
        visible: root.active
        blending: true

        property real time: root.phase
        property vector2d resolution: Qt.vector2d(Math.max(1, width), Math.max(1, height))
        property real intensity: root.intensity
        property real density: root.density
        property real driftSpeed: root.driftSpeed
        property vector2d driftDirection: Qt.vector2d(root.driftDirectionX, root.driftDirectionY)
        property real flowScale: root.flowScale
        property real crosswindWobble: root.crosswindWobble
        property real rollingSpeed: root.rollingSpeed
        property real wispStretch: root.wispStretch
        property real noiseScale: root.noiseScale
        property real edgeDensity: root.edgeDensity
        property real lowerFogBias: root.lowerFogBias
        property real centerClearRadius: root.centerClearRadius
        property real foregroundAmount: root.foregroundAmount
        property real sampleCount: root.qualitySamples
        property real opacityLimit: root.opacityLimit
        property vector2d protectedCenter: Qt.vector2d(root.protectedCenterX, root.protectedCenterY)
        property real protectedRadius: root.protectedRadius
        property real centerClearStrength: root.centerClearStrength
        property vector2d anchorCenter: Qt.vector2d(root.anchorCenterX, root.anchorCenterY)
        property real anchorRadius: root.anchorRadius
        property real cardClearStrength: root.cardClearStrength
        property real foregroundOpacityLimit: root.foregroundOpacityLimit
        property vector4d colorNear: Qt.vector4d(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, 1.0)
        property vector4d colorFar: Qt.vector4d(sf.deepBlue.r, sf.deepBlue.g, sf.deepBlue.b, 1.0)

        fragmentShader: Qt.resolvedUrl("../../shaders/stormforge_volumetric_fog.frag.qsb")
    }

    Item {
        id: debugVisibleProbe
        objectName: "stormforgeFogDebugVisibleProbe"
        anchors.fill: parent
        visible: root.debugVisible && root.active
        opacity: visible ? Math.min(0.72, Math.max(0.22, root.intensity * root.debugIntensityMultiplier * 0.42)) : 0.0

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: 2
            border.color: root.debugTint
                ? Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, 0.70)
                : Qt.rgba(1.0, 1.0, 1.0, 0.70)
        }

        Rectangle {
            width: parent.width
            height: parent.height * 0.30
            anchors.bottom: parent.bottom
            opacity: 0.90
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, 0.00) }
                GradientStop { position: 0.55; color: Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, 0.16) }
                GradientStop { position: 1.0; color: Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, 0.36) }
            }
        }

        Rectangle {
            width: parent.width * 0.20
            height: parent.height
            anchors.left: parent.left
            opacity: 0.58
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, 0.28) }
                GradientStop { position: 1.0; color: Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, 0.00) }
            }
        }

        Rectangle {
            width: parent.width * 0.20
            height: parent.height
            anchors.right: parent.right
            opacity: 0.58
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, 0.00) }
                GradientStop { position: 1.0; color: Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, 0.28) }
            }
        }
    }
}
