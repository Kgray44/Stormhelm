import QtQuick 2.15

import "../classic"

ClassicGhostShell {
    id: root

    property bool stormforgeFoundationReady: true
    property string stormforgeFoundationVersion: sf.foundationVersion

    StormforgeTokens {
        id: sf
        objectName: "stormforgeGhostTokens"
    }

    StormforgeGlassPanel {
        objectName: "stormforgeGhostFoundationPanel"
        width: Math.min(parent.width * 0.46, 520)
        height: 2
        anchors.horizontalCenter: parent.horizontalCenter
        y: Math.max(0, root.coreBottom + sf.space2)
        stateTone: "listening"
        elevation: sf.elevationFlat
        fillOpacity: 0.0
        opacity: 0.16
        z: -1
    }
}
