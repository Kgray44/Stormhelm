import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    signal activateItem(string itemId)
    signal closeItem(string itemId)

    property var items: []
    property string activeItemId: ""

    implicitHeight: 42

    Flickable {
        anchors.fill: parent
        contentWidth: tabsRow.implicitWidth
        contentHeight: tabsRow.implicitHeight
        clip: true
        interactive: contentWidth > width

        Row {
            id: tabsRow
            spacing: 10

            Repeater {
                model: root.items

                delegate: Rectangle {
                    required property var modelData
                    readonly property bool active: modelData.itemId === root.activeItemId
                    radius: 16
                    height: 34
                    width: Math.min(240, tabRow.implicitWidth + 22)
                    color: active ? "#182b37d8" : "#12212bcc"
                    border.width: 1
                    border.color: active ? "#7eaec0" : "#355465"

                    Row {
                        id: tabRow
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        spacing: 10

                        Text {
                            width: parent.width - closeGlyph.width - 12
                            text: modelData.title || "Item"
                            color: active ? "#eef8fb" : "#c3d7e1"
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }

                        Text {
                            id: closeGlyph
                            text: "\u00d7"
                            color: active ? "#eef8fb" : "#9ab4c0"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 15
                            verticalAlignment: Text.AlignVCenter

                            MouseArea {
                                anchors.fill: parent
                                onClicked: root.closeItem(modelData.itemId)
                            }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton
                        onClicked: root.activateItem(modelData.itemId)
                    }
                }
            }
        }
    }
}
