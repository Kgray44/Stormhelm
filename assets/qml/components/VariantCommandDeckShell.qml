import QtQuick 2.15

Item {
    id: root

    signal activateDestination(string key)
    signal activateWorkspaceItem(string key)
    signal activateOpenedItem(string itemId)
    signal closeOpenedItem(string itemId)
    signal updateDeckPanelGrid(string panelId, int gridX, int gridY, int colSpan, int rowSpan)
    signal pinDeckPanel(string panelId, bool pinned)
    signal collapseDeckPanel(string panelId, bool collapsed)
    signal hideDeckPanel(string panelId, bool hidden)
    signal restoreDeckPanel(string panelId)
    signal saveDeckLayout()
    signal resetDeckLayout()
    signal autoArrangeDeckLayout()
    signal restoreSavedDeckLayout()
    signal setDeckLayoutPreset(string preset)

    property string visualVariant: "classic"
    property real coreBottom: 0
    property real deckProgress: 1
    property var messages: []
    property var activeModule: ({})
    property var supportModules: []
    property var workspaceItems: []
    property var workspaceCanvas: ({})
    property var requestComposer: ({})
    property var railItems: []
    property var statusItems: []
    property var voiceState: ({})
    property var deckPanels: []
    property var hiddenPanels: []
    property var panelCatalog: []
    property var deckLayoutPresets: []
    property string activeDeckLayoutPreset: ""
    property string statusLine: ""
    property string modeTitle: ""
    property string modeSubtitle: ""
    property string assistantState: "idle"
    readonly property string effectiveVariant: String(root.visualVariant || "classic").toLowerCase() === "stormforge" ? "stormforge" : "classic"
    readonly property rect collaborationRect: shellLoader.item ? shellLoader.item.collaborationRect : Qt.rect(0, 0, 0, 0)
    readonly property rect contextRect: shellLoader.item ? shellLoader.item.contextRect : Qt.rect(0, 0, 0, 0)
    readonly property rect railRect: shellLoader.item ? shellLoader.item.railRect : Qt.rect(0, 0, 0, 0)

    Loader {
        id: shellLoader
        anchors.fill: parent
        source: root.effectiveVariant === "stormforge"
            ? Qt.resolvedUrl("../variants/stormforge/StormforgeCommandDeckShell.qml")
            : Qt.resolvedUrl("../variants/classic/ClassicCommandDeckShell.qml")
        onLoaded: {
            if (item) {
                item.objectName = root.effectiveVariant + "DeckShell"
            }
        }
    }

    Binding { target: shellLoader.item; property: "coreBottom"; value: root.coreBottom; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "deckProgress"; value: root.deckProgress; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "messages"; value: root.messages; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "activeModule"; value: root.activeModule; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "supportModules"; value: root.supportModules; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "workspaceItems"; value: root.workspaceItems; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "workspaceCanvas"; value: root.workspaceCanvas; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "requestComposer"; value: root.requestComposer; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "railItems"; value: root.railItems; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "statusItems"; value: root.statusItems; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "voiceState"; value: root.voiceState; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "deckPanels"; value: root.deckPanels; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "hiddenPanels"; value: root.hiddenPanels; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "panelCatalog"; value: root.panelCatalog; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "deckLayoutPresets"; value: root.deckLayoutPresets; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "activeDeckLayoutPreset"; value: root.activeDeckLayoutPreset; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "statusLine"; value: root.statusLine; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "modeTitle"; value: root.modeTitle; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "modeSubtitle"; value: root.modeSubtitle; when: shellLoader.item !== null }
    Binding { target: shellLoader.item; property: "assistantState"; value: root.assistantState; when: shellLoader.item !== null }

    Connections {
        target: shellLoader.item
        ignoreUnknownSignals: true

        function onActivateDestination(key) { root.activateDestination(key) }
        function onActivateWorkspaceItem(key) { root.activateWorkspaceItem(key) }
        function onActivateOpenedItem(itemId) { root.activateOpenedItem(itemId) }
        function onCloseOpenedItem(itemId) { root.closeOpenedItem(itemId) }
        function onUpdateDeckPanelGrid(panelId, gridX, gridY, colSpan, rowSpan) {
            root.updateDeckPanelGrid(panelId, gridX, gridY, colSpan, rowSpan)
        }
        function onPinDeckPanel(panelId, pinned) { root.pinDeckPanel(panelId, pinned) }
        function onCollapseDeckPanel(panelId, collapsed) { root.collapseDeckPanel(panelId, collapsed) }
        function onHideDeckPanel(panelId, hidden) { root.hideDeckPanel(panelId, hidden) }
        function onRestoreDeckPanel(panelId) { root.restoreDeckPanel(panelId) }
        function onSaveDeckLayout() { root.saveDeckLayout() }
        function onResetDeckLayout() { root.resetDeckLayout() }
        function onAutoArrangeDeckLayout() { root.autoArrangeDeckLayout() }
        function onRestoreSavedDeckLayout() { root.restoreSavedDeckLayout() }
        function onSetDeckLayoutPreset(preset) { root.setDeckLayoutPreset(preset) }
    }
}
