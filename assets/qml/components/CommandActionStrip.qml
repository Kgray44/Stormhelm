import QtQuick 2.15

Item {
    id: root

    signal actionTriggered(var action)

    property var actions: []
    property bool compact: false

    implicitHeight: flow.implicitHeight

    function fillColor(category) {
        switch (String(category || "")) {
        case "approve":
            return "#143445"
        case "deny":
            return "#352126"
        case "inspect":
            return "#142631"
        case "clarify":
            return "#173041"
        case "retry":
            return "#193227"
        case "reveal":
            return "#142631"
        default:
            return "#13242f"
        }
    }

    function borderColor(category) {
        switch (String(category || "")) {
        case "approve":
            return "#72b9d1"
        case "deny":
            return "#c88b92"
        case "inspect":
            return "#5e8ea3"
        case "clarify":
            return "#7ebed7"
        case "retry":
            return "#78c6a6"
        case "reveal":
            return "#6ea4ba"
        default:
            return "#567988"
        }
    }

    Flow {
        id: flow
        width: parent.width
        spacing: root.compact ? 8 : 10

        Repeater {
            model: root.actions || []

            delegate: Rectangle {
                required property var modelData
                readonly property bool actionEnabled: modelData.enabled === undefined || modelData.enabled === true

                radius: root.compact ? 16 : 18
                height: root.compact ? 30 : 34
                width: Math.min(label.implicitWidth + (root.compact ? 22 : 26), Math.max(root.compact ? 104 : 128, flow.width))
                clip: true
                color: root.fillColor(modelData.category)
                border.width: 1
                border.color: root.borderColor(modelData.category)
                opacity: actionEnabled ? 0.94 : 0.42

                Text {
                    id: label
                    anchors.centerIn: parent
                    width: parent.width - (root.compact ? 18 : 22)
                    text: modelData.label
                    color: parent.actionEnabled ? "#edf7fb" : "#98a9b1"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: root.compact ? 11 : 12
                    font.letterSpacing: 1.0
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: parent.actionEnabled
                    cursorShape: parent.actionEnabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: {
                        if (parent.actionEnabled)
                            root.actionTriggered(modelData)
                    }
                }
            }
        }
    }
}
