import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtWebEngine 1.15

Item {
    id: root

    property var itemData: ({})
    readonly property url pageUrl: root.itemData && root.itemData.url ? root.itemData.url : "about:blank"

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
            clip: true

            WebEngineView {
                anchors.fill: parent
                anchors.margins: 1
                url: root.pageUrl
                profile: WebEngineProfile {
                    offTheRecord: true
                }
                settings.pluginsEnabled: false
                settings.autoLoadImages: true
                settings.javascriptCanAccessClipboard: false
                settings.localContentCanAccessRemoteUrls: false
                settings.localContentCanAccessFileUrls: false
                settings.screenCaptureEnabled: false
                backgroundColor: "#101920"
            }
        }
    }
}
