import QtQuick 2.15

Rectangle {
    id: root

    property string label: ""
    property string stateTone: "idle"
    readonly property string resolvedTone: sf.normalizeState(stateTone)

    implicitWidth: chipText.implicitWidth + sf.space4 * 2
    implicitHeight: 26
    radius: sf.radiusChip
    color: sf.stateFill(resolvedTone)
    border.width: 1
    border.color: sf.stateStroke(resolvedTone)

    StormforgeTokens {
        id: sf
    }

    Text {
        id: chipText
        anchors.centerIn: parent
        text: root.label
        color: sf.stateText(root.resolvedTone)
        font.family: "Bahnschrift SemiCondensed"
        font.pixelSize: sf.fontSm
        elide: Text.ElideRight
    }
}
