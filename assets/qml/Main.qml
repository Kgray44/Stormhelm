import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15

import "components"

ApplicationWindow {
    id: root

    readonly property var bridge: stormhelmBridge
    readonly property string uiVisualVariant: bridge ? bridge.uiVisualVariant : "classic"
    readonly property bool stormforgeVisualVariant: uiVisualVariant === "stormforge"
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
    readonly property real coreSize: root.mix(Math.min(width * 0.20, 272), 196, deckProgress)
    readonly property real coreCenterY: root.mix(height * 0.42, height * 0.22, deckProgress)
    readonly property real coreY: coreCenterY - coreSize / 2 + (1 - ghostRevealProgress) * 10
    readonly property int ghostDraftLength: bridge ? bridge.ghostDraftText.length : 0
    readonly property real ghostStripWidth: Math.min(root.width * 0.62, 580)
    readonly property real deckStripWidth: Math.min(root.width * 0.52, 820)
    readonly property var ghostAdaptiveStyle: bridge ? bridge.ghostAdaptiveStyle : ({})
    readonly property var ghostPlacement: bridge ? bridge.ghostPlacement : ({})
    readonly property var stormforgeFogConfig: bridge ? bridge.uiStormforgeFog : ({})
    readonly property real ghostOffsetX: root.ghostMode ? root.ghostPlacementNumber("offsetX", 0) : 0
    readonly property real ghostOffsetY: root.ghostMode ? root.ghostPlacementNumber("offsetY", 0) : 0
    property real typingDarkProgress: bridge && bridge.ghostCaptureActive && root.ghostMode ? 1.0 : 0.0

    function ghostStyleNumber(key, fallback) {
        var adjusted = fallback
        if (!root.ghostAdaptiveStyle || root.ghostAdaptiveStyle[key] === undefined || root.ghostAdaptiveStyle[key] === null) {
            adjusted = fallback
        } else {
            adjusted = Number(root.ghostAdaptiveStyle[key])
        }
        if (key === "tone")
            return Math.max(adjusted, 0) + root.typingDarkProgress * 0.46
        if (key === "surfaceOpacity")
            return Math.min(0.96, adjusted + root.typingDarkProgress * 0.14)
        if (key === "edgeOpacity")
            return Math.min(0.58, adjusted + root.typingDarkProgress * 0.08)
        if (key === "lineOpacity")
            return Math.min(0.24, adjusted + root.typingDarkProgress * 0.06)
        if (key === "textContrast")
            return Math.min(0.48, adjusted + root.typingDarkProgress * 0.16)
        if (key === "secondaryTextContrast")
            return Math.min(0.34, adjusted + root.typingDarkProgress * 0.12)
        if (key === "shadowOpacity")
            return Math.min(0.42, adjusted + root.typingDarkProgress * 0.14)
        if (key === "backdropOpacity")
            return Math.min(0.42, adjusted + root.typingDarkProgress * 0.18)
        if (key === "anchorGlowBoost")
            return Math.min(0.62, adjusted + root.typingDarkProgress * 0.12)
        if (key === "anchorStrokeBoost")
            return Math.min(0.68, adjusted + root.typingDarkProgress * 0.14)
        if (key === "anchorFillBoost")
            return Math.min(0.42, adjusted + root.typingDarkProgress * 0.08)
        if (key === "anchorBackdropOpacity")
            return Math.min(0.42, adjusted + root.typingDarkProgress * 0.16)
        return adjusted
    }

    function ghostPlacementNumber(key, fallback) {
        if (!root.ghostPlacement || root.ghostPlacement[key] === undefined || root.ghostPlacement[key] === null) {
            return fallback
        }
        return Number(root.ghostPlacement[key])
    }

    property var renderConfirmationSignatures: ({})
    property bool renderConfirmationQueued: false

    function renderValue(value) {
        if (value === undefined || value === null) {
            return ""
        }
        return String(value)
    }

    function contextCardContains(needle) {
        var cards = bridge ? bridge.contextCards : []
        var wanted = String(needle || "").toLowerCase()
        for (var index = 0; index < cards.length; index += 1) {
            var card = cards[index] || {}
            var text = String((card.title || "") + " " + (card.subtitle || "") + " " + (card.body || "")).toLowerCase()
            if (text.indexOf(wanted) >= 0) {
                return true
            }
        }
        return false
    }

    function requestComposerValue() {
        var composer = bridge ? bridge.requestComposer : ({})
        return root.renderValue(
            composer.routeLabel
            || composer.statusLabel
            || composer.routeChip
            || composer.statusChip
            || composer.microStatus
            || composer.placeholder
        )
    }

    function routeInspectorValue() {
        var inspector = bridge ? bridge.routeInspector : ({})
        return root.renderValue(
            inspector.statusLabel
            || inspector.selectedRouteLabel
            || inspector.routeLabel
            || inspector.family
        )
    }

    function confirmRenderSurface(surface, componentId, key, value, visible) {
        if (!bridge || !bridge.confirmRenderVisible || !bridge.renderSurfaceRevision) {
            return
        }
        var revision = bridge.renderSurfaceRevision(surface)
        if (revision <= 0) {
            return
        }
        var stateValue = root.renderValue(value)
        var status = visible ? "confirmed" : "hidden"
        var signature = surface + ":" + revision + ":" + key + ":" + stateValue + ":" + status
        if (root.renderConfirmationSignatures[surface] === signature) {
            return
        }
        root.renderConfirmationSignatures[surface] = signature
        bridge.confirmRenderVisible({
            "surface": surface,
            "model_revision": revision,
            "qml_component_id": componentId,
            "visible_state_key": key,
            "visible_state_value": stateValue,
            "visible": visible,
            "render_confirmation_status": status,
            "confirmation_source": "qml_component"
        })
    }

    function confirmVisibleSurfaces() {
        root.renderConfirmationQueued = false
        if (!bridge) {
            return
        }
        var primary = bridge.ghostPrimaryCard || ({})
        var primaryValue = root.renderValue(primary.title || primary.summary || primary.resultState || bridge.statusLine)
        root.confirmRenderSurface(
            "ghost_primary",
            "ghostPrimaryCommandCard",
            "primary_state",
            primaryValue,
            ghostShell.visible && primaryValue.length > 0
        )

        var actionCount = bridge.ghostActionStrip ? bridge.ghostActionStrip.length : 0
        root.confirmRenderSurface(
            "ghost_action_strip",
            "ghostActionStrip",
            "action_count",
            String(actionCount),
            ghostShell.visible && actionCount > 0
        )

        var composerValue = root.requestComposerValue()
        root.confirmRenderSurface(
            "composer_chips",
            "requestComposerStatusChips",
            "composer_status",
            composerValue,
            composerValue.length > 0 && (ghostShell.visible || deckShell.visible)
        )

        var voice = bridge.voiceState || ({})
        var voiceValue = root.renderValue(
            voice.voice_current_phase
            || voice.voice_anchor_state
            || voice.active_playback_status
        )
        root.confirmRenderSurface(
            "voice_core",
            "ghostVoiceCore",
            "voice_current_phase",
            voiceValue,
            voiceCore.opacity > 0.02 && voiceValue.length > 0
        )

        var approvalVisible = root.contextCardContains("approval") || String(primaryValue).toLowerCase().indexOf("approval") >= 0
        root.confirmRenderSurface(
            "approval_prompt",
            "ghostApprovalPrompt",
            "approval_prompt",
            approvalVisible ? "visible" : "",
            ghostShell.visible && approvalVisible
        )

        var clarificationText = String(primaryValue).toLowerCase()
        var composer = bridge ? bridge.requestComposer : ({})
        var clarificationChoices = composer.clarificationChoices || []
        var clarificationVisible = root.contextCardContains("clarification")
            || root.contextCardContains("clarify")
            || clarificationText.indexOf("clarification") >= 0
            || clarificationText.indexOf("clarify") >= 0
            || clarificationChoices.length > 0
        root.confirmRenderSurface(
            "clarification_prompt",
            "ghostClarificationPrompt",
            "clarification_prompt",
            clarificationVisible ? "visible" : "",
            ghostShell.visible && clarificationVisible
        )

        var stream = bridge.eventStreamConnectionState || ({})
        var deckValue = root.renderValue(
            (stream.connection_state || "unknown")
            + ":dup=" + (stream.duplicate_ignored_count || 0)
            + ":ooo=" + (stream.out_of_order_ignored_count || 0)
            + ":reconcile=" + !!stream.reconciliation_requested
        )
        root.confirmRenderSurface(
            "deck_event_spine",
            "deckEventSpine",
            "event_stream_state",
            deckValue,
            deckShell.visible && deckValue.length > 0
        )

        var inspectorValue = root.routeInspectorValue()
        root.confirmRenderSurface(
            "route_inspector",
            "deckRouteInspector",
            "route_inspector_state",
            inspectorValue,
            deckShell.visible && inspectorValue.length > 0
        )
    }

    function scheduleRenderConfirmations() {
        if (root.renderConfirmationQueued) {
            return
        }
        root.renderConfirmationQueued = true
        Qt.callLater(root.confirmVisibleSurfaces)
    }

    Behavior on deckProgress {
        NumberAnimation { duration: 440; easing.type: Easing.InOutCubic }
    }
    Behavior on ghostRevealProgress {
        NumberAnimation { duration: 320; easing.type: Easing.InOutCubic }
    }
    Behavior on typingDarkProgress {
        NumberAnimation { duration: 460; easing.type: Easing.InOutCubic }
    }

    onClosing: function(close) {
        if (bridge && bridge.handleCloseRequest()) {
            close.accepted = false
        }
    }

    Component.onCompleted: root.scheduleRenderConfirmations()

    Connections {
        target: bridge
        function onCollectionsChanged() { root.scheduleRenderConfirmations() }
        function onStatusChanged() { root.scheduleRenderConfirmations() }
        function onVoiceStateChanged() { root.scheduleRenderConfirmations() }
        function onModeChanged() { root.scheduleRenderConfirmations() }
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

    Rectangle {
        anchors.fill: parent
        color: "#02070b"
        opacity: root.typingDarkProgress * 0.22
        visible: opacity > 0.01
        z: 5

        Behavior on opacity {
            NumberAnimation { duration: 460; easing.type: Easing.InOutCubic }
        }
    }

    VariantGhostShell {
        id: ghostShell
        objectName: "ghostShell"
        anchors.fill: parent
        visualVariant: root.uiVisualVariant
        coreBottom: fieldStrip.y + fieldStrip.height
        deckProgress: root.deckProgress
        messages: bridge ? bridge.ghostMessages : []
        contextCards: bridge ? bridge.contextCards : []
        primaryCard: bridge ? bridge.ghostPrimaryCard : ({})
        actionStrip: bridge ? bridge.ghostActionStrip : []
        cornerReadouts: bridge ? bridge.ghostCornerReadouts : []
        voiceState: bridge ? bridge.voiceState : ({})
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
        stormforgeFogConfig: root.stormforgeFogConfig
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

    VariantCommandDeckShell {
        id: deckShell
        objectName: "deckShell"
        anchors.fill: parent
        visualVariant: root.uiVisualVariant
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
        voiceState: bridge ? bridge.voiceState : ({})
        statusLine: bridge ? bridge.statusLine : ""
        modeTitle: bridge ? bridge.modeTitle : "Command Deck"
        modeSubtitle: bridge ? bridge.modeSubtitle : ""
        assistantState: bridge ? bridge.assistantState : "idle"
        visible: opacity > 0.02
        opacity: root.deckProgress > 0.02 ? 1 : 0
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
        objectName: "sharedGhostCenterCluster"
        anchors.fill: parent
        visible: !root.stormforgeVisualVariant
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
            voiceState: bridge ? bridge.voiceState : ({})
            anchorState: bridge ? (bridge.voiceState.voice_anchor_state || "idle") : "idle"
            speakingActive: bridge ? !!bridge.voiceState.speaking_visual_active : false
            motionIntensity: bridge ? Number(bridge.voiceState.voice_motion_intensity || 0.12) : 0.12
            audioLevel: bridge ? Number(bridge.voiceState.voice_smoothed_output_level || 0) : 0
            smoothedAudioLevel: bridge ? Number(bridge.voiceState.voice_smoothed_output_level || 0) : 0
            visualDriveLevel: bridge ? Number(bridge.voiceState.voice_visual_drive_level !== undefined ? bridge.voiceState.voice_visual_drive_level : (bridge.voiceState.audioDriveLevel || 0)) : 0
            visualDrivePeak: bridge ? Number(bridge.voiceState.voice_visual_drive_peak !== undefined ? bridge.voiceState.voice_visual_drive_peak : bridge.voiceState.voice_visual_drive_level || 0) : 0
            centerBlobDrive: bridge ? Number(bridge.voiceState.voice_center_blob_drive !== undefined ? bridge.voiceState.voice_center_blob_drive : (bridge.voiceState.audioDriveLevel || 0)) : 0
            centerBlobScaleDrive: bridge ? Number(bridge.voiceState.voice_center_blob_scale_drive !== undefined ? bridge.voiceState.voice_center_blob_scale_drive : (bridge.voiceState.voice_center_blob_drive !== undefined ? bridge.voiceState.voice_center_blob_drive : (bridge.voiceState.audioDriveLevel || 0))) : 0
            backendCenterBlobScale: bridge ? Number(bridge.voiceState.voice_center_blob_scale !== undefined ? bridge.voiceState.voice_center_blob_scale : 1.0) : 1.0
            outerSpeakingMotion: bridge ? Number(bridge.voiceState.voice_outer_speaking_motion !== undefined ? bridge.voiceState.voice_outer_speaking_motion : (bridge.voiceState.voice_visual_drive_level || 0)) : 0
            audioReactiveAvailable: bridge ? !!bridge.voiceState.voice_audio_reactive_available : false
            audioReactiveSource: bridge ? (bridge.voiceState.voice_audio_reactive_source || "unavailable") : "unavailable"
            statusLabel: bridge ? ((bridge.voiceState.voice_anchor && bridge.voiceState.voice_anchor.state_label) || "") : ""
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
            height: implicitHeight
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

            Behavior on width {
                NumberAnimation { duration: 360; easing.type: Easing.InOutCubic }
            }
            Behavior on height {
                NumberAnimation { duration: 260; easing.type: Easing.InOutCubic }
            }
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
