import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    signal activateOpenedItem(string itemId)
    signal closeOpenedItem(string itemId)

    property var canvasData: ({
        eyebrow: "",
        title: "",
        summary: "",
        body: "",
        chips: [],
        columns: [],
        openedItems: [],
        activeItem: ({})
    })
    readonly property var safeData: root.canvasData || ({
        eyebrow: "",
        title: "",
        summary: "",
        body: "",
        chips: [],
        columns: [],
        openedItems: [],
        activeItem: ({})
    })
    readonly property var activeItem: root.safeData.activeItem || ({})
    readonly property bool showWorkspaceItem: {
        var section = root.safeData.sectionKey || ""
        return (root.safeData.openedItems || []).length > 0
                && ["opened-items", "open-pages", "references", "working-set"].indexOf(section) >= 0
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 18

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                text: root.safeData.eyebrow
                color: "#b58a62"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: 11
                font.letterSpacing: 1.8
                visible: text.length > 0
            }

            Text {
                text: root.safeData.title
                color: "#edf7fb"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: 29
                font.letterSpacing: 1.1
            }

            Text {
                text: root.safeData.summary
                color: "#c7dbe5"
                font.family: "Segoe UI Semibold"
                font.pixelSize: 15
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            Text {
                text: root.safeData.body
                color: "#8ea8b4"
                font.family: "Segoe UI"
                font.pixelSize: 13
                wrapMode: Text.Wrap
                lineHeight: 1.24
                Layout.fillWidth: true
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 8
            visible: root.safeData.chips.length > 0

            Repeater {
                model: root.safeData.chips

                delegate: Rectangle {
                    required property var modelData
                    radius: 13
                    color: "#0f1c25"
                    border.width: 1
                    border.color: "#2f526171"
                    height: 28
                    width: chipRow.implicitWidth + 20
                    opacity: 0.9

                    Row {
                        id: chipRow
                        anchors.centerIn: parent
                        spacing: 7

                        Text {
                            text: modelData.label
                            color: "#7f9cab"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 10
                            font.letterSpacing: 1.2
                        }

                        Text {
                            text: modelData.value
                            color: "#e2f1f8"
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        Loader {
            Layout.fillWidth: true
            Layout.fillHeight: true
            sourceComponent: root.showWorkspaceItem ? workspaceItemComponent : overviewComponent
        }
    }

    Component {
        id: workspaceItemComponent

        ColumnLayout {
            spacing: 12

            OpenedItemsStrip {
                Layout.fillWidth: true
                items: root.safeData.openedItems
                activeItemId: root.activeItem.itemId || ""
                onActivateItem: function(itemId) { root.activateOpenedItem(itemId) }
                onCloseItem: function(itemId) { root.closeOpenedItem(itemId) }
            }

            Loader {
                Layout.fillWidth: true
                Layout.fillHeight: true
                sourceComponent: root.activeItem.viewer === "browser" ? browserComponent : fileComponent
            }
        }
    }

    Component {
        id: browserComponent

        BrowserSurface {
            itemData: root.activeItem
        }
    }

    Component {
        id: fileComponent

        FileViewerSurface {
            itemData: root.activeItem
        }
    }

    Component {
        id: overviewComponent

        RowLayout {
            spacing: 20

            Repeater {
                model: root.safeData.columns

                delegate: Item {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 1

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 12

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3

                            Text {
                                text: modelData.title
                                color: "#d9e9f1"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 16
                                font.letterSpacing: 1.1
                            }

                            Text {
                                text: modelData.summary
                                color: "#7f99a6"
                                font.family: "Segoe UI"
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            height: 1
                            color: "#315062"
                            opacity: 0.34
                        }

                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 10
                            model: modelData.entries

                            delegate: Item {
                                required property var modelData
                                width: ListView.view.width
                                height: entryColumn.implicitHeight + 10

                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    height: 1
                                    color: "#284556"
                                    opacity: 0.22
                                }

                                Column {
                                    id: entryColumn
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    spacing: 4

                                    Text {
                                        text: modelData.primary
                                        width: parent.width
                                        color: "#eef7fb"
                                        font.family: "Segoe UI Semibold"
                                        font.pixelSize: 13
                                        wrapMode: Text.Wrap
                                    }

                                    Text {
                                        text: modelData.secondary
                                        width: parent.width
                                        color: "#88a4b1"
                                        font.family: "Bahnschrift SemiCondensed"
                                        font.pixelSize: 10
                                        font.letterSpacing: 1.2
                                        wrapMode: Text.Wrap
                                    }

                                    Text {
                                        text: modelData.detail
                                        visible: text.length > 0
                                        width: parent.width
                                        color: "#b7cbd5"
                                        font.family: "Segoe UI"
                                        font.pixelSize: 12
                                        wrapMode: Text.Wrap
                                        lineHeight: 1.22
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
