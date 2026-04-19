import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    signal activateDestination(string key)
    signal activateWorkspaceItem(string key)
    signal activateOpenedItem(string itemId)
    signal closeOpenedItem(string itemId)

    property real coreBottom: 0
    property real deckProgress: 1
    property var messages: []
    property var activeModule: ({})
    property var supportModules: []
    property var workspaceItems: []
    property var workspaceCanvas: ({})
    property var railItems: []
    property var statusItems: []
    property string statusLine: ""
    property string modeTitle: ""
    property string modeSubtitle: ""
    property string assistantState: "idle"
    readonly property real sideInset: 38
    readonly property real workspaceRailWidth: 156
    readonly property real contextWidth: Math.min(parent.width * 0.23, 352)
    readonly property real bottomRailHeight: 74
    readonly property real deckTop: root.coreBottom + 34
    readonly property real rightRegionX: parent.width - root.contextWidth - root.sideInset
    readonly property real mainFieldX: root.sideInset + root.workspaceRailWidth + 26
    readonly property real mainFieldWidth: Math.max(620, root.rightRegionX - root.mainFieldX - 22)
    readonly property real collaborationWidth: Math.max(420, root.mainFieldWidth * 0.66)
    readonly property real spineWidth: Math.min(334, Math.max(278, root.mainFieldWidth * 0.29))
    readonly property rect collaborationRect: Qt.rect(collaborationField.x, collaborationField.y, collaborationField.width, collaborationField.height)
    readonly property rect contextRect: Qt.rect(contextRegion.x, contextRegion.y, contextRegion.width, contextRegion.height)
    readonly property rect railRect: Qt.rect(commandRail.x, commandRail.y, commandRail.width, commandRail.height)

    TopStatusStrip {
        width: Math.min(parent.width - 96, 1020)
        anchors.horizontalCenter: parent.horizontalCenter
        y: 18 - (1 - root.deckProgress) * 12
        items: root.statusItems
        stateName: root.assistantState
        opacity: 0.34 + root.deckProgress * 0.66
    }

    WorkspaceRail {
        id: workspaceRail
        x: (parent.width / 2 - width * 0.5) * (1 - root.deckProgress) + root.sideInset * root.deckProgress
        y: root.deckTop + 16
        width: root.workspaceRailWidth
        height: commandRail.y - y - 22
        items: root.workspaceItems
        revealProgress: root.deckProgress
        opacity: root.deckProgress
        onActivateItem: function(key) { root.activateWorkspaceItem(key) }
    }

    FieldSurface {
        id: collaborationField
        x: root.mainFieldX
        y: root.deckTop
        width: root.mainFieldWidth
        height: commandRail.y - y - 16
        radius: 36
        padding: 28
        tintColor: "#101a23"
        edgeColor: "#648fa4"
        glowColor: "#87cee4"
        fillOpacity: 0.78
        edgeOpacity: 0.2
        lineOpacity: 0.06
        opacity: 0.32 + root.deckProgress * 0.68

        RowLayout {
            anchors.fill: parent
            spacing: 22

            WorkspaceCanvas {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: root.collaborationWidth
                canvasData: root.workspaceCanvas
                onActivateOpenedItem: function(itemId) { root.activateOpenedItem(itemId) }
                onCloseOpenedItem: function(itemId) { root.closeOpenedItem(itemId) }
            }

            Rectangle {
                Layout.preferredWidth: 1
                Layout.fillHeight: true
                color: "#37586a"
                opacity: 0.26
            }

            CommandSpine {
                Layout.preferredWidth: root.spineWidth
                Layout.fillHeight: true
                messages: root.messages
                statusLine: root.statusLine
                onSend: function(text) { stormhelmBridge.sendMessage(text) }
                onComposerFocusChanged: function(focused) { stormhelmBridge.setComposerFocus(focused) }
            }
        }
    }

    Item {
        id: contextRegion
        x: root.rightRegionX
        y: root.deckTop + 22
        width: root.contextWidth
        height: commandRail.y - y - 16
        opacity: 0.18 + root.deckProgress * 0.82

        ColumnLayout {
            anchors.fill: parent
            spacing: 12

            Repeater {
                model: root.supportModules.slice(0, 2)

                delegate: Item {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: supportColumn.implicitHeight + 10

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: "#345767"
                        opacity: 0.22
                    }

                    Column {
                        id: supportColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        spacing: 3

                        Text {
                            text: modelData.title
                            color: "#d6e8f0"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 13
                            font.letterSpacing: 1.3
                            elide: Text.ElideRight
                        }

                        Text {
                            text: modelData.headline
                            color: "#7e9aa7"
                            font.family: "Segoe UI"
                            font.pixelSize: 10
                            wrapMode: Text.Wrap
                            width: parent.width
                        }
                    }
                }
            }

            ModulePanel {
                Layout.fillWidth: true
                Layout.fillHeight: true
                moduleData: root.activeModule
                onSaveNote: function(title, content) { stormhelmBridge.saveNote(title, content) }
            }
        }
    }

    CommandRail {
        id: commandRail
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 20
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(parent.width - 64, 1040)
        height: root.bottomRailHeight
        items: root.railItems
        opacity: 0.28 + root.deckProgress * 0.72
        onActivateItem: function(key) { root.activateDestination(key) }
    }
}
