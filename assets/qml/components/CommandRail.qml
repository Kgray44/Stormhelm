import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: root

    signal activateItem(string key)

    property var items: []
    property real emphasis: hover.hovered ? 1 : 0

    implicitHeight: 66

    HoverHandler {
        id: hover
    }

    FieldSurface {
        anchors.fill: parent
        radius: 28
        padding: 10
        tintColor: "#111922"
        edgeColor: "#517b90"
        glowColor: "#79c1d8"
        fillOpacity: 0.42 + root.emphasis * 0.14
        edgeOpacity: 0.12 + root.emphasis * 0.12
        lineOpacity: 0.05 + root.emphasis * 0.03

        ListView {
            anchors.fill: parent
            orientation: ListView.Horizontal
            spacing: 10
            model: root.items
            interactive: false

            delegate: Item {
                width: 118
                height: 44

                Rectangle {
                    anchors.fill: parent
                    radius: 18
                    color: modelData.active ? "#17384d5a" : "transparent"
                    border.width: modelData.active ? 1 : 0
                    border.color: "#7db9cda0"
                    antialiasing: true
                }

                Rectangle {
                    width: parent.width * 0.52
                    height: 2
                    radius: 1
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 5
                    color: modelData.active ? "#9bd9ec" : "#54788a"
                    opacity: modelData.active ? 0.88 : 0.2
                }

                Text {
                    anchors.centerIn: parent
                    text: modelData.label
                    color: modelData.active ? "#edf8fb" : "#98b5c2"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: 11
                    font.letterSpacing: 1.2
                    elide: Text.ElideRight
                }

                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: root.activateItem(modelData.key)
                    cursorShape: Qt.PointingHandCursor
                }
            }
        }
    }
}
