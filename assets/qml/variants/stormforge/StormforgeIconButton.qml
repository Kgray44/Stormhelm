import QtQuick 2.15

Rectangle {
    id: root

    signal clicked()

    property string iconText: ""
    property string accessibleName: ""
    property string stateTone: "idle"
    property bool enabledState: true

    width: 34
    height: 34
    radius: sf.radiusControl
    color: enabledState ? sf.stateFill(stateTone) : Qt.rgba(sf.unavailable.r, sf.unavailable.g, sf.unavailable.b, 0.08)
    border.width: 1
    border.color: enabledState ? sf.stateStroke(stateTone) : Qt.rgba(sf.unavailable.r, sf.unavailable.g, sf.unavailable.b, 0.38)
    opacity: enabledState ? 1 : sf.opacityDisabled

    Accessible.name: accessibleName
    Accessible.role: Accessible.Button

    StormforgeTokens {
        id: sf
    }

    Text {
        anchors.centerIn: parent
        text: root.iconText
        color: enabledState ? sf.stateText(stateTone) : sf.textMuted
        font.family: "Segoe UI Semibold"
        font.pixelSize: sf.fontTitle
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.enabledState
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
