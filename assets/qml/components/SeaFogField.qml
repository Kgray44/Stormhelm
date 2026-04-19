import QtQuick 2.15

Item {
    id: root

    objectName: "stormSeaFogField"

    property string rendererType: "shader"
    property string fogRenderer: "particle-shader"
    property string mode: "ghost"
    property real deckProgress: mode === "deck" ? 1 : 0
    property real densityScale: mode === "ghost" ? 0.62 : 1.0
    property real phase: 0
    property real baseTintOpacity: mode === "ghost" ? 0.005 : 0.022
    property real topVeilOpacity: mode === "ghost" ? 0.010 : 0.028

    NumberAnimation {
        target: root
        property: "phase"
        from: 0
        to: 1
        loops: Animation.Infinite
        duration: 28000
        running: true
    }

    Rectangle {
        anchors.fill: parent
        color: "#061018"
        opacity: root.baseTintOpacity
    }

    SeaFogLayer {
        id: farLayer
        objectName: "stormSeaFogFar"
        anchors.fill: parent
        phase: root.phase
        layerOpacity: (root.mode === "ghost" ? 0.016 : 0.028) * root.densityScale
        layerScale: 0.42
        phaseOffset: 0.0
        fullField: root.mode === "ghost" ? 0.14 : 0.30
        centerBias: root.mode === "ghost" ? 0.52 : 0.36
        drift: root.mode === "ghost" ? Qt.vector2d(0.010, -0.004) : Qt.vector2d(0.008, -0.003)
        focusPoint: root.mode === "ghost" ? Qt.vector2d(0.50, 0.57) : Qt.vector2d(0.51, 0.44)
        spread: root.mode === "ghost" ? Qt.vector2d(0.40, 0.26) : Qt.vector2d(0.68, 0.40)
        tintColor: Qt.vector4d(0.30, 0.38, 0.42, 1.0)
    }

    SeaFogLayer {
        id: midLayer
        objectName: "stormSeaFogMid"
        anchors.fill: parent
        phase: root.phase
        layerOpacity: (root.mode === "ghost" ? 0.022 : 0.040) * root.densityScale
        layerScale: 0.76
        phaseOffset: 1.8
        fullField: root.mode === "ghost" ? 0.08 : 0.22
        centerBias: root.mode === "ghost" ? 0.76 : 0.54
        drift: root.mode === "ghost" ? Qt.vector2d(-0.007, 0.003) : Qt.vector2d(-0.006, 0.002)
        focusPoint: root.mode === "ghost" ? Qt.vector2d(0.50, 0.58) : Qt.vector2d(0.51, 0.45)
        spread: root.mode === "ghost" ? Qt.vector2d(0.28, 0.17) : Qt.vector2d(0.48, 0.28)
        tintColor: Qt.vector4d(0.36, 0.46, 0.50, 1.0)
    }

    SeaFogLayer {
        id: nearLayer
        objectName: "stormSeaFogNear"
        anchors.fill: parent
        phase: root.phase
        layerOpacity: (root.mode === "ghost" ? 0.018 : 0.034) * root.densityScale
        layerScale: 1.18
        phaseOffset: 3.4
        fullField: root.mode === "ghost" ? 0.04 : 0.12
        centerBias: root.mode === "ghost" ? 0.84 : 0.62
        drift: root.mode === "ghost" ? Qt.vector2d(0.005, 0.002) : Qt.vector2d(0.004, 0.001)
        focusPoint: root.mode === "ghost" ? Qt.vector2d(0.50, 0.60) : Qt.vector2d(0.51, 0.47)
        spread: root.mode === "ghost" ? Qt.vector2d(0.22, 0.14) : Qt.vector2d(0.38, 0.22)
        tintColor: Qt.vector4d(0.42, 0.54, 0.58, 1.0)
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.01, 0.02, 0.04, root.topVeilOpacity) }
            GradientStop { position: 0.18; color: Qt.rgba(0.02, 0.03, 0.05, root.mode === "ghost" ? 0.004 : 0.012) }
            GradientStop { position: 0.55; color: Qt.rgba(0.01, 0.02, 0.04, 0.0) }
            GradientStop { position: 1.0; color: Qt.rgba(0.01, 0.02, 0.04, root.mode === "ghost" ? 0.003 : 0.010) }
        }
    }
}
