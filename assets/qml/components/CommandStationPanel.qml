import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    objectName: "commandStationPanel-" + String(root.safeData.stationId || "")

    signal actionRequested(var action)

    property var stationData: ({})
    property bool panelMode: false
    readonly property var safeData: root.stationData || ({})

    function chipFill(tone) {
        switch (String(tone || "")) {
        case "live":
            return "#133129"
        case "attention":
            return "#173041"
        case "warning":
            return "#352126"
        case "stale":
            return "#2c2428"
        default:
            return "#10202a"
        }
    }

    function chipBorder(tone) {
        switch (String(tone || "")) {
        case "live":
            return "#71c4a7"
        case "attention":
            return "#7ebed7"
        case "warning":
            return "#c88b92"
        case "stale":
            return "#b79aa6"
        default:
            return "#34586a"
        }
    }

    FieldSurface {
        anchors.fill: parent
        radius: root.panelMode ? 24 : 28
        padding: root.panelMode ? 14 : 18
        tintColor: "#14212b"
        edgeColor: "#628da0"
        glowColor: "#7ec6dc"
        fillOpacity: root.panelMode ? 0.66 : 0.72
        edgeOpacity: 0.28
        lineOpacity: 0.07

        Flickable {
            anchors.fill: parent
            clip: true
            contentWidth: width
            contentHeight: content.implicitHeight

            ColumnLayout {
                id: content
                width: parent.width
                spacing: 10

                Text {
                    text: root.safeData.eyebrow || ""
                    color: "#b98a56"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: 11
                    font.letterSpacing: 1.5
                    visible: text.length > 0
                }

                Text {
                    text: root.safeData.title || ""
                    color: "#eef7fb"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: root.panelMode ? 18 : 22
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }

                Text {
                    text: root.safeData.subtitle || ""
                    color: "#d2e3eb"
                    font.family: "Segoe UI Semibold"
                    font.pixelSize: root.panelMode ? 12 : 13
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                    visible: text.length > 0
                }

                Flow {
                    id: stationChipFlow
                    Layout.fillWidth: true
                    spacing: 8
                    visible: (root.safeData.chips || []).length > 0

                    Repeater {
                        model: root.safeData.chips || []

                        delegate: Rectangle {
                            required property var modelData

                            radius: 13
                            height: 28
                            width: Math.min(chipLabel.implicitWidth + chipValue.implicitWidth + 31, Math.max(120, stationChipFlow.width))
                            clip: true
                            color: root.chipFill(modelData.tone)
                            border.width: 1
                            border.color: root.chipBorder(modelData.tone)

                            Row {
                                id: chipRow
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 9
                                anchors.rightMargin: 9
                                spacing: 6

                                Text {
                                    id: chipLabel
                                    text: modelData.label
                                    color: "#7f9cab"
                                    font.family: "Bahnschrift SemiCondensed"
                                    font.pixelSize: 10
                                }

                                Text {
                                    id: chipValue
                                    text: modelData.value
                                    color: "#e2f1f8"
                                    font.family: "Segoe UI Semibold"
                                    font.pixelSize: 10
                                    width: Math.max(20, parent.width - chipLabel.width - chipRow.spacing)
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    visible: (root.safeData.invalidations || []).length > 0

                    Repeater {
                        model: root.safeData.invalidations || []

                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            radius: 14
                            color: "#21181d"
                            border.width: 1
                            border.color: "#8b6f79"
                            implicitHeight: invalidationColumn.implicitHeight + 16

                            ColumnLayout {
                                id: invalidationColumn
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 3

                                Text {
                                    text: modelData.label
                                    color: "#f2d4da"
                                    font.family: "Bahnschrift SemiCondensed"
                                    font.pixelSize: 10
                                }

                                Text {
                                    text: modelData.reason
                                    color: "#e7dbe0"
                                    font.family: "Segoe UI"
                                    font.pixelSize: 11
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }
                }

                Repeater {
                    model: root.safeData.sections || []

                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        radius: 18
                        color: "#0f1a23"
                        border.width: 1
                        border.color: "#305061"
                        implicitHeight: sectionColumn.implicitHeight + 18

                        ColumnLayout {
                            id: sectionColumn
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8

                            Text {
                                text: modelData.title
                                color: "#e5f2f8"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 14
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }

                            Repeater {
                                model: modelData.entries || []

                                delegate: ColumnLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        text: modelData.primary
                                        color: "#bed2dc"
                                        font.family: "Bahnschrift SemiCondensed"
                                        font.pixelSize: 10
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                    }

                                    Text {
                                        text: modelData.secondary
                                        color: "#edf7fb"
                                        font.family: "Segoe UI Semibold"
                                        font.pixelSize: 11
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                    }

                                    Text {
                                        text: modelData.detail
                                        color: "#bfd2dc"
                                        font.family: "Segoe UI"
                                        font.pixelSize: 10
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                        visible: text.length > 0
                                    }
                                }
                            }
                        }
                    }
                }

                CommandActionStrip {
                    Layout.fillWidth: true
                    actions: root.safeData.actions || []
                    compact: true
                    onActionTriggered: function(action) { root.actionRequested(action) }
                }
            }
        }
    }
}
