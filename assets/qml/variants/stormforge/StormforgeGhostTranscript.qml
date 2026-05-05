import QtQuick 2.15

StormforgeGlassPanel {
    id: root

    property var messages: []
    property string emptyText: ""
    property bool captureActive: false
    property string draftText: ""
    property string hintText: ""
    readonly property int visibleMessageCount: Math.min(2, messages ? messages.length : 0)
    readonly property int messageStartIndex: Math.max(0, (messages ? messages.length : 0) - 2)
    readonly property bool draftVisible: captureActive
    readonly property string visibleDraftText: draftText

    surfaceRole: "ghost_transcript"
    fillOpacity: draftVisible || visibleMessageCount > 0 ? 0.58 : 0.34
    radius: sf.radiusCard
    implicitWidth: 560
    implicitHeight: draftVisible || visibleMessageCount > 0 ? transcriptColumn.implicitHeight + sf.space4 * 2 : 38

    StormforgeTokens {
        id: sf
    }

    Column {
        id: transcriptColumn
        anchors.fill: parent
        anchors.margins: sf.space4
        spacing: sf.space2
        clip: true

        Text {
            width: parent.width
            text: root.emptyText
            visible: !root.draftVisible && root.visibleMessageCount === 0 && text.length > 0
            color: sf.textSecondary
            font.family: "Segoe UI"
            font.pixelSize: sf.fontBody
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }

        Text {
            id: draftLine
            objectName: "stormforgeGhostDraftLine"
            width: parent.width
            text: "You   " + (root.visibleDraftText.length > 0 ? root.visibleDraftText : (root.hintText.length > 0 ? root.hintText : "Type to command"))
            visible: root.draftVisible
            color: root.visibleDraftText.length > 0 ? sf.textPrimary : sf.textSecondary
            font.family: "Segoe UI Semibold"
            font.pixelSize: sf.fontBody
            wrapMode: Text.WrapAtWordBoundaryOrAnywhere
            maximumLineCount: 3
            elide: Text.ElideRight
        }

        Repeater {
            model: root.visibleMessageCount

            delegate: Text {
                required property int index

                readonly property var message: root.messages[root.messageStartIndex + index] || ({})
                width: parent.width
                text: String(message.speaker || (message.role === "user" ? "You" : "Stormhelm")) + "   " + String(message.content || "")
                color: message.role === "user" ? sf.textSecondary : sf.textPrimary
                font.family: message.role === "user" ? "Segoe UI Semibold" : "Segoe UI"
                font.pixelSize: sf.fontBody
                wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }
    }
}
