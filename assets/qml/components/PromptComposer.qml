import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    signal send(string text)
    signal composerFocusChanged(bool focused)
    signal actionRequested(var action)

    property bool compact: false
    property var composerState: ({})
    property string placeholderText: "Give Stormhelm a bearing..."

    implicitHeight: {
        var baseHeight = compact ? 96 : 132
        if ((root.safeComposer.chips || []).length > 0)
            baseHeight += compact ? 28 : 34
        if ((root.safeComposer.quickActions || []).length > 0)
            baseHeight += compact ? 32 : 38
        if ((root.safeComposer.clarificationChoices || []).length > 0)
            baseHeight += compact ? 38 : 44
        return baseHeight
    }

    readonly property var safeComposer: root.composerState || ({})

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

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: compact ? 14 : 18
        spacing: compact ? 10 : 12

        Flow {
            Layout.fillWidth: true
            spacing: 8
            visible: (root.safeComposer.chips || []).length > 0

            Repeater {
                model: root.safeComposer.chips || []

                delegate: Rectangle {
                    required property var modelData

                    radius: 12
                    height: 26
                    width: chipRow.implicitWidth + 16
                    color: root.chipFill(modelData.tone)
                    border.width: 1
                    border.color: root.chipBorder(modelData.tone)

                    Row {
                        id: chipRow
                        anchors.centerIn: parent
                        spacing: 6

                        Text {
                            text: modelData.label
                            color: "#7e9baa"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 10
                            font.letterSpacing: 1.0
                        }

                        Text {
                            text: modelData.value
                            color: "#e8f4f9"
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: 10
                        }
                    }
                }
            }
        }

        CommandActionStrip {
            Layout.fillWidth: true
            actions: root.safeComposer.quickActions || []
            compact: true
            visible: (root.safeComposer.quickActions || []).length > 0
            onActionTriggered: function(action) {
                if (action.sendText) {
                    root.send(action.sendText)
                } else {
                    root.actionRequested(action)
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            visible: (root.safeComposer.clarificationChoices || []).length > 0

            Text {
                text: "Clarify"
                color: "#b98a56"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: 10
                font.letterSpacing: 1.2
            }

            CommandActionStrip {
                Layout.fillWidth: true
                actions: root.safeComposer.clarificationChoices || []
                compact: true
                onActionTriggered: function(action) {
                    if (action.sendText) {
                        root.send(action.sendText)
                    } else {
                        root.actionRequested(action)
                    }
                }
            }
        }

        TextArea {
            id: input
            Layout.fillWidth: true
            Layout.fillHeight: true
            wrapMode: TextEdit.Wrap
            placeholderText: root.safeComposer.placeholder || root.placeholderText
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

        RowLayout {
            Layout.fillWidth: true
            spacing: 14

            Text {
                Layout.fillWidth: true
                text: root.safeComposer.summary || ""
                color: "#89a5b2"
                font.family: "Segoe UI"
                font.pixelSize: 11
                wrapMode: Text.Wrap
                visible: text.length > 0
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
}
