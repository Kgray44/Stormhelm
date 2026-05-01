import QtQuick 2.15
import QtQuick.Layouts 1.15

import "../../components"

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
    property bool panelLauncherExpanded: true
    readonly property real sideInset: 38
    readonly property real workspaceRailWidth: 156
    readonly property real bottomRailHeight: 74
    readonly property real deckTop: 60
    readonly property real mainFieldX: root.sideInset + root.workspaceRailWidth + 24
    readonly property real mainFieldWidth: parent.width - root.mainFieldX - root.sideInset
    readonly property bool panelUtilityVisible: root.panelCatalog.length > 0 || root.hiddenPanels.length > 0
    readonly property real panelUtilityReserve: root.panelUtilityVisible ? 186 : 18
    readonly property rect collaborationRect: Qt.rect(panelWorkspace.x + deckField.x, panelWorkspace.y + deckField.y, panelWorkspace.width, panelWorkspace.height)
    readonly property rect contextRect: Qt.rect(utilityColumn.x + deckField.x, utilityColumn.y + deckField.y, utilityColumn.width, utilityColumn.height)
    readonly property rect railRect: Qt.rect(commandRail.x, commandRail.y, commandRail.width, commandRail.height)
    readonly property var layoutTools: [
        { "key": "tidy", "label": "Tidy" },
        { "key": "save", "label": "Save" },
        { "key": "restore", "label": "Restore" },
        { "key": "reset", "label": "Reset" }
    ]

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
        y: root.deckTop + 8
        width: root.workspaceRailWidth
        height: Math.max(220, commandRail.y - y - root.panelUtilityReserve)
        items: root.workspaceItems
        revealProgress: root.deckProgress
        opacity: root.deckProgress > 0.02 ? 1 : 0
        onActivateItem: function(key) { root.activateWorkspaceItem(key) }
    }

    Item {
        id: deckField
        x: root.mainFieldX
        y: root.deckTop
        width: root.mainFieldWidth
        height: commandRail.y - y - 10
        opacity: root.deckProgress > 0.02 ? 1 : 0

        Row {
            id: controlDeck
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 12

            Row {
                id: layoutPresetRow
                objectName: "deckLayoutPresetRow"
                spacing: 8

                Repeater {
                    model: root.deckLayoutPresets

                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool active: String(modelData.key || "") === root.activeDeckLayoutPreset
                        radius: 16
                        height: 28
                        width: presetLabel.implicitWidth + 22
                        color: active ? "#173342" : "#0f1b23"
                        border.width: 1
                        border.color: active ? "#8ed5ea" : "#425f70"
                        opacity: active ? 0.96 : 0.84

                        Text {
                            id: presetLabel
                            anchors.centerIn: parent
                            text: modelData.label
                            color: active ? "#f2fbff" : "#d5e7ef"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 11
                            font.letterSpacing: 1.1
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.setDeckLayoutPreset(String(modelData.key || ""))
                        }
                    }
                }
            }

            Item {
                Layout.fillWidth: true
                width: Math.max(0, parent.width - layoutPresetRow.width - layoutToolRow.width - 12)
                height: 1
            }

            Row {
                id: layoutToolRow
                spacing: 8

                Repeater {
                    model: root.layoutTools

                    delegate: Rectangle {
                        required property var modelData
                        radius: 16
                        height: 28
                        width: label.implicitWidth + 20
                        color: "#11202a"
                        border.width: 1
                        border.color: "#49697a"
                        opacity: 0.88

                        Text {
                            id: label
                            anchors.centerIn: parent
                            text: modelData.label
                            color: "#e3f2f8"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 11
                            font.letterSpacing: 1.1
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (modelData.key === "tidy") {
                                    root.autoArrangeDeckLayout()
                                } else if (modelData.key === "save") {
                                    root.saveDeckLayout()
                                } else if (modelData.key === "restore") {
                                    root.restoreSavedDeckLayout()
                                } else if (modelData.key === "reset") {
                                    root.resetDeckLayout()
                                }
                            }
                        }
                    }
                }
            }
        }

        DeckPanelWorkspace {
            id: panelWorkspace
            anchors.top: controlDeck.bottom
            anchors.topMargin: 10
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            panels: root.deckPanels
            messages: root.messages
            statusLine: root.statusLine
            deckProgress: root.deckProgress
            requestComposer: root.requestComposer || ({})

            onPanelGridCommitted: function(panelId, gridX, gridY, colSpan, rowSpan) {
                root.updateDeckPanelGrid(panelId, gridX, gridY, colSpan, rowSpan)
            }
            onPanelPinnedChanged: function(panelId, pinned) {
                root.pinDeckPanel(panelId, pinned)
            }
            onPanelCollapsedChanged: function(panelId, collapsed) {
                root.collapseDeckPanel(panelId, collapsed)
            }
            onPanelHiddenChanged: function(panelId, hidden) {
                root.hideDeckPanel(panelId, hidden)
            }
        }

        Column {
            id: utilityColumn
            x: -root.workspaceRailWidth - 24
            y: workspaceRail.y + workspaceRail.height + 12 - deckField.y
            z: 8
            width: root.workspaceRailWidth
            height: Math.max(92, commandRail.y - (deckField.y + y) - 18)
            spacing: 10
            clip: true
            visible: root.panelUtilityVisible

            Rectangle {
                id: panelLauncher
                objectName: "deckPanelLauncher"
                width: parent.width
                height: Math.min(implicitHeight, Math.max(64, utilityColumn.height - (hiddenRail.visible ? 84 : 0)))
                radius: 20
                color: "#0f1820"
                border.width: 1
                border.color: "#425f70"
                opacity: 0.92
                implicitHeight: launcherHeader.height + launcherEntries.implicitHeight + 18

                Column {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 8

                    Row {
                        id: launcherHeader
                        width: parent.width
                        height: Math.max(22, panelLabel.implicitHeight, launcherToggle.height)
                        spacing: 8

                        Text {
                            id: panelLabel
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.max(0, parent.width - launcherToggle.width - 8)
                            text: "Panels"
                            color: "#edf7fb"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 12
                            font.letterSpacing: 1.2
                            elide: Text.ElideRight
                        }

                        Rectangle {
                            id: launcherToggle
                            anchors.verticalCenter: parent.verticalCenter
                            width: 22
                            height: 22
                            radius: 11
                            color: "#11202a"
                            border.width: 1
                            border.color: "#4a6779"

                            Text {
                                anchors.centerIn: parent
                                text: root.panelLauncherExpanded ? "-" : "+"
                                color: "#e3f2f8"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 12
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.panelLauncherExpanded = !root.panelLauncherExpanded
                            }
                        }
                    }

                    Column {
                        id: launcherEntries
                        width: parent.width
                        spacing: 6
                        visible: root.panelLauncherExpanded

                        Repeater {
                            model: root.panelCatalog

                            delegate: Rectangle {
                                required property var modelData
                                readonly property bool hidden: Boolean(modelData.hidden)
                                width: launcherEntries.width
                                height: 28
                                radius: 14
                                color: hidden ? "#10232f" : "#15212a"
                                border.width: 1
                                border.color: hidden ? "#6baec7" : "#35505f"
                                opacity: hidden ? 0.94 : 0.82

                                Row {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 8
                                    spacing: 6

                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: hidden ? "+" : "*"
                                        color: hidden ? "#b5eeff" : "#8fb5c3"
                                        font.family: "Bahnschrift SemiCondensed"
                                        font.pixelSize: 12
                                    }

                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: parent.width - 18
                                        text: modelData.title
                                        color: "#e7f5fb"
                                        font.family: "Bahnschrift SemiCondensed"
                                        font.pixelSize: 10
                                        elide: Text.ElideRight
                                    }
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        if (hidden) {
                                            root.restoreDeckPanel(String(modelData.panelId || ""))
                                        } else {
                                            root.hideDeckPanel(String(modelData.panelId || ""), true)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Column {
                id: hiddenRail
                objectName: "deckHiddenRail"
                width: parent.width
                spacing: 8
                visible: root.hiddenPanels.length > 0

                Text {
                    text: "Hidden"
                    color: "#8faab7"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: 11
                    font.letterSpacing: 1.3
                }

                Repeater {
                    model: root.hiddenPanels

                    delegate: Rectangle {
                        required property var modelData
                        width: hiddenRail.width
                        height: 54
                        radius: 18
                        color: "#11202a"
                        border.width: 1
                        border.color: "#436173"
                        opacity: 0.82

                        Column {
                            anchors.centerIn: parent
                            width: parent.width - 12
                            spacing: 2

                            Text {
                                width: parent.width
                                text: modelData.title
                                color: "#edf7fb"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 10
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.Wrap
                            }

                            Text {
                                width: parent.width
                                text: "Restore"
                                color: "#86a2af"
                                font.family: "Segoe UI"
                                font.pixelSize: 9
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.restoreDeckPanel(modelData.panelId)
                        }
                    }
                }
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
