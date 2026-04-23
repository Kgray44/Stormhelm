import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    objectName: "routeInspectorSurface"

    signal actionRequested(var action)

    property var inspectorData: ({})
    property bool panelMode: false

    readonly property var safeData: root.inspectorData || ({})

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
                spacing: 12

                Text {
                    text: root.safeData.statusLabel || ""
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

                Text {
                    text: root.safeData.body || ""
                    color: "#9cb6c2"
                    font.family: "Segoe UI"
                    font.pixelSize: root.panelMode ? 11 : 12
                    wrapMode: Text.Wrap
                    lineHeight: 1.22
                    Layout.fillWidth: true
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    visible: (root.safeData.provenance || []).length > 0

                    Repeater {
                        model: root.safeData.provenance || []

                        delegate: Rectangle {
                            required property var modelData

                            radius: 13
                            height: 28
                            width: chipRow.implicitWidth + 18
                            color: "#10202a"
                            border.width: 1
                            border.color: "#33586b"

                            Row {
                                id: chipRow
                                anchors.centerIn: parent
                                spacing: 6

                                Text {
                                    text: modelData.label
                                    color: "#7f9cab"
                                    font.family: "Bahnschrift SemiCondensed"
                                    font.pixelSize: 10
                                }

                                Text {
                                    text: modelData.value
                                    color: "#e2f1f8"
                                    font.family: "Segoe UI Semibold"
                                    font.pixelSize: 10
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
                                    font.pixelSize: 10
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 18
                        color: "#0f1a23"
                        border.width: 1
                        border.color: "#305061"
                        implicitHeight: traceColumn.implicitHeight + 18

                        ColumnLayout {
                            id: traceColumn
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8

                            Text {
                                text: "Trace"
                                color: "#e5f2f8"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 14
                            }

                            Repeater {
                                model: root.safeData.trace || []

                                delegate: ColumnLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        text: modelData.label
                                        color: "#89a6b3"
                                        font.family: "Bahnschrift SemiCondensed"
                                        font.pixelSize: 10
                                    }

                                    Text {
                                        text: modelData.value
                                        color: "#edf7fb"
                                        font.family: "Segoe UI Semibold"
                                        font.pixelSize: 11
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 18
                        color: "#0f1a23"
                        border.width: 1
                        border.color: "#305061"
                        implicitHeight: supportColumn.implicitHeight + 18

                        ColumnLayout {
                            id: supportColumn
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 8

                            Text {
                                text: "Support"
                                color: "#e5f2f8"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 14
                            }

                            Repeater {
                                model: root.safeData.supportSystems || []

                                delegate: ColumnLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        text: modelData.label
                                        color: "#89a6b3"
                                        font.family: "Bahnschrift SemiCondensed"
                                        font.pixelSize: 10
                                    }

                                    Text {
                                        text: modelData.value
                                        color: "#edf7fb"
                                        font.family: "Segoe UI Semibold"
                                        font.pixelSize: 11
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
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
