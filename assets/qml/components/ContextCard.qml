import QtQuick 2.15

Item {
    id: root

    property var card: ({
        subtitle: "",
        title: "",
        body: ""
    })
    property string presentation: "deck"
    readonly property var safeCard: root.card || ({
        subtitle: "",
        title: "",
        body: ""
    })

    implicitWidth: presentation === "ghost" ? 214 : 254
    implicitHeight: presentation === "ghost" ? 112 : 150

    FieldSurface {
        anchors.fill: parent
        radius: presentation === "ghost" ? 22 : 26
        padding: presentation === "ghost" ? 14 : 16
        tintColor: presentation === "ghost" ? "#14212c" : "#16222d"
        edgeColor: presentation === "ghost" ? "#567f92" : "#618ea4"
        glowColor: "#7cc4da"
        fillOpacity: presentation === "ghost" ? 0.48 : 0.68
        edgeOpacity: presentation === "ghost" ? 0.22 : 0.3
        lineOpacity: presentation === "ghost" ? 0.05 : 0.08

        Column {
            anchors.fill: parent
            spacing: 6

            Text {
                text: root.safeCard.subtitle
                color: "#ae8558"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: root.presentation === "ghost" ? 10 : 12
                font.letterSpacing: 1.7
                visible: text.length > 0
            }

            Text {
                text: root.safeCard.title
                color: "#eef7fb"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: root.presentation === "ghost" ? 15 : 18
                elide: Text.ElideRight
            }

            Text {
                text: root.safeCard.body
                color: "#bed1da"
                wrapMode: Text.Wrap
                font.family: "Segoe UI"
                font.pixelSize: root.presentation === "ghost" ? 12 : 13
                lineHeight: 1.22
            }
        }
    }
}
