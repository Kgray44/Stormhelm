import QtQuick 2.15

Item {
    id: root

    property string title: ""
    property string subtitle: ""

    implicitWidth: 260
    implicitHeight: titleText.implicitHeight + (subtitleText.visible ? subtitleText.implicitHeight + sf.space1 : 0)

    StormforgeTokens {
        id: sf
    }

    Column {
        anchors.fill: parent
        spacing: sf.space1

        Text {
            id: titleText
            width: parent.width
            text: root.title
            color: sf.textPrimary
            font.family: "Bahnschrift SemiCondensed"
            font.pixelSize: sf.fontDeckTitle
            elide: Text.ElideRight
        }

        Text {
            id: subtitleText
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
