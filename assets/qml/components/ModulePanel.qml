import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    signal saveNote(string title, string content)
    property bool panelMode: false

    property var moduleData: ({
        key: "placeholder",
        kind: "placeholder",
        title: "Module",
        eyebrow: "",
        headline: "",
        body: "",
        stats: [],
        sections: [],
        entries: []
    })
    readonly property var safeData: root.moduleData || ({
        key: "placeholder",
        kind: "placeholder",
        title: "Module",
        eyebrow: "",
        headline: "",
        body: "",
        stats: [],
        sections: [],
        entries: []
    })

    implicitHeight: {
        switch (safeData.kind) {
        case "notes":
            return root.panelMode ? 260 : 320
        case "system":
            return root.panelMode ? 220 : 248
        default:
            return root.panelMode ? 208 : 228
        }
    }

    FieldSurface {
        anchors.fill: parent
        radius: 30
        padding: root.panelMode ? 14 : 18
        tintColor: "#15212b"
        edgeColor: "#628da2"
        glowColor: "#80c6dd"
        fillOpacity: 0.68
        edgeOpacity: 0.26
        lineOpacity: 0.07

        ColumnLayout {
            anchors.fill: parent
            spacing: root.panelMode ? 10 : 12

            Text {
                text: root.safeData.eyebrow
                color: "#b98a56"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: 11
                font.letterSpacing: 1.9
            }

            Text {
                text: root.safeData.title
                color: "#eef7fb"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: root.panelMode ? 18 : 22
            }

            Text {
                text: root.safeData.headline
                color: "#d2e3eb"
                wrapMode: Text.Wrap
                font.family: "Segoe UI Semibold"
                font.pixelSize: root.panelMode ? 13 : 14
            }

            Text {
                text: root.safeData.body
                color: "#94afbc"
                wrapMode: Text.Wrap
                font.family: "Segoe UI"
                font.pixelSize: root.panelMode ? 11 : 12
                lineHeight: 1.24
                Layout.fillWidth: true
                visible: !root.panelMode || text.length < 220
            }

            Flow {
                Layout.fillWidth: true
                spacing: 8
                visible: (root.safeData.stats || []).length > 0

                Repeater {
                    model: root.safeData.stats || []

                    delegate: Rectangle {
                        required property var modelData
                        radius: 13
                        color: "#10202a"
                        border.width: 1
                        border.color: "#33586b"
                        height: 28
                        width: statRow.implicitWidth + 18

                        Row {
                            id: statRow
                            anchors.centerIn: parent
                            spacing: 6

                            Text {
                                text: modelData.label
                                color: "#84a0ae"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 10
                                font.letterSpacing: 1.1
                            }

                            Text {
                                text: modelData.value
                                color: "#edf7fb"
                                font.family: "Segoe UI Semibold"
                                font.pixelSize: 10
                            }
                        }
                    }
                }
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 14
                visible: (root.safeData.sections || []).length > 0
                model: root.safeData.sections || []

                delegate: Column {
                    required property var modelData
                    width: ListView.view.width
                    spacing: 6

                    Text {
                        text: modelData.title
                        width: parent.width
                        color: "#d7e9f1"
                        font.family: "Bahnschrift SemiCondensed"
                        font.pixelSize: 13
                        font.letterSpacing: 1.1
                    }

                    Text {
                        text: modelData.summary
                        width: parent.width
                        color: "#7f9aa8"
                        font.family: "Segoe UI"
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                    }

                    Repeater {
                        model: modelData.entries || []

                        delegate: Column {
                            required property var modelData
                            width: parent.width
                            spacing: 3

                            Text {
                                text: modelData.primary
                                width: parent.width
                                color: "#eef7fb"
                                font.family: "Segoe UI Semibold"
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                            }

                            Text {
                                text: modelData.secondary
                                width: parent.width
                                color: "#8ca7b5"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 10
                                font.letterSpacing: 1.1
                                wrapMode: Text.Wrap
                            }

                            Text {
                                text: modelData.detail
                                visible: text.length > 0
                                width: parent.width
                                color: "#bfd2dc"
                                font.family: "Segoe UI"
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                            }
                        }
                    }
                }
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 10
                visible: (root.safeData.sections || []).length === 0
                model: root.safeData.entries

                delegate: Item {
                    width: ListView.view.width
                    height: details.implicitHeight + 10

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: "#315262"
                        opacity: 0.22
                    }

                    Column {
                        id: details
                        anchors.left: parent.left
                        anchors.right: parent.right
                        spacing: 4

                        Text {
                            text: modelData.primary
                            color: "#eaf4f9"
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                        }

                        Text {
                            text: modelData.secondary
                            color: "#92adbc"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 11
                            font.letterSpacing: 1.2
                        }

                        Text {
                            text: modelData.detail
                            visible: text.length > 0
                            color: "#c5d7e1"
                            font.family: "Segoe UI"
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }

            ColumnLayout {
                visible: root.safeData.kind === "notes"
                Layout.fillWidth: true
                spacing: 8

                TextField {
                    id: noteTitle
                    Layout.fillWidth: true
                    placeholderText: "Logbook title"
                    color: "#edf7fb"
                    placeholderTextColor: "#7e9ba8"
                    background: Rectangle {
                        radius: 14
                        color: "#13212b"
                        border.width: 1
                        border.color: "#5d889b"
                    }
                }

                TextArea {
                    id: noteBody
                    Layout.fillWidth: true
                    Layout.preferredHeight: 70
                    placeholderText: "Add a local note..."
                    wrapMode: TextEdit.Wrap
                    color: "#edf7fb"
                    placeholderTextColor: "#7e9ba8"
                    background: Rectangle {
                        radius: 16
                        color: "#13212b"
                        border.width: 1
                        border.color: "#5d889b"
                    }
                }

                Button {
                    text: "Write To Logbook"
                    Layout.alignment: Qt.AlignRight
                    background: Rectangle {
                        radius: 18
                        color: "#17374a6a"
                        border.width: 1
                        border.color: "#7ab3c8c4"
                    }
                    contentItem: Text {
                        text: parent.text
                        color: "#eef8fb"
                        font.family: "Bahnschrift SemiCondensed"
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        root.saveNote(noteTitle.text, noteBody.text)
                        noteTitle.clear()
                        noteBody.clear()
                    }
                }
            }
        }
    }
}
