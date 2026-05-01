import QtQuick 2.15

Rectangle {
    id: root

    property string surfaceRole: "glass_panel"
    property string stateTone: "idle"
    property int elevation: sf.elevationLow
    property color fillColor: sf.glassFill
    property color strokeColor: stateTone === "idle" ? Qt.rgba(sf.lineSoft.r, sf.lineSoft.g, sf.lineSoft.b, sf.strokeOpacitySoft) : sf.stateStroke(stateTone)
    property real fillOpacity: sf.opacityGlass

    radius: sf.radiusPanel
    color: Qt.rgba(fillColor.r, fillColor.g, fillColor.b, fillOpacity)
    border.width: 1
    border.color: strokeColor
    clip: false

    StormforgeTokens {
        id: sf
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: -Math.max(1, root.elevation * 3)
        radius: root.radius + Math.max(1, root.elevation * 3)
        color: "transparent"
        border.width: root.elevation > 0 ? 1 : 0
        border.color: root.stateTone === "idle" ? Qt.rgba(sf.signalCyan.r, sf.signalCyan.g, sf.signalCyan.b, sf.glowOpacitySoft) : sf.stateGlow(root.stateTone)
        opacity: root.elevation > 0 ? Math.min(0.46, sf.shadowOpacity + root.elevation * 0.05) : 0
        z: -1
    }

    Behavior on opacity {
        NumberAnimation { duration: sf.durationBase; easing.type: Easing.InOutQuad }
    }
}
