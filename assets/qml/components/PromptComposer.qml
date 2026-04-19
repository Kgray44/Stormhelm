import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    signal send(string text)
    signal composerFocusChanged(bool focused)

    property bool compact: false
    property string placeholderText: "Give Stormhelm a bearing..."

    implicitHeight: compact ? 88 : 128

    function submitCurrentText() {
        var text = input.text.trim()
        if (text.length === 0) {
            return
        }
        root.send(input.text)
        input.clear()
    }

    FieldSurface {
        anchors.fill: parent
        radius: compact ? 26 : 30
        padding: compact ? 14 : 18
        tintColor: "#14212b"
        edgeColor: "#628da0"
        glowColor: "#7ec6dc"
        fillOpacity: compact ? 0.66 : 0.72
        edgeOpacity: compact ? 0.28 : 0.32
        lineOpacity: 0.06
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: compact ? 14 : 18
        spacing: 14

        TextArea {
            id: input
            Layout.fillWidth: true
            Layout.fillHeight: true
            wrapMode: TextEdit.Wrap
            placeholderText: root.placeholderText
            color: "#eff7fb"
            placeholderTextColor: "#7d98ab"
            font.family: "Segoe UI"
            font.pixelSize: compact ? 14 : 15
            background: Item {}

            onActiveFocusChanged: root.composerFocusChanged(activeFocus)

            Keys.onPressed: function(event) {
                if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                        && !(event.modifiers & Qt.ShiftModifier)
                        && !(event.modifiers & Qt.ControlModifier)
                        && !(event.modifiers & Qt.AltModifier)
                        && !(event.modifiers & Qt.MetaModifier)) {
                    root.submitCurrentText()
                    event.accepted = true
                }
            }
        }

        Button {
            text: compact ? "Send" : "Plot"
            Layout.alignment: Qt.AlignBottom
            background: Rectangle {
                radius: 18
                color: "#17364a6a"
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
                root.submitCurrentText()
            }
        }
    }
}
