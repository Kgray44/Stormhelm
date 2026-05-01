import QtQuick 2.15

Rectangle {
    id: root

    property string title: ""
    property string subtitle: ""
    property string stateTone: "idle"
    readonly property string resolvedTone: sf.normalizeState(stateTone)

    implicitHeight: 52
    radius: sf.radiusControl
    color: sf.stateFill(resolvedTone)
    border.width: 1
    border.color: sf.stateStroke(resolvedTone)

    StormforgeTokens {
        id: sf
    }

    Column {
        anchors.fill: parent
        anchors.margins: sf.space3
        spacing: sf.space1

        Text {
            width: parent.width
            text: root.title
            color: sf.textPrimary
            font.family: "Segoe UI Semibold"
            font.pixelSize: sf.fontBody
            elide: Text.ElideRight
        }

        Text {
            width: parent.width
            text: root.subtitle
            visible: text.length > 0
            color: sf.textMuted
            font.family: "Segoe UI"
            font.pixelSize: sf.fontSm
            elide: Text.ElideRight
        }
    }
}
