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
    property real ghostRevealProgress: bridge ? bridge.ghostRevealTarget : 1.0
    readonly property real coreSize: root.mix(Math.min(width * 0.18, 238), 176, deckProgress)
    readonly property real coreCenterY: root.mix(height * 0.42, height * 0.22, deckProgress)
    readonly property real coreY: coreCenterY - coreSize / 2 + (1 - ghostRevealProgress) * 10
    readonly property int ghostDraftLength: bridge ? bridge.ghostDraftText.length : 0
    readonly property real ghostStripWidth: Math.min(root.width * 0.62, 540 + root.ghostDraftLength * 8)
    readonly property real deckStripWidth: Math.min(root.width * 0.52, 820)
    readonly property var ghostAdaptiveStyle: bridge ? bridge.ghostAdaptiveStyle : ({})
    readonly property var ghostPlacement: bridge ? bridge.ghostPlacement : ({})
    readonly property real ghostOffsetX: root.ghostMode ? root.ghostPlacementNumber("offsetX", 0) : 0
    readonly property real ghostOffsetY: root.ghostMode ? root.ghostPlacementNumber("offsetY", 0) : 0

    function ghostStyleNumber(key, fallback) {
        if (!root.ghostAdaptiveStyle || root.ghostAdaptiveStyle[key] === undefined || root.ghostAdaptiveStyle[key] === null) {
            return fallback
        }
        return Number(root.ghostAdaptiveStyle[key])
    }

    function ghostPlacementNumber(key, fallback) {
        if (!root.ghostPlacement || root.ghostPlacement[key] === undefined || root.ghostPlacement[key] === null) {
            return fallback
        }
        return Number(root.ghostPlacement[key])
    }

    Behavior on deckProgress {
        NumberAnimation { duration: 440; easing.type: Easing.InOutCubic }
    }
    Behavior on ghostRevealProgress {
        NumberAnimation { duration: 320; easing.type: Easing.InOutCubic }
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
        objectName: "ghostShell"
        anchors.fill: parent
        coreBottom: fieldStrip.y + fieldStrip.height
        deckProgress: root.deckProgress
        messages: bridge ? bridge.ghostMessages : []
        contextCards: bridge ? bridge.contextCards : []
        primaryCard: bridge ? bridge.ghostPrimaryCard : ({})
        actionStrip: bridge ? bridge.ghostActionStrip : []
        cornerReadouts: bridge ? bridge.ghostCornerReadouts : []
        statusLine: bridge ? bridge.statusLine : ""
        connectionLabel: bridge ? bridge.connectionLabel : ""
        timeLabel: bridge ? bridge.localTimeLabel : ""
        contentOffsetX: root.ghostOffsetX
        contentOffsetY: root.ghostOffsetY
        adaptiveTone: root.ghostStyleNumber("tone", 0)
        adaptiveTextContrast: root.ghostStyleNumber("textContrast", 0.08)
        adaptiveSecondaryTextContrast: root.ghostStyleNumber("secondaryTextContrast", 0.05)
        adaptiveShadowOpacity: root.ghostStyleNumber("shadowOpacity", 0.1)
        adaptiveBackdropOpacity: root.ghostStyleNumber("backdropOpacity", 0.04)
        visible: opacity > 0.02
        opacity: (1 - root.deckProgress) * root.ghostRevealProgress
        scale: (1 - root.deckProgress * 0.018) * root.mix(0.986, 1.0, root.ghostRevealProgress)
        z: 12

        Behavior on opacity {
            NumberAnimation { duration: 320; easing.type: Easing.InOutQuad }
        }
        Behavior on scale {
            NumberAnimation { duration: 360; easing.type: Easing.InOutQuad }
        }

        onActionRequested: function(action) {
            if (action.sendText) {
                stormhelmBridge.sendMessage(action.sendText)
            } else if (action.localAction) {
                stormhelmBridge.performLocalSurfaceAction(action.localAction)
            }
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
        deckPanels: bridge ? bridge.deckPanels : []
        hiddenPanels: bridge ? bridge.hiddenDeckPanels : []
        panelCatalog: bridge ? bridge.deckPanelCatalog : []
        deckLayoutPresets: bridge ? bridge.deckLayoutPresets : []
        activeDeckLayoutPreset: bridge ? bridge.activeDeckLayoutPreset : ""
        workspaceItems: bridge ? bridge.workspaceRailItems : []
        workspaceCanvas: bridge ? bridge.workspaceCanvas : ({})
        requestComposer: bridge ? bridge.requestComposer : ({})
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
        onUpdateDeckPanelGrid: function(panelId, gridX, gridY, colSpan, rowSpan) {
            stormhelmBridge.updateDeckPanelGrid(panelId, gridX, gridY, colSpan, rowSpan)
        }
        onPinDeckPanel: function(panelId, pinned) {
            stormhelmBridge.setDeckPanelPinned(panelId, pinned)
        }
        onCollapseDeckPanel: function(panelId, collapsed) {
            stormhelmBridge.setDeckPanelCollapsed(panelId, collapsed)
        }
        onHideDeckPanel: function(panelId, hidden) {
            stormhelmBridge.setDeckPanelHidden(panelId, hidden)
        }
        onRestoreDeckPanel: function(panelId) {
            stormhelmBridge.restoreDeckPanel(panelId)
        }
        onSaveDeckLayout: stormhelmBridge.saveDeckLayout()
        onResetDeckLayout: stormhelmBridge.resetDeckLayout()
        onAutoArrangeDeckLayout: stormhelmBridge.autoArrangeDeckLayout("")
        onRestoreSavedDeckLayout: stormhelmBridge.restoreSavedDeckLayout()
        onSetDeckLayoutPreset: function(preset) {
            stormhelmBridge.setDeckLayoutPreset(preset)
        }

        Behavior on opacity {
            NumberAnimation { duration: 300; easing.type: Easing.InOutQuad }
        }
        Behavior on scale {
            NumberAnimation { duration: 360; easing.type: Easing.InOutQuad }
        }
    }

    Item {
        id: ghostCenterCluster
        anchors.fill: parent
        z: 34

        transform: Translate {
            id: ghostCenterMotion
            x: root.ghostOffsetX
            y: root.ghostOffsetY

            Behavior on x {
                NumberAnimation { duration: 620; easing.type: Easing.InOutCubic }
            }
            Behavior on y {
                NumberAnimation { duration: 620; easing.type: Easing.InOutCubic }
            }
        }

        VoiceCore {
            id: voiceCore
            objectName: "ghostVoiceCore"
            width: root.coreSize
            height: root.coreSize
            anchors.horizontalCenter: parent.horizontalCenter
            y: root.coreY
            opacity: root.mix(0.0, 1.0, root.ghostRevealProgress)
            scale: root.mix(0.988, 1.0, root.ghostRevealProgress)
            assistantState: bridge ? bridge.assistantState : "idle"
            shellMode: bridge ? bridge.mode : "ghost"
            adaptiveGlowBoost: root.ghostMode ? root.ghostStyleNumber("glowBoost", 0.06) : 0
            adaptiveAnchorGlowBoost: root.ghostMode ? root.ghostStyleNumber("anchorGlowBoost", 0.08) : 0
            adaptiveAnchorStrokeBoost: root.ghostMode ? root.ghostStyleNumber("anchorStrokeBoost", 0.12) : 0
            adaptiveAnchorFillBoost: root.ghostMode ? root.ghostStyleNumber("anchorFillBoost", 0.04) : 0
            adaptiveAnchorBackdropOpacity: root.ghostMode ? root.ghostStyleNumber("anchorBackdropOpacity", 0.05) : 0
            adaptiveTone: root.ghostMode ? root.ghostStyleNumber("tone", 0) : 0
            adaptiveLabelContrast: root.ghostMode ? root.ghostStyleNumber("textContrast", 0.08) : 0
            z: 6

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
            objectName: "ghostFieldStrip"
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
            ghostStyle: root.ghostAdaptiveStyle
            opacity: root.mix(0.0, 1.0, root.ghostRevealProgress)
            scale: root.mix(0.992, 1.0, root.ghostRevealProgress)
            z: 0
        }
    }

    ForegroundMistLayer {
        anchors.fill: parent
        mode: bridge ? bridge.mode : "ghost"
        deckProgress: root.deckProgress
        rectA: root.normalizedRect(Qt.rect(fieldStrip.x + root.ghostOffsetX, fieldStrip.y + root.ghostOffsetY, fieldStrip.width, fieldStrip.height))
        rectB: root.ghostMode
            ? root.normalizedRect(Qt.rect(root.width * 0.35 + root.ghostOffsetX, voiceCore.y + root.ghostOffsetY + voiceCore.height * 0.50, root.width * 0.30, Math.max(88, fieldStrip.y + fieldStrip.height - (voiceCore.y + voiceCore.height * 0.50) + 28)))
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
