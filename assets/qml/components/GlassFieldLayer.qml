import QtQuick 2.15

Item {
    id: root

    objectName: "stormGlassField"

    property string mode: "ghost"
    property real deckProgress: mode === "deck" ? 1 : 0
    property real materialStrength: root.deckProgress * 0.055
    property real phase: 0
    property real swell: 0

    NumberAnimation {
        target: root
        property: "phase"
        from: 0
        to: 1
        loops: Animation.Infinite
        duration: 18000
        running: true
    }

    NumberAnimation {
        target: root
        property: "swell"
        from: 0
        to: 1
        loops: Animation.Infinite
        duration: 12000
        running: true
    }

    Rectangle {
        anchors.fill: parent
        color: "#091018"
        opacity: root.deckProgress * 0.008
    }

    ShaderEffect {
        id: glassShader
        anchors.fill: parent
        blending: true
        opacity: root.deckProgress * 0.065

        property real time: root.phase
        property real depth: root.materialStrength
        property vector2d resolution: Qt.vector2d(width, height)

        fragmentShader: Qt.resolvedUrl("../shaders/ship_glass.frag.qsb")
    }

    Rectangle {
        anchors.fill: parent
        color: "#0d1820"
        opacity: root.deckProgress * 0.008 + Math.sin(root.swell * Math.PI * 2) * (root.deckProgress * 0.0008)
    }

    Repeater {
        model: 4

        Rectangle {
            width: parent.width * 0.33
            height: parent.height * 1.22
            x: parent.width * (-0.1 + index * 0.28)
            y: -parent.height * 0.1
            rotation: -3.6 + index * 2.2
            color: "#a5d2dc"
            opacity: root.deckProgress * 0.002
        }
    }

    Repeater {
        model: 5

        Rectangle {
            width: 1
            height: parent.height * 1.1
            x: parent.width * (0.05 + index * 0.21)
            y: -parent.height * 0.04
            rotation: -1.2 + index * 0.35
            color: "#8abccf"
            opacity: root.deckProgress * 0.0035
        }
    }
}
