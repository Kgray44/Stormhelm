import QtQuick 2.15

Item {
    id: root

    property string stateTone: "idle"
    property real contentOffsetX: 0
    property real contentOffsetY: 0

    readonly property string componentRole: "stormforge_ghost_stage"
    readonly property bool ownsAnchorRendering: false
    readonly property bool ownsFogRendering: false
    readonly property int layerBackdrop: 0
    readonly property int layerAtmosphere: 2
    readonly property int layerInstrumentation: 4
    readonly property int layerAnchor: 8
    readonly property int layerTranscript: 12
    readonly property int layerCards: 14
    readonly property int layerApproval: 16
    readonly property int layerActions: 18
    readonly property int layerForegroundAtmosphere: 22

    transform: Translate {
        x: root.contentOffsetX
        y: root.contentOffsetY

        Behavior on x {
            NumberAnimation { duration: sf.durationSlow; easing.type: Easing.InOutCubic }
        }
        Behavior on y {
            NumberAnimation { duration: sf.durationSlow; easing.type: Easing.InOutCubic }
        }
    }

    StormforgeTokens {
        id: sf
    }

    Item {
        id: instrumentationLayer
        objectName: "stormforgeGhostInstrumentationLayer"
        anchors.fill: parent
        z: root.layerInstrumentation
        enabled: false
    }
}
