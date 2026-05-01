import QtQuick 2.15

import "../classic"

ClassicCommandDeckShell {
    id: root

    property bool stormforgeFoundationReady: true
    property string stormforgeFoundationVersion: sf.foundationVersion

    StormforgeTokens {
        id: sf
        objectName: "stormforgeDeckTokens"
    }

    StormforgeGlassPanel {
        objectName: "stormforgeDeckFoundationPanel"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: sf.space6
        anchors.rightMargin: sf.space6
        anchors.topMargin: sf.space3
        height: 2
        stateTone: "planned"
        elevation: sf.elevationFlat
        fillOpacity: 0.0
        opacity: 0.18
        z: -1
    }
}
