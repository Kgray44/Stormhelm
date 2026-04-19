import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Pdf 6.5

Item {
    id: root

    property var itemData: ({})
    readonly property string viewerKind: itemData && itemData.viewer ? itemData.viewer : "fallback"
    readonly property url fileUrl: itemData && itemData.url ? itemData.url : ""

    PdfDocument {
        id: pdfDocument
        source: root.viewerKind === "pdf" ? root.fileUrl : ""
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Text {
                Layout.fillWidth: true
                text: root.itemData && root.itemData.path ? root.itemData.path : (root.itemData && root.itemData.url ? root.itemData.url : "No file selected")
                color: "#d7e7ef"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: 11
                font.letterSpacing: 1.1
                elide: Text.ElideRight
            }

            Text {
                text: root.viewerKind === "pdf" ? "PDF Viewer" : (root.viewerKind === "image" ? "Image Viewer" : "File Viewer")
                color: "#89a5b2"
                font.family: "Segoe UI"
                font.pixelSize: 11
            }
        }

        Loader {
            Layout.fillWidth: true
            Layout.fillHeight: true
            sourceComponent: {
                if (root.viewerKind === "image") {
                    return imageComponent
                }
                if (root.viewerKind === "pdf") {
                    return pdfComponent
                }
                if (root.viewerKind === "text" || root.viewerKind === "markdown") {
                    return textComponent
                }
                return fallbackComponent
            }
        }
    }

    Component {
        id: textComponent

        Rectangle {
            radius: 24
            color: "#0f1820cc"
            border.width: 1
            border.color: "#355565"

            ScrollView {
                anchors.fill: parent
                anchors.margins: 1
                clip: true

                TextArea {
                    readOnly: true
                    wrapMode: TextEdit.Wrap
                    text: root.itemData && root.itemData.content ? root.itemData.content : ""
                    color: "#edf7fb"
                    font.family: root.viewerKind === "markdown" ? "Segoe UI" : "Cascadia Mono"
                    font.pixelSize: 13
                    background: Item {}
                }
            }
        }
    }

    Component {
        id: imageComponent

        Rectangle {
            radius: 24
            color: "#0f1820cc"
            border.width: 1
            border.color: "#355565"

            Flickable {
                anchors.fill: parent
                clip: true
                contentWidth: imageItem.width
                contentHeight: imageItem.height

                Image {
                    id: imageItem
                    anchors.centerIn: parent
                    source: root.fileUrl
                    fillMode: Image.PreserveAspectFit
                    sourceSize.width: parent.width
                    sourceSize.height: parent.height
                    asynchronous: true
                }
            }
        }
    }

    Component {
        id: pdfComponent

        Rectangle {
            radius: 24
            color: "#0f1820cc"
            border.width: 1
            border.color: "#355565"
            clip: true

            PdfMultiPageView {
                anchors.fill: parent
                anchors.margins: 1
                document: pdfDocument
            }
        }
    }

    Component {
        id: fallbackComponent

        Rectangle {
            radius: 24
            color: "#0f1820cc"
            border.width: 1
            border.color: "#355565"

            Column {
                anchors.centerIn: parent
                spacing: 8

                Text {
                    text: "Unsupported File"
                    color: "#eef8fb"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: 22
                    horizontalAlignment: Text.AlignHCenter
                }

                Text {
                    width: 320
                    text: "Stormhelm can keep this item in the workspace, but this viewer type is not supported yet. Open it externally for full fidelity."
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
