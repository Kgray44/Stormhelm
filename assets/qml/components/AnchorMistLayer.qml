import QtQuick 2.15

Item {
    id: root

    objectName: "stormAnchorMist"

    property string rendererType: "shader"
    property string mode: "ghost"
    property real deckProgress: mode === "deck" ? 1 : 0
    property real phase: 0
    property real baseOpacity: mode === "ghost" ? 0.108 : 0.132
    property vector2d focusPoint: mode === "ghost"
        ? Qt.vector2d(0.50, 0.58)
        : Qt.vector2d(0.51, 0.44)
    property vector2d spread: mode === "ghost"
        ? Qt.vector2d(0.26, 0.16)
        : Qt.vector2d(0.46, 0.28)

    NumberAnimation {
        target: root
        property: "phase"
        from: 0
        to: 1
        loops: Animation.Infinite
        duration: 20000
        running: true
    }

    ShaderEffect {
        anchors.fill: parent
        blending: true

        property real time: root.phase
        property real depth: root.baseOpacity
        property vector2d focusPoint: root.focusPoint
        property vector2d spread: root.spread

        fragmentShader: Qt.resolvedUrl("../shaders/anchor_mist.frag.qsb")
    }
}
