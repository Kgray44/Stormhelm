import QtQuick 2.15

Item {
    id: root

    property real coreBottom: 0
    property real deckProgress: 0
    property var messages: []
    property var contextCards: []
    property var cornerReadouts: []
    property string statusLine: ""
    property string connectionLabel: ""
    property string timeLabel: ""
    readonly property int messageStartIndex: Math.max(0, root.messages.length - 2)

    enabled: false

    Repeater {
        model: root.cornerReadouts

        delegate: CornerReadout {
            required property var modelData

            width: 220
            label: modelData.label
            primary: modelData.primary
            secondary: modelData.secondary
            rightAligned: modelData.corner === "top_right" || modelData.corner === "bottom_right"
            anchors.top: modelData.corner === "top_left" || modelData.corner === "top_right" ? parent.top : undefined
            anchors.bottom: modelData.corner === "bottom_left" || modelData.corner === "bottom_right" ? parent.bottom : undefined
            anchors.left: modelData.corner === "top_left" || modelData.corner === "bottom_left" ? parent.left : undefined
            anchors.right: modelData.corner === "top_right" || modelData.corner === "bottom_right" ? parent.right : undefined
            anchors.topMargin: 42
            anchors.bottomMargin: 54
            anchors.leftMargin: 54
            anchors.rightMargin: 54
            opacity: (1 - root.deckProgress * 0.58) * 0.84
        }
    }

    Column {
        width: Math.min(parent.width * 0.72, 940)
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.coreBottom + 14 + root.deckProgress * 26
        spacing: 14
        opacity: 1 - root.deckProgress * 0.46

        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width * 0.7, 620)
            spacing: 7
            visible: root.messages.length > 0

            Repeater {
                model: root.messages.slice(root.messageStartIndex)

                delegate: Item {
                    required property var modelData
                    width: parent.width
                    height: lineText.implicitHeight

                    Text {
                        id: lineText
                        width: parent.width
                        text: modelData.speaker + "   " + modelData.content
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        color: modelData.role === "user" ? "#d8eef8" : "#edf7fb"
                        font.family: modelData.role === "user" ? "Segoe UI Semibold" : "Segoe UI"
                        font.pixelSize: 13
                        opacity: 0.88
                    }
                }
            }
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 14
            visible: root.contextCards.length > 0
            opacity: 0.9 - root.deckProgress * 0.28

            Repeater {
                model: root.contextCards

                delegate: ContextCard {
                    required property var modelData
                    card: modelData
                    presentation: "ghost"
                }
            }
        }
    }
}
