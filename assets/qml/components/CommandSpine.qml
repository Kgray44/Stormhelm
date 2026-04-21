import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    signal send(string text)
    signal composerFocusChanged(bool focused)

    property var messages: []
    property string statusLine: ""
    property bool panelMode: false

    ColumnLayout {
        anchors.fill: parent
        spacing: root.panelMode ? 10 : 12

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3
            visible: !root.panelMode

            Text {
                text: "Command Spine"
                color: "#dbeaf2"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: 14
                font.letterSpacing: 1.5
            }

            Text {
                text: root.statusLine
                color: "#89a5b2"
                font.family: "Segoe UI"
                font.pixelSize: 11
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
        }

        Text {
            visible: root.panelMode
            text: root.statusLine
            color: "#89a5b2"
            font.family: "Segoe UI"
            font.pixelSize: 11
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }

        TranscriptTimeline {
            Layout.fillWidth: true
            Layout.fillHeight: true
            messages: root.messages
            compact: true
            framed: false
        }

        PromptComposer {
            Layout.fillWidth: true
            compact: true
            placeholderText: "Signal the helm, plot a command, or leave a note..."
            onSend: function(text) { root.send(text) }
            onComposerFocusChanged: function(focused) { root.composerFocusChanged(focused) }
        }
    }
}
