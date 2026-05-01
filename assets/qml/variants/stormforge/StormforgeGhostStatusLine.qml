import QtQuick 2.15

StormforgeGlassPanel {
    id: root

    property string statusText: ""
    property string connectionText: ""
    property string timeText: ""

    surfaceRole: "ghost_status"
    fillOpacity: 0.62
    radius: sf.radiusCard
    implicitWidth: Math.min(620, Math.max(360, statusLabel.implicitWidth + connectionLabel.implicitWidth + timeLabel.implicitWidth + sf.space7))
    implicitHeight: 44

    StormforgeTokens {
        id: sf
    }

    Row {
        anchors.fill: parent
        anchors.leftMargin: sf.space4
        anchors.rightMargin: sf.space4
        spacing: sf.space3

        Text {
            id: connectionLabel
            anchors.verticalCenter: parent.verticalCenter
            text: root.connectionText
            color: sf.stateAccent(root.stateTone)
            font.family: "Bahnschrift SemiCondensed"
            font.pixelSize: sf.fontSm
            visible: text.length > 0
            elide: Text.ElideRight
        }

        Text {
            id: statusLabel
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(120, parent.width - connectionLabel.width - timeLabel.width - sf.space6)
            text: root.statusText
            color: sf.textPrimary
            font.family: "Segoe UI Semibold"
            font.pixelSize: sf.fontBody
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }

        Text {
            id: timeLabel
            anchors.verticalCenter: parent.verticalCenter
            text: root.timeText
            color: sf.textMuted
            font.family: "Bahnschrift SemiCondensed"
            font.pixelSize: sf.fontSm
            visible: text.length > 0
            elide: Text.ElideRight
        }
    }
}
