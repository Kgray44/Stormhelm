import QtQuick 2.15

Item {
    id: root

    objectName: "stormforgeFogFallbackLayer"

    property var config: ({})
    property string rendererType: "fallback"
    property real phase: 0.0
    readonly property bool active: boolValue("enabled", false)
        && String(valueFor("mode", "volumetric")).toLowerCase() === "fallback"
    readonly property bool animationRunning: fallbackMotion.running
    readonly property real intensity: active ? Math.min(0.32, Math.max(0.0, numberValue("intensity", 0.35))) : 0.0

    visible: active
    opacity: active ? 1.0 : 0.0

    function valueFor(key, fallback) {
        if (!root.config || root.config[key] === undefined || root.config[key] === null) {
            return fallback
        }
        return root.config[key]
    }

    function boolValue(key, fallback) {
        var value = valueFor(key, fallback)
        if (typeof value === "boolean") {
            return value
        }
        if (typeof value === "string") {
            var normalized = value.toLowerCase()
            return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on"
        }
        return Boolean(value)
    }

    function numberValue(key, fallback) {
        var parsed = Number(valueFor(key, fallback))
        return isNaN(parsed) ? fallback : parsed
    }

    StormforgeTokens {
        id: sf
    }

    NumberAnimation {
        id: fallbackMotion
        target: root
        property: "phase"
        from: 0.0
        to: 1.0
        duration: 72000
        loops: Animation.Infinite
        running: root.active && root.boolValue("motion", true)
    }

    Rectangle {
        anchors.fill: parent
        opacity: root.intensity * 0.18
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: Qt.rgba(sf.deepBlue.r, sf.deepBlue.g, sf.deepBlue.b, 0.00) }
            GradientStop { position: 0.60; color: Qt.rgba(sf.stormBlue.r, sf.stormBlue.g, sf.stormBlue.b, 0.12) }
            GradientStop { position: 1.0; color: Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, 0.18) }
        }
    }

    Rectangle {
        width: parent.width * 1.18
        height: Math.max(96, parent.height * 0.20)
        x: -parent.width * 0.08 + Math.sin(root.phase * Math.PI * 2.0) * 14
        y: parent.height * 0.70
        radius: height * 0.5
        color: Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, root.intensity * 0.10)
        opacity: root.intensity
    }
}
