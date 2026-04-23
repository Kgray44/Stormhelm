import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    property var itemData: ({})
    readonly property url pageUrl: itemData && itemData.url ? itemData.url : "about:blank"
    readonly property bool embeddedPreviewEnabled: typeof stormhelmBridge !== "undefined"
                                              ? Boolean(stormhelmBridge.embeddedBrowserPreviewEnabled)
                                              : true

    Loader {
        id: embeddedBrowserLoader
        anchors.fill: parent
        active: root.embeddedPreviewEnabled
        source: root.embeddedPreviewEnabled ? "BrowserSurfaceEmbedded.qml" : ""

        onLoaded: {
            if (item) {
                item.itemData = Qt.binding(function() { return root.itemData })
            }
        }
    }

    Component {
        id: lightweightBrowserComponent

        Rectangle {
            color: "transparent"

            ColumnLayout {
                anchors.fill: parent
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        Layout.fillWidth: true
                        text: root.itemData && root.itemData.url ? root.itemData.url : "about:blank"
                        color: "#d7e7ef"
                        font.family: "Bahnschrift SemiCondensed"
                        font.pixelSize: 11
                        font.letterSpacing: 1.1
                        elide: Text.ElideRight
                    }

                    Text {
                        text: "Research Surface"
                        color: "#89a5b2"
                        font.family: "Segoe UI"
                        font.pixelSize: 11
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 24
                    color: "#0f1820cc"
                    border.width: 1
                    border.color: "#355565"

                    Column {
                        anchors.centerIn: parent
                        spacing: 8

                        Text {
                            text: "Browser Preview Deferred"
                            color: "#eef8fb"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 22
                            horizontalAlignment: Text.AlignHCenter
                        }

                        Text {
                            width: 320
                            text: "Stormhelm keeps the opened page in view, but shells without live embedded-browser support use a lightweight placeholder instead of spinning up the web engine."
                            color: "#a3bcc8"
                            wrapMode: Text.Wrap
                            horizontalAlignment: Text.AlignHCenter
                            font.family: "Segoe UI"
                            font.pixelSize: 12
                        }
                    }
                }
            }
        }
    }

    onItemDataChanged: {
        if (embeddedBrowserLoader.item) {
            embeddedBrowserLoader.item.itemData = Qt.binding(function() { return root.itemData })
        }
    }
}
