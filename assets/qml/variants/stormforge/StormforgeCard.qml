import QtQuick 2.15

StormforgeGlassPanel {
    id: root

    property string title: ""
    property string subtitle: ""
    property string body: ""

    surfaceRole: "card"
    radius: sf.radiusCard
    fillColor: sf.panelFill
    fillOpacity: sf.opacityPanel

    StormforgeTokens {
        id: sf
    }

    Column {
        anchors.fill: parent
        anchors.margins: sf.space4
        spacing: sf.space2

        Text {
            width: parent.width
            text: root.title
            visible: text.length > 0
            color: sf.textPrimary
            font.family: "Segoe UI Semibold"
            font.pixelSize: sf.fontTitle
            elide: Text.ElideRight
        }

        Text {
            width: parent.width
            text: root.subtitle
            visible: text.length > 0
            color: sf.textSecondary
            font.family: "Segoe UI"
            font.pixelSize: sf.fontSm
            elide: Text.ElideRight
        }

        Text {
            width: parent.width
            text: root.body
            visible: text.length > 0
            color: sf.textSecondary
            font.family: "Segoe UI"
            font.pixelSize: sf.fontBody
            wrapMode: Text.WrapAtWordBoundaryOrAnywhere
            maximumLineCount: 3
            elide: Text.ElideRight
        }
    }
}
