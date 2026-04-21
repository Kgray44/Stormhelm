import QtQuick 2.15

Item {
    id: root

    property var message: ({
        role: "assistant",
        speaker: "Stormhelm",
        shortTime: "",
        content: ""
    })
    readonly property var safeMessage: root.message || ({
        role: "assistant",
        speaker: "Stormhelm",
        shortTime: "",
        content: "",
        nextSuggestion: ({})
    })
    readonly property var safeNextSuggestion: root.safeMessage && root.safeMessage.nextSuggestion ? root.safeMessage.nextSuggestion : ({})
    property bool compact: false
    property string presentation: "deck"
    readonly property bool userMessage: safeMessage.role === "user"

    width: ListView.view ? ListView.view.width : parent.width
    implicitHeight: bubble.implicitHeight + 8

    FieldSurface {
        id: bubble
        width: Math.min(root.width * (root.compact ? 0.88 : 0.92), root.userMessage ? 560 : 720)
        implicitHeight: contentColumn.implicitHeight + padding * 2
        anchors.horizontalCenter: root.userMessage ? undefined : parent.horizontalCenter
        anchors.right: root.userMessage ? parent.right : undefined
        anchors.left: root.userMessage ? undefined : parent.left
        radius: root.compact ? 20 : 24
        padding: root.compact ? 12 : 16
        tintColor: root.userMessage ? "#18324a" : "#15222c"
        edgeColor: root.userMessage ? "#73a8bf" : "#5f8598"
        glowColor: root.userMessage ? "#8fd5ec" : "#79c0d8"
        fillOpacity: root.userMessage ? 0.7 : 0.58
        edgeOpacity: root.userMessage ? 0.34 : 0.24
        lineOpacity: 0.05
        accentTopLine: !root.userMessage

        Column {
            id: contentColumn
            anchors.fill: parent
            spacing: 8

            Row {
                spacing: 8

                Text {
                    text: root.safeMessage.speaker
                    color: root.userMessage ? "#e3f4fd" : "#d6e6ef"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: root.compact ? 13 : 15
                    font.letterSpacing: 1.4
                }

                Text {
                    text: root.safeMessage.shortTime
                    color: "#83a0af"
                    font.pixelSize: root.compact ? 11 : 12
                }
            }

            Text {
                width: parent.width
                text: root.safeMessage.content
                wrapMode: Text.Wrap
                color: "#f1f7fb"
                font.family: "Segoe UI"
                font.pixelSize: root.compact ? 14 : 16
                lineHeight: 1.25
            }

            Text {
                width: parent.width
                visible: !root.userMessage && !!root.safeNextSuggestion.title
                text: "Next: " + root.safeNextSuggestion.title
                wrapMode: Text.Wrap
                color: "#9fd0e3"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: root.compact ? 12 : 13
                font.letterSpacing: 0.8
            }
        }
    }
}
