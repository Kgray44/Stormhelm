import QtQuick 2.15

Item {
    id: root
    objectName: "transcriptTimeline"

    property var messages: []
    property bool compact: false
    property bool framed: true
    property bool autoFollow: true
    property bool followPending: false
    readonly property real followThreshold: 28

    function nearBottom() {
        var remaining = listView.contentHeight - (listView.contentY + listView.height)
        return listView.atYEnd || remaining <= root.followThreshold
    }

    function followToBottom() {
        if (listView.count > 0) {
            listView.positionViewAtEnd()
        }
        root.followPending = false
        root.autoFollow = true
    }

    onMessagesChanged: {
        if (root.autoFollow || root.nearBottom()) {
            root.followPending = true
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
        objectName: "transcriptList"
        anchors.fill: parent
        anchors.margins: root.framed ? (root.compact ? 16 : 22) : 0
        spacing: root.compact ? 8 : 12
        clip: true
        model: root.messages
        boundsBehavior: Flickable.StopAtBounds
        onMovementStarted: {
            if (!root.nearBottom()) {
                root.autoFollow = false
                root.followPending = false
            }
        }
        onMovementEnded: root.autoFollow = root.nearBottom()
        onContentHeightChanged: {
            if (root.followPending) {
                Qt.callLater(root.followToBottom)
            }
        }
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
