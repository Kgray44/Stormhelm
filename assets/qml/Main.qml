import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15

import "components"

ApplicationWindow {
    id: root

    readonly property var bridge: stormhelmBridge
    function mix(a, b, t) { return a + (b - a) * t }
    function normalizedRect(rectValue) {
        if (!rectValue || width <= 0 || height <= 0) {
            return Qt.vector4d(0, 0, 0, 0)
        }
        return Qt.vector4d(
            rectValue.x / width,
            rectValue.y / height,
            rectValue.width / width,
            rectValue.height / height
        )
    }
    x: Screen.virtualX
    y: Screen.virtualY
    width: Screen.width
    height: Screen.height
    minimumWidth: Screen.width
    minimumHeight: Screen.height
    visible: true
    visibility: Window.Windowed
    color: "transparent"
    background: Item {}
    title: bridge ? bridge.windowTitle : "Stormhelm"
    flags: Qt.FramelessWindowHint | Qt.Window

    readonly property bool ghostMode: !bridge || bridge.mode === "ghost"
    property real deckProgress: bridge && bridge.mode === "deck" ? 1 : 0
    readonly property real coreSize: root.mix(Math.min(width * 0.18, 238), 176, deckProgress)
    readonly property real coreCenterY: root.mix(height * 0.42, height * 0.22, deckProgress)
    readonly property real coreY: coreCenterY - coreSize / 2
    readonly property int ghostDraftLength: bridge ? bridge.ghostDraftText.length : 0
    readonly property real ghostStripWidth: Math.min(root.width * 0.62, 540 + root.ghostDraftLength * 8)
    readonly property real deckStripWidth: Math.min(root.width * 0.52, 820)

    Behavior on deckProgress {
        NumberAnimation { duration: 440; easing.type: Easing.InOutCubic }
    }

    onClosing: function(close) {
        if (bridge && bridge.handleCloseRequest()) {
            close.accepted = false
        }
    }

    Shortcut {
        sequences: [StandardKey.Cancel]
        onActivated: {
            if (bridge && bridge.mode === "deck") {
                bridge.setMode("ghost")
            } else {
                bridge && bridge.hideWindow()
            }
        }
    }

    Shortcut {
        sequence: bridge ? bridge.ghostShortcutLabel : "Ctrl+Space"
        onActivated: {
            if (stormhelmGhostInput) {
                stormhelmGhostInput.beginCapture()
            } else if (bridge) {
                bridge.beginGhostCapture()
            }
        }
    }

    StormBackground {
        anchors.fill: parent
        mode: bridge ? bridge.mode : "ghost"
        deckProgress: root.deckProgress
    }

    GhostShell {
        id: ghostShell
        anchors.fill: parent
        coreBottom: fieldStrip.y + fieldStrip.height
        deckProgress: root.deckProgress
        messages: bridge ? bridge.ghostMessages : []
        contextCards: bridge ? bridge.contextCards : []
        cornerReadouts: bridge ? bridge.ghostCornerReadouts : []
        statusLine: bridge ? bridge.statusLine : ""
        connectionLabel: bridge ? bridge.connectionLabel : ""
        timeLabel: bridge ? bridge.localTimeLabel : ""
        visible: opacity > 0.02
        opacity: 1 - root.deckProgress * 0.58
        scale: 1 - root.deckProgress * 0.018
        z: 12

        Behavior on opacity {
            NumberAnimation { duration: 320; easing.type: Easing.InOutQuad }
        }
        Behavior on scale {
            NumberAnimation { duration: 360; easing.type: Easing.InOutQuad }
        }
    }

    CommandDeckShell {
        id: deckShell
        objectName: "deckShell"
        anchors.fill: parent
        coreBottom: fieldStrip.y + fieldStrip.height
        deckProgress: root.deckProgress
        messages: bridge ? bridge.messages : []
        activeModule: bridge ? bridge.activeDeckModule : ({})
        supportModules: bridge ? bridge.deckSupportModules : []
        workspaceItems: bridge ? bridge.workspaceRailItems : []
        workspaceCanvas: bridge ? bridge.workspaceCanvas : ({})
        railItems: bridge ? bridge.commandRailItems : []
        statusItems: bridge ? bridge.statusStripItems : []
        statusLine: bridge ? bridge.statusLine : ""
        modeTitle: bridge ? bridge.modeTitle : "Command Deck"
        modeSubtitle: bridge ? bridge.modeSubtitle : ""
        assistantState: bridge ? bridge.assistantState : "idle"
        visible: opacity > 0.02
        opacity: root.deckProgress
        scale: 1.02 - root.deckProgress * 0.02
        z: 10

        onActivateDestination: function(key) {
            stormhelmBridge.activateModule(key)
        }
        onActivateWorkspaceItem: function(key) {
            stormhelmBridge.activateWorkspaceSection(key)
        }
        onActivateOpenedItem: function(itemId) {
            stormhelmBridge.activateOpenedItem(itemId)
        }
        onCloseOpenedItem: function(itemId) {
            stormhelmBridge.closeOpenedItem(itemId)
        }

        Behavior on opacity {
            NumberAnimation { duration: 300; easing.type: Easing.InOutQuad }
        }
        Behavior on scale {
            NumberAnimation { duration: 360; easing.type: Easing.InOutQuad }
        }
    }

    VoiceCore {
        id: voiceCore
        width: root.coreSize
        height: root.coreSize
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.coreY
        assistantState: bridge ? bridge.assistantState : "idle"
        shellMode: bridge ? bridge.mode : "ghost"
        z: 40

        Behavior on y {
            NumberAnimation { duration: 360; easing.type: Easing.InOutCubic }
        }
        Behavior on width {
            NumberAnimation { duration: 360; easing.type: Easing.InOutCubic }
        }
        Behavior on height {
            NumberAnimation { duration: 360; easing.type: Easing.InOutCubic }
        }

        onRequestDeck: bridge && bridge.setMode("deck")
        onRequestGhost: bridge && bridge.setMode("ghost")
    }

    SignalStrip {
        id: fieldStrip
        width: root.mix(root.ghostStripWidth, root.deckStripWidth, root.deckProgress)
        anchors.horizontalCenter: parent.horizontalCenter
        y: voiceCore.y + voiceCore.height + 14
        shellMode: bridge ? bridge.mode : "ghost"
        eyebrow: bridge ? bridge.connectionLabel : ""
        primaryText: bridge ? bridge.statusLine : ""
        secondaryText: bridge ? (ghostMode ? bridge.localTimeLabel : bridge.modeSubtitle) : ""
        stateName: bridge ? bridge.assistantState : "idle"
        captureActive: bridge ? bridge.ghostCaptureActive : false
        draftText: bridge ? bridge.ghostDraftText : ""
        hintText: bridge ? bridge.ghostInputHint : ""
        deckProgress: root.deckProgress
        z: 34
    }

    ForegroundMistLayer {
        anchors.fill: parent
        mode: bridge ? bridge.mode : "ghost"
        deckProgress: root.deckProgress
        rectA: root.normalizedRect(Qt.rect(fieldStrip.x, fieldStrip.y, fieldStrip.width, fieldStrip.height))
        rectB: root.ghostMode
            ? root.normalizedRect(Qt.rect(root.width * 0.35, voiceCore.y + voiceCore.height * 0.50, root.width * 0.30, Math.max(88, fieldStrip.y + fieldStrip.height - (voiceCore.y + voiceCore.height * 0.50) + 28)))
            : root.normalizedRect(deckShell.collaborationRect)
        rectC: root.ghostMode
            ? Qt.vector4d(0, 0, 0, 0)
            : root.normalizedRect(deckShell.contextRect)
        rectD: root.ghostMode
            ? Qt.vector4d(0, 0, 0, 0)
            : root.normalizedRect(deckShell.railRect)
        z: 9
    }
}
