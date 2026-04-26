import QtQuick 2.15

Item {
    id: root

    property var card: ({
        subtitle: "",
        title: "",
        body: ""
    })
    property string presentation: "deck"
    property var ghostStyle: ({})
    readonly property var safeCard: root.card || ({
        subtitle: "",
        title: "",
        body: ""
    })
    readonly property real adaptiveTone: root.presentation === "ghost" && root.ghostStyle && root.ghostStyle["tone"] !== undefined ? Number(root.ghostStyle["tone"]) : 0
    readonly property real adaptiveTextContrast: root.presentation === "ghost" && root.ghostStyle && root.ghostStyle["textContrast"] !== undefined ? Number(root.ghostStyle["textContrast"]) : 0
    readonly property real adaptiveSecondaryTextContrast: root.presentation === "ghost" && root.ghostStyle && root.ghostStyle["secondaryTextContrast"] !== undefined ? Number(root.ghostStyle["secondaryTextContrast"]) : 0
    readonly property real adaptiveBackdropOpacity: root.presentation === "ghost" && root.ghostStyle && root.ghostStyle["backdropOpacity"] !== undefined ? Number(root.ghostStyle["backdropOpacity"]) : 0.04

    implicitWidth: presentation === "ghost" ? 214 : 254
    implicitHeight: presentation === "ghost" ? 112 : 150

    function toneColor(baseColor) {
        if (root.adaptiveTone > 0) {
            return Qt.darker(baseColor, 1 + root.adaptiveTone * 0.7)
        }
        if (root.adaptiveTone < 0) {
            return Qt.lighter(baseColor, 1 + Math.abs(root.adaptiveTone) * 0.45)
        }
        return baseColor
    }

    function contrastColor(baseColor, boost) {
        return Qt.lighter(root.toneColor(baseColor), 1 + boost)
    }

    FieldSurface {
        anchors.fill: parent
        radius: presentation === "ghost" ? 22 : 26
        padding: presentation === "ghost" ? 14 : 16
        tintColor: presentation === "ghost" ? root.toneColor("#14212c") : "#16222d"
        edgeColor: presentation === "ghost" ? root.contrastColor("#567f92", root.adaptiveTextContrast * 0.24) : "#618ea4"
        glowColor: "#7cc4da"
        fillOpacity: presentation === "ghost" ? 0.44 + root.adaptiveBackdropOpacity * 0.4 : 0.68
        edgeOpacity: presentation === "ghost" ? 0.22 + root.adaptiveTextContrast * 0.16 : 0.3
        lineOpacity: presentation === "ghost" ? 0.05 + root.adaptiveSecondaryTextContrast * 0.08 : 0.08

        Column {
            anchors.fill: parent
            spacing: 6
            clip: root.presentation === "ghost"

            Text {
                width: parent.width
                text: root.safeCard.subtitle
                color: presentation === "ghost" ? root.contrastColor("#ae8558", root.adaptiveSecondaryTextContrast * 0.16) : "#ae8558"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: root.presentation === "ghost" ? 10 : 12
                font.letterSpacing: 1.7
                elide: Text.ElideRight
                visible: text.length > 0
            }

            Text {
                width: parent.width
                text: root.safeCard.title
                color: presentation === "ghost" ? root.contrastColor("#eef7fb", root.adaptiveTextContrast * 0.3) : "#eef7fb"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: root.presentation === "ghost" ? 15 : 18
                elide: Text.ElideRight
            }

            Text {
                width: parent.width
                text: root.safeCard.body
                color: presentation === "ghost" ? root.contrastColor("#bed1da", root.adaptiveSecondaryTextContrast * 0.28) : "#bed1da"
                wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                maximumLineCount: root.presentation === "ghost" ? 3 : 0
                elide: root.presentation === "ghost" ? Text.ElideRight : Text.ElideNone
                font.family: "Segoe UI"
                font.pixelSize: root.presentation === "ghost" ? 12 : 13
                lineHeight: 1.22
            }
        }
    }
}
