import QtQuick 2.15

Item {
    id: root

    property var messages: []
    property bool compact: false
    property bool framed: true
    property bool autoFollow: true

    function followToBottom() {
        if (listView.count > 0) {
            listView.positionViewAtEnd()
        }
    }

    onMessagesChanged: {
        if (root.autoFollow || (root.messages.length > 0 && root.messages[root.messages.length - 1].role === "user")) {
            root.autoFollow = true
            Qt.callLater(root.followToBottom)
        }
    }

    FieldSurface {
        anchors.fill: parent
        visible: root.framed
        radius: compact ? 28 : 34
        padding: compact ? 16 : 20
        tintColor: compact ? "#131d26" : "#15212b"
        edgeColor: compact ? "#5f8698" : "#638da1"
        glowColor: "#7ec4da"
        fillOpacity: compact ? 0.56 : 0.62
        edgeOpacity: compact ? 0.22 : 0.28
        lineOpacity: compact ? 0.05 : 0.08
    }

    ListView {
        id: listView
        anchors.fill: parent
        anchors.margins: root.framed ? (root.compact ? 16 : 22) : 0
        spacing: root.compact ? 8 : 12
        clip: true
        model: root.messages
        onMovementEnded: root.autoFollow = listView.atYEnd
        Component.onCompleted: Qt.callLater(root.followToBottom)

        delegate: Item {
            required property var modelData
            width: listView.width
            implicitHeight: bubble.implicitHeight

            MessageBubble {
                id: bubble
                width: parent.width
                message: modelData
                compact: root.compact
                presentation: root.compact ? "ghost" : "deck"
            }
        }
    }

    Text {
        anchors.centerIn: parent
        visible: listView.count === 0
        text: root.compact ? "The transcript will surface here." : "Stormhelm is holding the chartroom open."
        color: "#87a4b8"
        font.family: "Bahnschrift SemiCondensed"
        font.pixelSize: root.compact ? 16 : 20
        opacity: 0.72
    }
}
