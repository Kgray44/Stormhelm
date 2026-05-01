import QtQuick 2.15

StormforgeGlassPanel {
    id: root

    property var card: ({})
    readonly property string promptTone: resolvePromptTone()

    surfaceRole: "ghost_permission_prompt"
    stateTone: promptTone
    fillOpacity: 0.82
    radius: sf.radiusCard
    implicitWidth: 600
    implicitHeight: promptColumn.implicitHeight + sf.space4 * 2
    visible: hasPrompt()

    StormforgeTokens {
        id: sf
    }

    function textValue(value) {
        if (value === undefined || value === null)
            return ""
        return String(value)
    }

    function resolvePromptTone() {
        var state = String(card.resultState || card.state || card.status || "").toLowerCase()
        var text = String((card.title || "") + " " + (card.body || "") + " " + (card.summary || "")).toLowerCase()
        if (state.indexOf("approval") >= 0 || text.indexOf("approval") >= 0 || text.indexOf("permission") >= 0)
            return "approval_required"
        if (state.indexOf("blocked") >= 0 || text.indexOf("blocked") >= 0)
            return "blocked"
        if (state.indexOf("failed") >= 0 || text.indexOf("failed") >= 0 || text.indexOf("error") >= 0)
            return "failed"
        return "idle"
    }

    function hasPrompt() {
        return promptTone === "approval_required" || promptTone === "blocked" || promptTone === "failed"
    }

    Column {
        id: promptColumn
        anchors.fill: parent
        anchors.margins: sf.space4
        spacing: sf.space2

        Row {
            width: parent.width
            spacing: sf.space3

            StormforgeStatusChip {
                label: root.promptTone === "approval_required" ? "approval" : root.promptTone
                stateTone: root.promptTone
            }

            Text {
                width: Math.max(0, parent.width - 112)
                text: root.textValue(root.card.title || "Action needs attention")
                color: sf.textPrimary
                font.family: "Segoe UI Semibold"
                font.pixelSize: sf.fontTitle
                elide: Text.ElideRight
            }
        }

        Text {
            width: parent.width
            text: root.textValue(root.card.body || root.card.summary || root.card.subtitle || "")
            color: sf.textSecondary
            font.family: "Segoe UI"
            font.pixelSize: sf.fontBody
            wrapMode: Text.WrapAtWordBoundaryOrAnywhere
            maximumLineCount: 3
            elide: Text.ElideRight
        }
    }
}
