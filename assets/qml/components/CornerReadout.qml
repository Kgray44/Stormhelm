import QtQuick 2.15

Item {
    id: root

    property string label: ""
    property string primary: ""
    property string secondary: ""
    property bool rightAligned: false
    property real tone: 0
    property real contrastBoost: 0.08
    property real shadowOpacity: 0.1
    property real backdropOpacity: 0.04

    implicitWidth: 220
    implicitHeight: meta.implicitHeight
    opacity: 0.78

    function toneColor(baseColor) {
        if (root.tone > 0) {
            return Qt.darker(baseColor, 1 + root.tone * 0.7)
        }
        if (root.tone < 0) {
            return Qt.lighter(baseColor, 1 + Math.abs(root.tone) * 0.45)
        }
        return baseColor
    }

    function contrastColor(baseColor, boost) {
        return Qt.lighter(root.toneColor(baseColor), 1 + boost)
    }

    Rectangle {
        anchors.fill: meta
        anchors.margins: -10
        radius: 18
        color: Qt.rgba(root.toneColor("#101923").r, root.toneColor("#101923").g, root.toneColor("#101923").b, root.backdropOpacity)
        border.width: 1
        border.color: Qt.rgba(0.64, 0.82, 0.9, root.backdropOpacity * 0.48)
        antialiasing: true
        visible: root.backdropOpacity > 0.01
    }

    Column {
        id: meta
        width: parent.width
        spacing: 5

        Text {
            width: parent.width
            text: root.label
            color: root.contrastColor("#90b0bd", root.contrastBoost * 0.22)
            font.family: "Bahnschrift SemiCondensed"
            font.pixelSize: 11
            font.letterSpacing: 1.9
            horizontalAlignment: root.rightAligned ? Text.AlignRight : Text.AlignLeft
            style: Text.Raised
            styleColor: Qt.rgba(0.01, 0.04, 0.07, root.shadowOpacity)
        }

        Text {
            width: parent.width
            text: root.primary
            color: root.contrastColor("#e4f2f8", root.contrastBoost * 0.44)
            font.family: "Segoe UI Semibold"
            font.pixelSize: 14
            wrapMode: Text.Wrap
            horizontalAlignment: root.rightAligned ? Text.AlignRight : Text.AlignLeft
            style: Text.Raised
            styleColor: Qt.rgba(0.01, 0.04, 0.07, root.shadowOpacity)
        }

        Text {
            width: parent.width
            text: root.secondary
            color: root.contrastColor("#89a5b3", root.contrastBoost * 0.3)
            font.family: "Segoe UI"
            font.pixelSize: 11
            wrapMode: Text.Wrap
            horizontalAlignment: root.rightAligned ? Text.AlignRight : Text.AlignLeft
            style: Text.Raised
            styleColor: Qt.rgba(0.01, 0.04, 0.07, root.shadowOpacity)
        }
    }
}
