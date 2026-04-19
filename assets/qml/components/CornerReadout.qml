import QtQuick 2.15

Item {
    id: root

    property string label: ""
    property string primary: ""
    property string secondary: ""
    property bool rightAligned: false

    implicitWidth: 220
    implicitHeight: meta.implicitHeight
    opacity: 0.78

    Column {
        id: meta
        width: parent.width
        spacing: 5

        Text {
            width: parent.width
            text: root.label
            color: "#90b0bd"
            font.family: "Bahnschrift SemiCondensed"
            font.pixelSize: 11
            font.letterSpacing: 1.9
            horizontalAlignment: root.rightAligned ? Text.AlignRight : Text.AlignLeft
        }

        Text {
            width: parent.width
            text: root.primary
            color: "#e4f2f8"
            font.family: "Segoe UI Semibold"
            font.pixelSize: 14
            wrapMode: Text.Wrap
            horizontalAlignment: root.rightAligned ? Text.AlignRight : Text.AlignLeft
        }

        Text {
            width: parent.width
            text: root.secondary
            color: "#89a5b3"
            font.family: "Segoe UI"
            font.pixelSize: 11
            wrapMode: Text.Wrap
            horizontalAlignment: root.rightAligned ? Text.AlignRight : Text.AlignLeft
        }
    }
}
