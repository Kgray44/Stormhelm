import QtQuick 2.15

Item {
    id: root

    objectName: "stormForegroundMist"

    property string mode: "ghost"
    property real deckProgress: mode === "deck" ? 1 : 0
    property real mistStrength: root.mode === "ghost" ? 0.0 : 0.006 + root.deckProgress * 0.008
    property real phase: 0
    property vector4d rectA: Qt.vector4d(0, 0, 0, 0)
    property vector4d rectB: Qt.vector4d(0, 0, 0, 0)
    property vector4d rectC: Qt.vector4d(0, 0, 0, 0)
    property vector4d rectD: Qt.vector4d(0, 0, 0, 0)

    NumberAnimation {
        target: root
        property: "phase"
        from: 0
        to: 1
        loops: Animation.Infinite
        duration: 42000
        running: true
    }

    ShaderEffect {
        anchors.fill: parent
        blending: true

        property real time: root.phase
        property real depth: root.mistStrength
        property vector4d rectA: root.rectA
        property vector4d rectB: root.rectB
        property vector4d rectC: root.rectC
        property vector4d rectD: root.rectD

        fragmentShader: Qt.resolvedUrl("../shaders/foreground_mist.frag.qsb")
    }
}
