import QtQuick 2.15

Rectangle {
    id: root

    signal clicked()

    property string text: ""
    property string stateTone: "idle"
    property bool enabledState: true

    implicitWidth: Math.max(76, buttonText.implicitWidth + sf.space5 * 2)
    implicitHeight: 34
    radius: sf.radiusControl
    color: enabledState ? sf.stateFill(stateTone) : Qt.rgba(sf.unavailable.r, sf.unavailable.g, sf.unavailable.b, 0.08)
    border.width: 1
    border.color: enabledState ? sf.stateStroke(stateTone) : Qt.rgba(sf.unavailable.r, sf.unavailable.g, sf.unavailable.b, 0.38)
    opacity: enabledState ? 1 : sf.opacityDisabled

    StormforgeTokens {
        id: sf
    }

    Text {
        id: buttonText
        anchors.centerIn: parent
        text: root.text
        color: enabledState ? sf.stateText(stateTone) : sf.textMuted
        font.family: "Segoe UI Semibold"
        font.pixelSize: sf.fontBody
        elide: Text.ElideRight
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.enabledState
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
