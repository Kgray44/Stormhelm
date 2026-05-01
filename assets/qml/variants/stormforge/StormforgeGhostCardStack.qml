import QtQuick 2.15

Item {
    id: root

    property var cards: []
    property string stateTone: "idle"
    readonly property int visibleCardCount: Math.min(2, root.cards ? root.cards.length : 0)

    implicitWidth: contextRegion.implicitWidth
    implicitHeight: contextRegion.implicitHeight
    height: contextRegion.height
    visible: visibleCardCount > 0

    StormforgeTokens {
        id: sf
    }

    Row {
        id: contextRegion
        objectName: "stormforgeGhostContextRegion"
        property int visibleCardCount: root.visibleCardCount
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: sf.space3
        height: childrenRect.height
        width: childrenRect.width
        visible: visibleCardCount > 0

        Repeater {
            model: contextRegion.visibleCardCount

            delegate: StormforgeGhostContextCard {
                required property int index
                card: (root.cards || [])[index] || ({})
            }
        }
    }
}
