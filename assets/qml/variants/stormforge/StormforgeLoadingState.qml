import QtQuick 2.15

Item {
    id: root

    property string label: "Loading"
    property string stateTone: "running"

    implicitWidth: loadingRow.implicitWidth
    implicitHeight: 32

    StormforgeTokens {
        id: sf
    }

    Row {
        id: loadingRow
        anchors.verticalCenter: parent.verticalCenter
        spacing: sf.space2

        Rectangle {
            width: 10
            height: 10
            radius: 5
            anchors.verticalCenter: parent.verticalCenter
            color: sf.stateAccent(root.stateTone)
            opacity: 0.74

            SequentialAnimation on opacity {
                loops: Animation.Infinite
                NumberAnimation { to: 0.28; duration: sf.durationSlow; easing.type: Easing.InOutQuad }
                NumberAnimation { to: 0.74; duration: sf.durationSlow; easing.type: Easing.InOutQuad }
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.label
            color: sf.textSecondary
            font.family: "Segoe UI"
            font.pixelSize: sf.fontBody
        }
    }
}
