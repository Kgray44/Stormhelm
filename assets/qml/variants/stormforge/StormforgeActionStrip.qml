import QtQuick 2.15

Item {
    id: root

    signal actionTriggered(var action)

    property var actions: []
    property bool compact: false
    readonly property int actionCount: actions ? actions.length : 0

    implicitWidth: actionRow.implicitWidth
    implicitHeight: actionRow.implicitHeight

    StormforgeTokens {
        id: sf
    }

    Row {
        id: actionRow
        spacing: compact ? sf.space2 : sf.space3

        Repeater {
            model: root.actions || []

            delegate: StormforgeButton {
                required property var modelData

                text: String(modelData.label || "")
                stateTone: String(modelData.state || modelData.resultState || "planned")
                enabledState: modelData.enabled === undefined ? true : !!modelData.enabled
                onClicked: root.actionTriggered(modelData)
            }
        }
    }
}
