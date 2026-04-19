import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: root

    signal activateItem(string key)

    property var items: []
    property real revealProgress: 1

    implicitWidth: 158

    Column {
        id: list
        anchors.fill: parent
        spacing: 12

        Repeater {
            model: root.items

            delegate: Item {
                required property var modelData
                width: root.width
                height: labelColumn.implicitHeight + 8
                opacity: 0.42 + (modelData.active ? 0.42 : 0) + root.revealProgress * 0.1

                Rectangle {
                    width: 3
                    height: parent.height - 10
                    radius: 2
                    anchors.left: parent.left
                    anchors.leftMargin: 3
                    anchors.verticalCenter: parent.verticalCenter
                    color: modelData.active ? "#a7d5e6" : "#3b6173"
                    opacity: modelData.active ? 0.82 : 0.34
                }

                Rectangle {
                    width: Math.min(parent.width * 0.78, 114)
                    height: parent.height - 6
                    radius: height / 2
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    color: modelData.active ? "#19384b4d" : "transparent"
                    border.width: modelData.active ? 1 : 0
                    border.color: "#5d8da261"
                    antialiasing: true
                }

                Column {
                    id: labelColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 20
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Text {
                        text: modelData.label
                        color: modelData.active ? "#eef8fb" : "#a6c0cc"
                        font.family: "Bahnschrift SemiCondensed"
                        font.pixelSize: 12
                        font.letterSpacing: 1.1
                        elide: Text.ElideRight
                    }

                    Text {
                        text: modelData.eyebrow
                        color: modelData.active ? "#89a3af" : "#67808c"
                        font.family: "Segoe UI"
                        font.pixelSize: 9
                        elide: Text.ElideRight
                        visible: text.length > 0
                    }
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
