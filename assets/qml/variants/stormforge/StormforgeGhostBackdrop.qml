import QtQuick 2.15

Item {
    id: root

    property string stateTone: "idle"
    property real veilStrength: sf.opacityGhostVeil

    StormforgeTokens {
        id: sf
    }

    Rectangle {
        anchors.fill: parent
        color: sf.abyss
        opacity: Math.min(0.18, root.veilStrength)
    }

    Rectangle {
        width: Math.min(parent.width * 0.72, 760)
        height: width
        radius: width / 2
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.16
        color: "transparent"
        border.width: 1
        border.color: sf.stateGlow(root.stateTone)
        opacity: 0.22
    }

    Rectangle {
        width: Math.min(parent.width * 0.42, 420)
        height: width
        radius: width / 2
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.26
        color: sf.stateFill(root.stateTone)
        opacity: 0.2
    }

    Repeater {
        model: 3

        delegate: Rectangle {
            required property int index

            width: Math.min(root.width * (0.28 + index * 0.12), 420 + index * 84)
            height: width
            radius: width / 2
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height * 0.30 - index * 20
            color: "transparent"
            border.width: 1
            border.color: Qt.rgba(sf.lineSoft.r, sf.lineSoft.g, sf.lineSoft.b, 0.18 - index * 0.03)
        }
    }
}
