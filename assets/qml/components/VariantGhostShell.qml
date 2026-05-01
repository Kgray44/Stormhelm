import QtQuick 2.15

Item {
    id: root

    signal actionRequested(var action)

    property string visualVariant: "classic"
    property real coreBottom: 0
    property real deckProgress: 0
    property var messages: []
    property var contextCards: []
    property var primaryCard: ({})
    property var actionStrip: []
    property var cornerReadouts: []
    property var voiceState: ({})
    property string statusLine: ""
    property string connectionLabel: ""
    property string timeLabel: ""
    property real contentOffsetX: 0
    property real contentOffsetY: 0
    property real adaptiveTone: 0
    property real adaptiveTextContrast: 0.08
    property real adaptiveSecondaryTextContrast: 0.05
    property real adaptiveShadowOpacity: 0.1
    property real adaptiveBackdropOpacity: 0.04
    property var stormforgeFogConfig: ({})
    readonly property string effectiveVariant: String(root.visualVariant || "classic").toLowerCase() === "stormforge" ? "stormforge" : "classic"

    enabled: false

    Loader {
        id: shellLoader
        anchors.fill: parent
        source: root.effectiveVariant === "stormforge"
            ? Qt.resolvedUrl("../variants/stormforge/StormforgeGhostShell.qml")
            : Qt.resolvedUrl("../variants/classic/ClassicGhostShell.qml")
        onLoaded: {
            if (item) {
                item.objectName = root.effectiveVariant + "GhostShell"
            }
        }
    }

    Binding { target: shellLoader.item; property: "coreBottom"; value: root.coreBottom; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "deckProgress"; value: root.deckProgress; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "messages"; value: root.messages; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "contextCards"; value: root.contextCards; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "primaryCard"; value: root.primaryCard; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "actionStrip"; value: root.actionStrip; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "cornerReadouts"; value: root.cornerReadouts; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "voiceState"; value: root.voiceState; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "statusLine"; value: root.statusLine; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "connectionLabel"; value: root.connectionLabel; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "timeLabel"; value: root.timeLabel; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "contentOffsetX"; value: root.contentOffsetX; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "contentOffsetY"; value: root.contentOffsetY; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "adaptiveTone"; value: root.adaptiveTone; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "adaptiveTextContrast"; value: root.adaptiveTextContrast; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "adaptiveSecondaryTextContrast"; value: root.adaptiveSecondaryTextContrast; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "adaptiveShadowOpacity"; value: root.adaptiveShadowOpacity; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "adaptiveBackdropOpacity"; value: root.adaptiveBackdropOpacity; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "stormforgeFogConfig"; value: root.stormforgeFogConfig; when: shellLoader.item !== null && root.effectiveVariant === "stormforge" }

    Connections {
        target: shellLoader.item
        ignoreUnknownSignals: true

        function onActionRequested(action) {
            root.actionRequested(action)
        }
    }
}
