import QtQuick 2.15

Item {
    id: root

    property string label: ""
    property string value: ""
    property string stateTone: "idle"

    implicitWidth: Math.max(labelText.implicitWidth, valueText.implicitWidth)
    implicitHeight: labelText.implicitHeight + valueText.implicitHeight + sf.space1

    StormforgeTokens {
        id: sf
    }

    Column {
        anchors.fill: parent
        spacing: sf.space1

        Text {
            id: labelText
            width: parent.width
            text: root.label
            color: sf.textMuted
            font.family: "Bahnschrift SemiCondensed"
            font.pixelSize: sf.fontXs
            elide: Text.ElideRight
        }

        Text {
            id: valueText
            width: parent.width
            text: root.value
            color: root.stateTone === "idle" ? sf.textPrimary : sf.stateAccent(root.stateTone)
            font.family: "Segoe UI Semibold"
            font.pixelSize: sf.fontTitle
            elide: Text.ElideRight
        }
    }
}
