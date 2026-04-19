import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    signal saveNote(string title, string content)

    property var moduleData: ({
        key: "placeholder",
        kind: "placeholder",
        title: "Module",
        eyebrow: "",
        headline: "",
        body: "",
        entries: []
    })
    readonly property var safeData: root.moduleData || ({
        key: "placeholder",
        kind: "placeholder",
        title: "Module",
        eyebrow: "",
        headline: "",
        body: "",
        entries: []
    })

    implicitHeight: {
        switch (safeData.kind) {
        case "notes":
            return 320
        case "system":
            return 248
        default:
            return 228
        }
    }

    FieldSurface {
        anchors.fill: parent
        radius: 30
        padding: 18
        tintColor: "#15212b"
        edgeColor: "#628da2"
        glowColor: "#80c6dd"
        fillOpacity: 0.68
        edgeOpacity: 0.26
        lineOpacity: 0.07

        ColumnLayout {
            anchors.fill: parent
            spacing: 12

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
                font.pixelSize: 22
            }

            Text {
                text: root.safeData.headline
                color: "#d2e3eb"
                wrapMode: Text.Wrap
                font.family: "Segoe UI Semibold"
                font.pixelSize: 14
            }

            Text {
                text: root.safeData.body
                color: "#94afbc"
                wrapMode: Text.Wrap
                font.family: "Segoe UI"
                font.pixelSize: 12
                lineHeight: 1.24
                Layout.fillWidth: true
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 10
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
