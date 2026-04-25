import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    property var card: ({})
    property bool compact: false

    readonly property var safeCard: root.card || ({})

    implicitWidth: root.compact ? 420 : 520
    implicitHeight: surface.implicitHeight

    FieldSurface {
        id: surface
        width: parent.width
        implicitHeight: content.implicitHeight + padding * 2
        radius: root.compact ? 24 : 28
        padding: root.compact ? 16 : 18
        tintColor: "#14222c"
        edgeColor: "#638ea2"
        glowColor: "#80c6dd"
        fillOpacity: root.compact ? 0.54 : 0.66
        edgeOpacity: 0.28
        lineOpacity: 0.08

        ColumnLayout {
            id: content
            anchors.fill: parent
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Text {
                    text: root.safeCard.statusLabel || ""
                    color: "#bb8d59"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: root.compact ? 11 : 12
                    font.letterSpacing: 1.4
                    visible: text.length > 0
                }

                Text {
                    Layout.fillWidth: true
                    text: root.safeCard.routeLabel || ""
                    color: "#7fa0af"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: root.compact ? 10 : 11
                    font.letterSpacing: 1.1
                    horizontalAlignment: Text.AlignRight
                    visible: text.length > 0
                }
            }

            Text {
                Layout.fillWidth: true
                text: root.safeCard.title || ""
                color: "#eef7fb"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: root.compact ? 20 : 24
                wrapMode: Text.Wrap
            }

            Text {
                Layout.fillWidth: true
                text: root.safeCard.subtitle || ""
                color: "#d1e3eb"
                font.family: "Segoe UI Semibold"
                font.pixelSize: root.compact ? 12 : 13
                wrapMode: Text.Wrap
                visible: text.length > 0
            }

            Text {
                Layout.fillWidth: true
                text: root.safeCard.body || ""
                color: "#c0d5df"
                font.family: "Segoe UI"
                font.pixelSize: root.compact ? 12 : 13
                wrapMode: Text.Wrap
                lineHeight: 1.22
            }

            Flow {
                id: provenanceFlow
                Layout.fillWidth: true
                spacing: 8
                visible: (root.safeCard.provenance || []).length > 0

                Repeater {
                    model: root.safeCard.provenance || []

                    delegate: Rectangle {
                        required property var modelData

                        radius: 13
                        height: 28
                        width: Math.min(chipLabel.implicitWidth + chipValue.implicitWidth + 32, Math.max(120, provenanceFlow.width))
                        clip: true
                        color: "#0f1d26"
                        border.width: 1
                        border.color: "#335767"

                        Row {
                            id: chipRow
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 9
                            anchors.rightMargin: 9
                            spacing: 7

                            Text {
                                id: chipLabel
                                text: modelData.label
                                color: "#7d9aa8"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 10
                                font.letterSpacing: 1.0
                            }

                            Text {
                                id: chipValue
                                text: modelData.value
                                color: "#e8f4f9"
                                font.family: "Segoe UI Semibold"
                                font.pixelSize: 10
                                width: Math.max(20, parent.width - chipLabel.width - chipRow.spacing)
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }
        }
    }
}
