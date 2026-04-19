import QtQuick 2.15

Item {
    id: root

    objectName: "stormMistField"

    property string mode: "ghost"
    property real deckProgress: mode === "deck" ? 1 : 0
    property real mistStrength: 0.052 + root.deckProgress * 0.028
    property real phase: 0
    property real globalPresence: mode === "ghost" ? 0.014 : 0.024
    property vector2d focusPoint: mode === "ghost"
        ? Qt.vector2d(0.50, 0.56)
        : Qt.vector2d(0.51, 0.44)
    property vector2d spread: mode === "ghost"
        ? Qt.vector2d(0.22, 0.14)
        : Qt.vector2d(0.42, 0.26)

    ShaderEffect {
        anchors.fill: parent
        blending: true

        property real time: root.phase
        property real depth: root.mistStrength
        property real globalPresence: root.globalPresence
        property vector2d focusPoint: root.focusPoint
        property vector2d spread: root.spread

        fragmentShader: Qt.resolvedUrl("../shaders/nautical_mist.frag.qsb")
    }
}
