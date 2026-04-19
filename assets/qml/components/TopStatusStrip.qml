import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    property var items: []
    property string stateName: "idle"
    readonly property color accentColor: root.stateName === "warning" ? "#c59159"
                                             : root.stateName === "acting" ? "#c4a067"
                                             : root.stateName === "speaking" ? "#9edfed"
                                             : root.stateName === "listening" ? "#90d8d8"
                                             : root.stateName === "thinking" ? "#8dbed8"
                                             : "#7ec7de"

    implicitHeight: 38

    FieldSurface {
        anchors.fill: parent
        radius: 22
        padding: 10
        tintColor: "#111a23"
        edgeColor: root.accentColor
        glowColor: root.accentColor
        fillOpacity: 0.46
        edgeOpacity: 0.12
        lineOpacity: 0.04

        RowLayout {
            anchors.fill: parent
            spacing: 16

            Text {
                text: "Stormhelm"
                color: Qt.tint("#eaf6fb", Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.2))
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: 14
                font.letterSpacing: 2.2

                Behavior on color {
                    ColorAnimation { duration: 360; easing.type: Easing.InOutQuad }
                }
            }

            Item { Layout.fillWidth: true }

            Repeater {
                model: root.items

                Column {
                    spacing: 1

                    Text {
                        text: modelData.label
                        color: "#87a6b5"
                        font.family: "Bahnschrift SemiCondensed"
                        font.pixelSize: 9
                        font.letterSpacing: 1.6
                    }

                    Text {
                        text: modelData.value
                        color: "#dcecf3"
                        font.family: "Segoe UI Semibold"
                        font.pixelSize: 11
                    }
                }
            }
        }
    }
}
