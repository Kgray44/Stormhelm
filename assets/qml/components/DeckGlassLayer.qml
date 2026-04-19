import QtQuick 2.15

Item {
    id: root

    objectName: "stormDeckGlassField"

    property string mode: "ghost"
    property real deckProgress: mode === "deck" ? 1 : 0
    property real phase: 0
    property real materialStrength: root.deckProgress * 0.045

    NumberAnimation {
        target: root
        property: "phase"
        from: 0
        to: 1
        loops: Animation.Infinite
        duration: 18000
        running: true
    }

    Rectangle {
        anchors.fill: parent
        color: "#08111a"
        opacity: root.deckProgress * 0.022
    }

    ShaderEffect {
        anchors.fill: parent
        blending: true
        opacity: root.deckProgress * 0.042

        property real time: root.phase
        property real depth: root.materialStrength
        property vector2d resolution: Qt.vector2d(width, height)

        fragmentShader: Qt.resolvedUrl("../shaders/ship_glass.frag.qsb")
    }
}
