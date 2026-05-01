import QtQuick 2.15

Item {
    id: root

    signal actionTriggered(var action)

    property var actions: []
    readonly property int actionCount: actionStrip.actionCount

    implicitWidth: actionStrip.implicitWidth
    implicitHeight: actionStrip.implicitHeight
    width: actionStrip.width
    height: actionStrip.height
    visible: actionCount > 0

    StormforgeActionStrip {
        id: actionStrip
        objectName: "stormforgeGhostActionStrip"
        anchors.horizontalCenter: parent.horizontalCenter
        compact: true
        actions: root.actions || []
        onActionTriggered: function(action) {
            root.actionTriggered(action)
        }
    }
}
