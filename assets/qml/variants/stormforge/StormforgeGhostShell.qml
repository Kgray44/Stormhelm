import QtQuick 2.15

Item {
    id: root

    signal actionRequested(var action)

    property bool stormforgeFoundationReady: true
    property string stormforgeFoundationVersion: sf.foundationVersion
    property string stormforgeGhostComposition: "UI-P2S"
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
    property bool anchorCoreAvailable: true
    property url anchorCoreSource: Qt.resolvedUrl("StormforgeAnchorCore.qml")
    readonly property string ghostTone: resolveGhostTone()
    readonly property int visibleCardCount: Math.min(2, contextCards ? contextCards.length : 0)
    readonly property bool stormforgeFogFallbackRequested: fogBool("enabled", false)
        && String(fogValue("mode", "volumetric")).toLowerCase() === "fallback"

    enabled: false

    StormforgeTokens {
        id: sf
        objectName: "stormforgeGhostTokens"
    }

    function valueText(value) {
        if (value === undefined || value === null)
            return ""
        return String(value)
    }

    function toneFromCard(card) {
        if (!card)
            return ""
        var state = valueText(card.resultState || card.state || card.status || card.routeState).toLowerCase()
        var text = valueText((card.title || "") + " " + (card.body || "") + " " + (card.summary || "")).toLowerCase()
        if (state.indexOf("approval") >= 0 || text.indexOf("approval") >= 0 || text.indexOf("permission") >= 0)
            return "approval_required"
        if (state.indexOf("blocked") >= 0 || text.indexOf("blocked") >= 0)
            return "blocked"
        if (state.indexOf("failed") >= 0 || state.indexOf("error") >= 0 || text.indexOf("failed") >= 0)
            return "failed"
        if (state.indexOf("verified") >= 0)
            return "verified"
        if (state.indexOf("stale") >= 0)
            return "stale"
        if (state.indexOf("running") >= 0)
            return "running"
        if (state.indexOf("planned") >= 0)
            return "planned"
        return ""
    }

    function resolveGhostTone() {
        var cardTone = toneFromCard(root.primaryCard)
        if (cardTone.length > 0)
            return cardTone
        var voicePhase = valueText(root.voiceState.voice_current_phase || root.voiceState.voice_anchor_state).toLowerCase()
        if (voicePhase.indexOf("listening") >= 0)
            return "listening"
        if (voicePhase.indexOf("thinking") >= 0 || voicePhase.indexOf("routing") >= 0)
            return "thinking"
        if (voicePhase.indexOf("acting") >= 0)
            return "acting"
        if (voicePhase.indexOf("speaking") >= 0)
            return "speaking"
        return "idle"
    }

    function statusText() {
        if (root.statusLine.length > 0)
            return root.statusLine
        if (root.messages && root.messages.length > 0)
            return valueText(root.messages[root.messages.length - 1].content)
        return "Standing watch."
    }

    function fogValue(key, fallback) {
        if (!root.stormforgeFogConfig
                || root.stormforgeFogConfig[key] === undefined
                || root.stormforgeFogConfig[key] === null) {
            return fallback
        }
        return root.stormforgeFogConfig[key]
    }

    function fogBool(key, fallback) {
        var value = fogValue(key, fallback)
        if (typeof value === "boolean")
            return value
        if (typeof value === "string") {
            var normalized = value.toLowerCase()
            if (normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on")
                return true
            if (normalized === "0" || normalized === "false" || normalized === "no" || normalized === "off")
                return false
        }
        return Boolean(value)
    }

    function fogNumber(key, fallback) {
        var parsed = Number(fogValue(key, fallback))
        return isNaN(parsed) ? fallback : parsed
    }

    function clampNumber(value, minimum, maximum) {
        return Math.min(maximum, Math.max(minimum, value))
    }

    function normalizedItemCenterX(item, fallback) {
        if (!item || root.width <= 0)
            return fallback
        return clampNumber((item.x + item.width * 0.5 + root.contentOffsetX) / root.width, 0.0, 1.0)
    }

    function normalizedItemCenterY(item, fallback) {
        if (!item || root.height <= 0)
            return fallback
        return clampNumber((item.y + item.height * 0.5 + root.contentOffsetY) / root.height, 0.0, 1.0)
    }

    function protectedFogTop() {
        if (transcript && transcript.visible)
            return transcript.y
        if (statusLine && statusLine.visible)
            return statusLine.y
        return root.height * 0.44
    }

    function protectedFogBottom() {
        if (actionRegion && actionRegion.visible && actionRegion.height > 0)
            return actionRegion.y + actionRegion.height
        if (permissionPrompt && permissionPrompt.visible && permissionPrompt.height > 0)
            return permissionPrompt.y + permissionPrompt.height
        if (cardStack && cardStack.visible && cardStack.height > 0)
            return cardStack.y + cardStack.height
        if (transcript && transcript.visible && transcript.height > 0)
            return transcript.y + transcript.height
        return root.height * 0.72
    }

    function protectedFogCenterY() {
        if (root.height <= 0)
            return fogNumber("protectedCenterY", 0.58)
        return clampNumber(((protectedFogTop() + protectedFogBottom()) * 0.5 + root.contentOffsetY) / root.height, 0.32, 0.82)
    }

    function protectedFogRadius() {
        if (root.height <= 0)
            return fogNumber("protectedRadius", 0.36)
        var protectedSpan = Math.max(1, protectedFogBottom() - protectedFogTop()) / root.height
        return clampNumber(Math.max(fogNumber("protectedRadius", 0.36), protectedSpan * 0.62), 0.24, 0.56)
    }

    StormforgeGhostBackdrop {
        id: backdrop
        objectName: "stormforgeGhostBackdrop"
        anchors.fill: parent
        stateTone: root.ghostTone
        veilStrength: sf.opacityGhostVeil + root.adaptiveBackdropOpacity * 0.4
        z: sf.zBackground
    }

    StormforgeGhostStage {
        id: stage
        objectName: "stormforgeGhostStage"
        anchors.fill: parent
        stateTone: root.ghostTone
        contentOffsetX: root.contentOffsetX
        contentOffsetY: root.contentOffsetY
        z: sf.zSurface

        StormforgeGlassPanel {
            objectName: "stormforgeGhostFoundationPanel"
            width: Math.min(parent.width * 0.44, 520)
            height: 2
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(0, anchorHost.y + anchorHost.height + sf.space2)
            stateTone: root.ghostTone
            elevation: sf.elevationFlat
            fillOpacity: 0.0
            opacity: 0.18
            z: stage.layerInstrumentation
        }

        Item {
            id: composition
            objectName: "stormforgeGhostComposition"
            anchors.fill: parent
            z: stage.layerAnchor
        }

        StormforgeAnchorHost {
            id: anchorHost
            objectName: "stormforgeAnchorHost"
            width: Math.min(Math.max(parent.width * 0.18, 188), 244)
            height: width + sf.space6
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(parent.height * 0.16, parent.height * 0.36 - height * 0.5)
            voiceState: root.voiceState
            stateTone: root.ghostTone
            anchorCoreAvailable: root.anchorCoreAvailable
            anchorCoreSource: root.anchorCoreSource
            z: stage.layerAnchor
        }

        StormforgeGhostStatusLine {
            id: statusLine
            objectName: "stormforgeGhostStatusLine"
            width: Math.min(parent.width * 0.58, 620)
            anchors.horizontalCenter: parent.horizontalCenter
            y: anchorHost.y + anchorHost.height + sf.space5
            statusText: root.statusText()
            connectionText: root.connectionLabel
            timeText: root.timeLabel
            stateTone: root.ghostTone
            z: stage.layerTranscript
        }

        StormforgeGhostTranscript {
            id: transcript
            objectName: "stormforgeGhostTranscript"
            width: Math.min(parent.width * 0.56, 580)
            anchors.horizontalCenter: parent.horizontalCenter
            y: statusLine.y + statusLine.height + sf.space3
            messages: root.messages || []
            emptyText: root.statusText()
            stateTone: root.ghostTone
            z: stage.layerTranscript
        }

        StormforgeGhostPermissionPrompt {
            id: permissionPrompt
            objectName: "stormforgeGhostPermissionPrompt"
            width: Math.min(parent.width * 0.58, 620)
            anchors.horizontalCenter: parent.horizontalCenter
            y: transcript.y + transcript.height + sf.space3
            card: root.primaryCard || ({})
            z: stage.layerApproval
        }

        StormforgeGhostCardStack {
            id: cardStack
            objectName: "stormforgeGhostCardStack"
            width: Math.min(parent.width * 0.66, 620)
            anchors.horizontalCenter: parent.horizontalCenter
            y: permissionPrompt.visible
                ? permissionPrompt.y + permissionPrompt.height + sf.space3
                : transcript.y + transcript.height + sf.space3
            cards: root.contextCards || []
            stateTone: root.ghostTone
            z: stage.layerCards
        }

        StormforgeGhostActionRegion {
            id: actionRegion
            objectName: "stormforgeGhostActionRegion"
            anchors.horizontalCenter: parent.horizontalCenter
            y: cardStack.visible
                ? cardStack.y + cardStack.height + sf.space3
                : (permissionPrompt.visible ? permissionPrompt.y + permissionPrompt.height + sf.space3 : transcript.y + transcript.height + sf.space3)
            actions: root.actionStrip || []
            z: stage.layerActions
            onActionTriggered: function(action) {
                root.actionRequested(action)
            }
        }
    }

    Item {
        id: atmosphereSlot
        objectName: "stormforgeGhostAtmosphereSlot"
        property bool fogImplemented: true
        property bool fogActive: volumetricFog.active || fallbackLoader.active
        anchors.fill: parent
        visible: fogActive
        z: sf.zBackground + 1

        StormforgeVolumetricFogLayer {
            id: volumetricFog
            anchors.fill: parent
            config: root.stormforgeFogConfig
            protectedCenterX: root.normalizedItemCenterX(transcript, fogNumber("protectedCenterX", 0.50))
            protectedCenterY: root.protectedFogCenterY()
            protectedRadius: root.protectedFogRadius()
            anchorCenterX: root.normalizedItemCenterX(anchorHost, fogNumber("anchorCenterX", 0.50))
            anchorCenterY: root.normalizedItemCenterY(anchorHost, fogNumber("anchorCenterY", 0.30))
            anchorRadius: fogNumber("anchorRadius", 0.18)
        }

        Loader {
            id: fallbackLoader
            anchors.fill: parent
            active: root.stormforgeFogFallbackRequested

            sourceComponent: StormforgeFogFallbackLayer {
                anchors.fill: parent
                config: root.stormforgeFogConfig
            }
        }
    }
}
