import QtQuick 2.15

Item {
    id: root
    objectName: "deckPanelWorkspace"

    signal panelGridCommitted(string panelId, int gridX, int gridY, int colSpan, int rowSpan)
    signal panelPinnedChanged(string panelId, bool pinned)
    signal panelCollapsedChanged(string panelId, bool collapsed)
    signal panelHiddenChanged(string panelId, bool hidden)

    property var panels: []
    property var messages: []
    property string statusLine: ""
    property real deckProgress: 1.0
    property int gridColumns: 12
    property int gridRows: 8
    property int reservedGridX: 4
    property int reservedGridY: 0
    property int reservedColSpan: 4
    property int reservedRowSpan: 3
    property real gutter: 14
    readonly property real cellWidth: Math.max(72, (width - (gridColumns - 1) * gutter) / gridColumns)
    readonly property real rowHeight: Math.max(70, (height - (gridRows - 1) * gutter) / gridRows)
    readonly property rect regionRect: Qt.rect(x, y, width, height)
    readonly property rect reservedRect: Qt.rect(
        reservedGridX * (cellWidth + gutter),
        reservedGridY * (rowHeight + gutter),
        reservedColSpan * cellWidth + Math.max(0, reservedColSpan - 1) * gutter,
        reservedRowSpan * rowHeight + Math.max(0, reservedRowSpan - 1) * gutter
    )

    clip: true

    Repeater {
        model: root.panels

        delegate: DeckPanel {
            required property var modelData
            required property int index
            readonly property var panelModel: modelData

            panelData: panelModel
            cellWidth: root.cellWidth
            rowHeight: root.rowHeight
            gutter: root.gutter
            gridColumns: root.gridColumns
            gridRows: root.gridRows
            layoutWidth: root.width
            layoutHeight: root.height
            reservedRect: root.reservedRect
            revealProgress: Math.max(0, Math.min(1, root.deckProgress * 1.16 - index * 0.08))

            onGridCommitted: function(panelId, gridX, gridY, colSpan, rowSpan) {
                root.panelGridCommitted(panelId, gridX, gridY, colSpan, rowSpan)
            }
            onPinnedChangedRequested: function(panelId, pinned) {
                root.panelPinnedChanged(panelId, pinned)
            }
            onCollapsedChangedRequested: function(panelId, collapsed) {
                root.panelCollapsedChanged(panelId, collapsed)
            }
            onHiddenChangedRequested: function(panelId, hidden) {
                root.panelHiddenChanged(panelId, hidden)
            }

            Loader {
                anchors.fill: parent
                sourceComponent: {
                    switch (panelModel.contentKind) {
                    case "spine":
                        return spineComponent
                    case "module":
                        return moduleComponent
                    case "preview":
                        return previewComponent
                    default:
                        return workspaceComponent
                    }
                }
            }

            Component {
                id: spineComponent

                CommandSpine {
                    anchors.fill: parent
                    messages: root.messages
                    statusLine: root.statusLine
                    panelMode: true
                    onSend: function(text) { stormhelmBridge.sendMessage(text) }
                    onComposerFocusChanged: function(focused) { stormhelmBridge.setComposerFocus(focused) }
                }
            }

            Component {
                id: workspaceComponent

                WorkspaceCanvas {
                    anchors.fill: parent
                    canvasData: panelModel.canvasData || ({})
                    panelMode: true
                    onActivateOpenedItem: function(itemId) { stormhelmBridge.activateOpenedItem(itemId) }
                    onCloseOpenedItem: function(itemId) { stormhelmBridge.closeOpenedItem(itemId) }
                }
            }

            Component {
                id: moduleComponent

                ModulePanel {
                    anchors.fill: parent
                    moduleData: panelModel.moduleData || ({})
                    panelMode: true
                    onSaveNote: function(title, content) { stormhelmBridge.saveNote(title, content) }
                }
            }

            Component {
                id: previewComponent

                Loader {
                    anchors.fill: parent
                    sourceComponent: {
                        var item = panelModel.itemData || ({})
                        return item.viewer === "browser" ? browserPreview : filePreview
                    }
                }
            }

            Component {
                id: browserPreview

                BrowserSurface {
                    anchors.fill: parent
                    itemData: panelModel.itemData || ({})
                }
            }

            Component {
                id: filePreview

                FileViewerSurface {
                    anchors.fill: parent
                    itemData: panelModel.itemData || ({})
                }
            }
        }
    }
}
