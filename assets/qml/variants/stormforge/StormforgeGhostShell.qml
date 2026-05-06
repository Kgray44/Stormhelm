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
    property var voiceVisualState: ({})
    property var pendingVoiceState: ({})
    property var visualVoiceState: ({})
    property int _pendingVoiceStateSerial: 0
    property int _appliedVoiceStateSerial: 0
    property int voiceEventCountDuringSpeaking: 0
    property int voiceEventRateDuringSpeaking: 0
    readonly property int voicePayloadUpdatesPerSecond: root.voiceEventRateDuringSpeaking
    readonly property int voiceSurfaceUpdatesPerSecond: root.voiceEventRateDuringSpeaking
    property int visualVoiceStateApplyCount: 0
    property int visualVoiceStateApplyRateDuringSpeaking: 0
    property double _voiceEventWindowStartedMs: 0
    property int _voiceEventWindowCount: 0
    property int _visualApplyWindowCount: 0
    property double lastVoiceEventAtMs: 0
    property double visualVoiceStateLastAppliedMs: 0
    property int productionQmlDiagnosticEmitCount: 0
    property double productionQmlDiagnosticLastEmitMs: 0
    property double productionQmlDiagnosticMaxGapMs: 0
    readonly property int productionQmlDiagnosticMinIntervalMs: 100
    property bool captureActive: false
    property string draftText: ""
    property string hintText: ""
    property string assistantState: "idle"
    property var routeInspector: ({})
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
    property var stormforgeVoiceDiagnosticsConfig: ({})
    property bool anchorCoreAvailable: true
    property url anchorCoreSource: Qt.resolvedUrl("StormforgeAnchorCore.qml")
    readonly property string liveVoiceIsolationVersion: "UI-VOICE-LIVE-ISO"
    readonly property string stormforgeRenderCadenceVersion: "UI-P2R"
    readonly property string voiceVisualSyncVersion: "UI-P2R"
    readonly property bool sharedAnimationClockEnabled: true
    readonly property alias visualClockTargetFps: stormforgeAnimationClock.targetFps
    readonly property alias visualClockMinAcceptableFps: stormforgeAnimationClock.minAcceptableFps
    readonly property alias visualClockFrameCounter: stormforgeAnimationClock.frameCounter
    readonly property alias visualClockFps: stormforgeAnimationClock.measuredFps
    readonly property alias visualClockLongFrameCount: stormforgeAnimationClock.longFrameCount
    readonly property alias visualClockLastFrameGapMs: stormforgeAnimationClock.lastFrameGapMs
    readonly property alias visualClockMaxFrameGapMs: stormforgeAnimationClock.maxFrameGapMs
    readonly property alias visualClockCadenceStable: stormforgeAnimationClock.cadenceStable
    readonly property alias visualClockSpeakingCadenceStable: stormforgeAnimationClock.speakingCadenceStable
    readonly property bool rawAudioEventsDoNotRequestPaint: true
    readonly property bool audioReactiveUsesVisualClock: anchorHost.audioReactiveUsesVisualClock
    readonly property real anchorPaintFpsDuringSpeaking: anchorHost.visualSpeakingActive ? anchorHost.anchorPaintCountPerSecond : 0
    readonly property real anchorRequestPaintFpsDuringSpeaking: anchorHost.visualSpeakingActive ? anchorHost.anchorRequestPaintCountPerSecond : 0
    readonly property real dynamicCorePaintFpsDuringSpeaking: anchorHost.visualSpeakingActive ? anchorHost.anchorPaintCountPerSecond : 0
    readonly property real fogTickFpsDuringSpeaking: root.visualVoiceSpeakingActive && atmosphereSlot.fogActive ? stormforgeAnimationClock.measuredFps : 0
    readonly property real speakingVisualLatencyEstimateMs: Math.max(0, stormforgeAnimationClock.deltaTimeMs)
    readonly property bool visualVoiceSpeakingActive: voiceSupportsSpeakingFor(root.mergedVoiceVisualState())
    readonly property string anchorVisualizerMode: normalizeAnchorVisualizerMode(voiceDiagnosticValue("anchorVisualizerMode", "auto"))
    readonly property string anchorRenderer: normalizeAnchorRenderer(voiceDiagnosticValue("anchorRenderer", "legacy_blob_reference"))
    readonly property bool stormforgeFogDiagnosticDisableDuringSpeech: fogBool("diagnosticDisableDuringSpeech", false)
    readonly property bool stormforgeFogDisabledDuringSpeech: root.stormforgeFogDiagnosticDisableDuringSpeech
        && root.visualVoiceSpeakingActive
    readonly property string currentAnchorVisualizerMode: anchorHost.effectiveAnchorVisualizerMode
    readonly property string requestedAnchorVisualizerMode: anchorHost.requestedAnchorVisualizerMode
    readonly property bool forcedVisualizerModeHonored: anchorHost.forcedVisualizerModeHonored
    readonly property string forcedVisualizerModeUnavailableReason: anchorHost.forcedVisualizerModeUnavailableReason
    readonly property string visualizerStrategySelectedBy: anchorHost.visualizerStrategySelectedBy
    readonly property string qmlSpeakingEnergySource: anchorHost.qmlSpeakingEnergySource
    readonly property real finalSpeakingEnergyMinDuringSpeaking: anchorHost.finalSpeakingEnergyMinDuringSpeaking
    readonly property real finalSpeakingEnergyMaxDuringSpeaking: anchorHost.finalSpeakingEnergyMaxDuringSpeaking
    readonly property bool envelopeTimelineReadyAtPlaybackStart: anchorHost.envelopeTimelineReadyAtPlaybackStart
    readonly property string chosenL06VisualizerStrategy: anchorHost.visualizerSourceStrategy
    readonly property string ghostTone: resolveGhostTone()
    readonly property string ghostToneSource: resolveGhostToneSource()
    readonly property string voiceAvailabilityState: resolveVoiceAvailabilityState()
    readonly property bool voiceOfflineDoesNotMakeGhostToneUnavailable: root.voiceAvailabilityState === "available"
        || root.ghostTone !== "unavailable"
        || root.ghostToneSource !== "voice_state"
    readonly property int visibleCardCount: Math.min(2, contextCards ? contextCards.length : 0)
    readonly property bool stormforgeFogFallbackRequested: fogBool("enabled", false)
        && !root.stormforgeFogDisabledDuringSpeech
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

    function valueBool(value) {
        if (value === true)
            return true
        if (value === false || value === undefined || value === null)
            return false
        var text = String(value).toLowerCase()
        return text === "true" || text === "1" || text === "yes" || text === "on"
    }

    function hasWord(text, word) {
        var normalized = " " + valueText(text).toLowerCase().replace(/[^a-z0-9_]+/g, " ") + " "
        return normalized.indexOf(" " + word + " ") >= 0
    }

    function toneFromText(value) {
        var text = valueText(value).toLowerCase()
        if (text.length <= 0)
            return ""
        if (text.indexOf("unavailable") >= 0
                || text.indexOf("disabled") >= 0
                || text.indexOf("offline") >= 0
                || text.indexOf("interrupted") >= 0)
            return "unavailable"
        if (text.indexOf("failed") >= 0
                || text.indexOf("failure") >= 0
                || text.indexOf("error") >= 0)
            return "failed"
        if (text.indexOf("blocked") >= 0
                || text.indexOf("warning") >= 0
                || text.indexOf("denied") >= 0
                || text.indexOf("held") >= 0
                || hasWord(text, "hold"))
            return "blocked"
        if (text.indexOf("approval") >= 0
                || text.indexOf("permission") >= 0
                || text.indexOf("trust_pending") >= 0
                || text.indexOf("pending approval") >= 0
                || text.indexOf("confirmation") >= 0)
            return "approval_required"
        if (text.indexOf("speaking") >= 0
                || text.indexOf("playback_active") >= 0
                || text.indexOf("playing") >= 0)
            return "speaking"
        if (text.indexOf("capturing") >= 0 || text.indexOf("capture_active") >= 0)
            return "capturing"
        if (text.indexOf("listening") >= 0)
            return "listening"
        if (text.indexOf("transcribing") >= 0)
            return "transcribing"
        if (text.indexOf("executing") >= 0
                || text.indexOf("execution") >= 0
                || text.indexOf("acting") >= 0
                || text.indexOf("running") >= 0
                || text.indexOf("in_progress") >= 0)
            return "acting"
        if (text.indexOf("thinking") >= 0
                || text.indexOf("routing") >= 0
                || text.indexOf("planning") >= 0
                || text.indexOf("planned") >= 0
                || text.indexOf("processing") >= 0
                || text.indexOf("synthesizing") >= 0
                || text.indexOf("preparing") >= 0
                || text.indexOf("requested") >= 0)
            return "thinking"
        if (text.indexOf("ghost_ready") >= 0
                || text.indexOf("signal_acquired") >= 0
                || text.indexOf("wake") >= 0)
            return "wake_detected"
        if (text.indexOf("ready") >= 0)
            return "ready"
        if (text.indexOf("mock") >= 0 || text.indexOf("dev") >= 0)
            return "mock_dev"
        if (text.indexOf("idle") >= 0)
            return "idle"
        return ""
    }

    function voiceOfflineText(value) {
        var text = valueText(value).toLowerCase().replace(/-/g, "_")
        return text.indexOf("voice_unavailable") >= 0
            || text.indexOf("voice_offline") >= 0
            || text.indexOf("capture_disabled") >= 0
            || text.indexOf("capture_unavailable") >= 0
            || text.indexOf("provider_unavailable") >= 0
            || text.indexOf("dev_capture_not_allowed") >= 0
            || text.indexOf("offline") >= 0
            || text.indexOf("unavailable") >= 0
            || text.indexOf("disabled") >= 0
    }

    function cardText(card) {
        if (!card)
            return ""
        return valueText(card.title || "")
            + " "
            + valueText(card.body || "")
            + " "
            + valueText(card.summary || "")
            + " "
            + valueText(card.subtitle || "")
    }

    function isVoiceAvailabilityCard(card) {
        if (!card)
            return false
        var text = (cardText(card)
            + " "
            + valueText(card.resultState || card.state || card.status || card.routeState)).toLowerCase()
        var voiceRelated = text.indexOf("voice") >= 0
            || text.indexOf("capture disabled") >= 0
            || text.indexOf("capture unavailable") >= 0
            || text.indexOf("capture offline") >= 0
        return voiceRelated && voiceOfflineText(text)
    }

    function isLifecycleAdvisoryCard(card) {
        if (!card)
            return false
        var text = (cardText(card)
            + " "
            + valueText(card.resultState || card.state || card.status || card.routeState)).toLowerCase()
        return isLifecycleAdvisoryText(text)
    }

    function routeInspectorText(inspector) {
        if (!inspector)
            return ""
        return valueText(inspector.routeState || inspector.state || inspector.status || inspector.resultState)
            + " "
            + valueText(inspector.statusLabel || inspector.selectedRouteLabel || inspector.routeLabel)
            + " "
            + valueText(inspector.family || inspector.stage || inspector.reason)
            + " "
            + valueText(inspector.title || inspector.subtitle || inspector.summary || inspector.body)
    }

    function isLifecycleAdvisoryText(value) {
        var text = valueText(value).toLowerCase()
        return text.indexOf("lifecycle hold") >= 0
            || text.indexOf("install posture changed") >= 0
            || text.indexOf("install-mode boundary") >= 0
            || text.indexOf("install boundary") >= 0
            || text.indexOf("review lifecycle boundaries") >= 0
            || text.indexOf("held at boundary") >= 0
            || text.indexOf("core hold") >= 0
    }

    function isLifecycleAdvisoryInspector(inspector) {
        return inspector && isLifecycleAdvisoryText(routeInspectorText(inspector))
    }

    function hasLifecycleAdvisoryCard(cards) {
        if (!cards)
            return false
        for (var index = 0; index < cards.length; ++index) {
            if (isLifecycleAdvisoryCard(cards[index]))
                return true
        }
        return false
    }

    function hasLifecycleAdvisoryContext() {
        return isLifecycleAdvisoryText(root.statusLine)
            || isLifecycleAdvisoryCard(root.primaryCard)
            || isLifecycleAdvisoryInspector(root.routeInspector)
            || hasLifecycleAdvisoryCard(root.contextCards)
    }

    function toneFromCard(card) {
        if (!card)
            return ""
        var state = valueText(card.resultState || card.state || card.status || card.routeState)
        var stateTone = toneFromText(state)
        if (stateTone === "unavailable" && isVoiceAvailabilityCard(card))
            return ""
        if (stateTone === "blocked" && isLifecycleAdvisoryCard(card))
            return ""
        if (stateTone.length > 0)
            return stateTone
        var cardTone = toneFromText(cardText(card))
        if (cardTone === "unavailable" && isVoiceAvailabilityCard(card))
            return ""
        if (cardTone === "blocked" && isLifecycleAdvisoryCard(card))
            return ""
        return cardTone
    }

    function toneFromRouteInspector(inspector) {
        if (!inspector)
            return ""
        var tone = toneFromText(routeInspectorText(inspector))
        if (tone === "blocked" && isLifecycleAdvisoryInspector(inspector))
            return ""
        return tone
    }

    function toneFromCards(cards) {
        if (!cards)
            return ""
        for (var index = 0; index < cards.length; ++index) {
            var tone = toneFromCard(cards[index])
            if (tone.length > 0)
                return tone
        }
        return ""
    }

    function toneFromActions(actions) {
        if (!actions)
            return ""
        for (var index = 0; index < actions.length; ++index) {
            var action = actions[index]
            if (!action)
                continue
            var tone = toneFromText(
                valueText(action.state || action.status || action.resultState)
                + " "
                + valueText(action.label || action.title || action.text)
            )
            if (tone.length > 0)
                return tone
        }
        return ""
    }

    function voiceSupportsSpeakingFor(state) {
        if (!state)
            return false
        var playback = valueText(
            state.authoritativePlaybackStatus !== undefined && state.authoritativePlaybackStatus !== null
                ? state.authoritativePlaybackStatus
                : (state.activePlaybackStatus !== undefined && state.activePlaybackStatus !== null
                    ? state.activePlaybackStatus
                    : state.active_playback_status)
        ).toLowerCase()
        var authoritative = valueText(state.authoritativeVoiceStateVersion).toUpperCase() === "AR6"
        if (authoritative
                && (playback === "completed"
                    || playback === "failed"
                    || playback === "stopped"
                    || playback === "cancelled"
                    || playback === "unavailable"
                    || playback === "idle"))
            return false
        return valueBool(state.authoritativeVoiceVisualActive)
            || valueBool(state.voice_visual_active)
            || state.speaking_visual_active === true
            || playback === "playing"
            || playback === "active"
            || playback === "prerolling"
            || playback === "started"
    }

    function voiceSupportsSpeaking() {
        return voiceSupportsSpeakingFor(root.mergedVoiceVisualState())
    }

    function toneFromVoice() {
        var state = root.visualVoiceState
        if (!state)
            return ""
        var playback = valueText(state.active_playback_status).toLowerCase()
        if (playback === "muted" || playback === "interrupted")
            return ""
        if (voiceSupportsSpeaking())
            return "speaking"
        var voiceTone = toneFromText(
            valueText(state.voice_current_phase)
            + " "
            + valueText(state.voice_anchor_state)
        )
        return voiceTone === "unavailable" ? "" : voiceTone
    }

    function toneFromAssistantState() {
        var tone = toneFromText(root.assistantState)
        if (tone === "blocked" && hasLifecycleAdvisoryContext())
            return ""
        return tone
    }

    function resolveVoiceAvailabilityState() {
        var state = root.visualVoiceState
        if (!state)
            return "available"
        var reason = valueText(state.unavailable_reason || state.capture_unavailable_reason)
        if (reason.length > 0 && voiceOfflineText(reason))
            return reason.toLowerCase().replace(/-/g, "_")
        if (state.voice_available === false || state.available === false)
            return "offline"
        var phase = valueText(state.voice_current_phase)
        var anchor = valueText(state.voice_anchor_state)
        if (voiceOfflineText(phase + " " + anchor))
            return "offline"
        return "available"
    }

    function toneCandidate(tone, source) {
        return {"tone": tone, "source": source}
    }

    function pickCandidate(candidates, tones) {
        for (var toneIndex = 0; toneIndex < tones.length; ++toneIndex) {
            for (var index = 0; index < candidates.length; ++index) {
                if (candidates[index].tone === tones[toneIndex])
                    return candidates[index]
            }
        }
        return toneCandidate("", "")
    }

    function resolveGhostTonePair() {
        var candidates = [
            toneCandidate(toneFromCard(root.primaryCard), "card_state"),
            toneCandidate(toneFromRouteInspector(root.routeInspector), "route_or_assistant_state"),
            toneCandidate(toneFromActions(root.actionStrip), "action_state"),
            toneCandidate(toneFromCards(root.contextCards), "card_state"),
            toneCandidate(toneFromAssistantState(), "route_or_assistant_state"),
            toneCandidate(toneFromVoice(), "voice_state")
        ]
        var prompt = pickCandidate(candidates, ["unavailable", "failed", "blocked", "approval_required"])
        if (prompt.tone.length > 0)
            return prompt

        var speaking = pickCandidate(candidates, ["speaking"])
        if (speaking.tone.length > 0 && voiceSupportsSpeaking())
            return toneCandidate("speaking", "speaking_playback_state")

        var active = pickCandidate(candidates, [
            "listening",
            "capturing",
            "transcribing",
            "acting",
            "thinking",
            "wake_detected",
            "ready",
            "mock_dev",
            "idle"
        ])
        if (active.tone.length > 0)
            return active
        return toneCandidate("idle", "idle_fallback")
    }

    function resolveGhostTone() {
        return resolveGhostTonePair().tone
    }

    function resolveGhostToneSource() {
        return resolveGhostTonePair().source
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

    function voiceDiagnosticValue(key, fallback) {
        if (!root.stormforgeVoiceDiagnosticsConfig
                || root.stormforgeVoiceDiagnosticsConfig[key] === undefined
                || root.stormforgeVoiceDiagnosticsConfig[key] === null) {
            return fallback
        }
        return root.stormforgeVoiceDiagnosticsConfig[key]
    }

    function normalizeAnchorVisualizerMode(value) {
        var normalized = valueText(value).toLowerCase().replace(/[- ]/g, "_")
        if (normalized === "off"
                || normalized === "procedural"
                || normalized === "envelope_timeline"
                || normalized === "constant_test_wave")
            return normalized
        return "auto"
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

    function sampleVoiceEventRate(now) {
        if (root._voiceEventWindowStartedMs <= 0)
            root._voiceEventWindowStartedMs = now
        var elapsed = now - root._voiceEventWindowStartedMs
        if (elapsed < 1000)
            return
        var scale = 1000.0 / Math.max(1, elapsed)
        root.voiceEventRateDuringSpeaking = Math.round(root._voiceEventWindowCount * scale)
        root.visualVoiceStateApplyRateDuringSpeaking = Math.round(root._visualApplyWindowCount * scale)
        root._voiceEventWindowCount = 0
        root._visualApplyWindowCount = 0
        root._voiceEventWindowStartedMs = now
    }

    function applyPendingVoiceStateForVisualFrame(now) {
        if (root._appliedVoiceStateSerial !== root._pendingVoiceStateSerial) {
            root.visualVoiceState = root.pendingVoiceState || ({})
            root._appliedVoiceStateSerial = root._pendingVoiceStateSerial
            root.visualVoiceStateApplyCount += 1
            if (voiceSupportsSpeakingFor(root.visualVoiceState))
                root._visualApplyWindowCount += 1
            root.visualVoiceStateLastAppliedMs = now
        }
        root.sampleVoiceEventRate(now)
    }

    function mergedVoiceVisualState() {
        var merged = {}
        var base = root.visualVoiceState || ({})
        var visual = root.voiceVisualState || ({})
        for (var baseKey in base)
            merged[baseKey] = base[baseKey]
        for (var visualKey in visual)
            merged[visualKey] = visual[visualKey]
        var baseSource = valueText(
            base.voice_visual_source !== undefined && base.voice_visual_source !== null
                ? base.voice_visual_source
                : base.voice_visual_energy_source
        )
        var visualSource = valueText(
            visual.voice_visual_source !== undefined && visual.voice_visual_source !== null
                ? visual.voice_visual_source
                : visual.voice_visual_energy_source
        )
        var baseEnergy = Number(base.voice_visual_energy || 0)
        var visualEnergy = Number(visual.voice_visual_energy || 0)
        var visualActive = valueBool(visual.voice_visual_active)
        var visualAuthoritative = valueText(visual.authoritativeVoiceStateVersion).toUpperCase() === "AR6"
        var visualPlayback = valueText(
            visual.authoritativePlaybackStatus !== undefined && visual.authoritativePlaybackStatus !== null
                ? visual.authoritativePlaybackStatus
                : (visual.activePlaybackStatus !== undefined && visual.activePlaybackStatus !== null
                    ? visual.activePlaybackStatus
                    : visual.active_playback_status)
        ).toLowerCase()
        var visualTerminal = visualAuthoritative
            && (visualPlayback === "completed"
                || visualPlayback === "failed"
                || visualPlayback === "stopped"
                || visualPlayback === "cancelled"
                || visualPlayback === "unavailable"
                || visualPlayback === "idle")
        var baseHasPcmSignal = baseSource === "pcm_stream_meter"
            && (valueBool(base.voice_visual_active)
                || valueBool(base.voice_visual_available)
                || (isFinite(baseEnergy) && baseEnergy > 0.0001))
        var visualPcmLooksStale = visualSource === "pcm_stream_meter"
            && !visualActive
            && (!isFinite(visualEnergy) || visualEnergy <= 0.0001)
        if (!visualTerminal && baseHasPcmSignal && (visualSource !== "pcm_stream_meter" || visualPcmLooksStale)) {
            var scalarKeys = [
                "playback_id",
                "voice_visual_active",
                "voice_visual_available",
                "voice_visual_energy",
                "voice_visual_source",
                "voice_visual_energy_source",
                "voice_visual_playback_id",
                "voice_visual_latest_age_ms",
                "voice_visual_sample_rate_hz",
                "voice_visual_started_at_ms",
                "voice_visual_disabled_reason",
                "payload_time_ms",
                "payload_wall_time_ms",
                "meter_time_ms",
                "meter_wall_time_ms",
                "authoritativeVoiceStateVersion",
                "activePlaybackId",
                "activePlaybackStatus",
                "authoritativePlaybackId",
                "authoritativePlaybackStatus",
                "authoritativeVoiceVisualActive",
                "authoritativeVoiceVisualEnergy",
                "authoritativeStateSequence",
                "authoritativeStateSource",
                "lastAcceptedUpdateSource",
                "lastIgnoredUpdateSource",
                "staleBroadSnapshotIgnored",
                "staleBroadSnapshotIgnoredCount",
                "hotPathAcceptedCount",
                "terminalEventAcceptedCount",
                "playbackIdSwitchCount",
                "playbackIdMismatchIgnoredCount",
                "voiceVisualActiveFlapCount",
                "speakingEnteredReason",
                "speakingExitedReason",
                "releaseDeadlineMs",
                "releaseTailMs"
            ]
            for (var keyIndex = 0; keyIndex < scalarKeys.length; ++keyIndex) {
                var scalarKey = scalarKeys[keyIndex]
                if (base[scalarKey] !== undefined && base[scalarKey] !== null)
                    merged[scalarKey] = base[scalarKey]
            }
        }
        return merged
    }

    function shouldEmitProductionVoiceDiagnostic() {
        if (typeof stormhelmBridge === "undefined" || !stormhelmBridge)
            return false
        if (!stormhelmBridge.voiceReactiveDiagnosticsEnabled)
            return false
        return root.visualVoiceSpeakingActive
            || anchorHost.qmlVoiceVisualActive
            || anchorHost.qmlFinalSpeakingEnergy > 0.001
            || valueBool(root.voiceVisualState.voice_visual_active)
            || valueText(root.voiceVisualState.active_playback_status).length > 0
            || valueText(root.visualVoiceState.active_playback_status).length > 0
    }

    function normalizeAnchorRenderer(value) {
        var normalized = valueText(value || "legacy_blob_reference").toLowerCase().replace(/[- ]/g, "_")
        if (normalized === "legacy_blob" || normalized === "legacy_blob_reference")
            return "legacy_blob_reference"
        if (normalized === "legacy_blob_fast" || normalized === "legacy_blob_fast_candidate")
            return "legacy_blob_fast_candidate"
        if (normalized === "legacy_blob_qsg" || normalized === "legacy_blob_qsg_candidate")
            return "legacy_blob_qsg_candidate"
        if (normalized === "ar3_split")
            return "ar3_split"
        return "legacy_blob_reference"
    }

    function emitProductionVoiceDiagnostic(now) {
        if (!root.shouldEmitProductionVoiceDiagnostic())
            return
        if (root.productionQmlDiagnosticLastEmitMs > 0
                && now - root.productionQmlDiagnosticLastEmitMs < root.productionQmlDiagnosticMinIntervalMs)
            return
        if (root.productionQmlDiagnosticLastEmitMs > 0)
            root.productionQmlDiagnosticMaxGapMs = Math.max(
                root.productionQmlDiagnosticMaxGapMs,
                now - root.productionQmlDiagnosticLastEmitMs
            )
        root.productionQmlDiagnosticLastEmitMs = now
        root.productionQmlDiagnosticEmitCount += 1
        var authoritativeState = root.mergedVoiceVisualState()
        stormhelmBridge.recordVoiceReactiveQmlDiagnostic({
            "qml_receive_time_ms": now,
            "qmlReceivedVoiceVisualEnergy": anchorHost.qmlReceivedVoiceVisualEnergy,
            "qmlReceivedVoiceVisualActive": anchorHost.qmlVoiceVisualActive,
            "qmlReceivedVoiceVisualSource": anchorHost.qmlReceivedVoiceVisualSource,
            "qmlReceivedPlaybackId": anchorHost.qmlReceivedPlaybackId,
            "qmlReceivedEnergyAgeMs": anchorHost.qmlEnergySampleAgeMs,
            "authoritativeVoiceStateVersion": valueText(authoritativeState.authoritativeVoiceStateVersion),
            "activePlaybackId": valueText(authoritativeState.activePlaybackId),
            "activePlaybackStatus": valueText(authoritativeState.activePlaybackStatus),
            "authoritativePlaybackId": valueText(authoritativeState.authoritativePlaybackId),
            "authoritativePlaybackStatus": valueText(authoritativeState.authoritativePlaybackStatus),
            "authoritativeVoiceVisualActive": valueBool(authoritativeState.authoritativeVoiceVisualActive),
            "authoritativeVoiceVisualEnergy": Number(authoritativeState.authoritativeVoiceVisualEnergy || 0),
            "authoritativeStateSequence": Number(authoritativeState.authoritativeStateSequence || 0),
            "authoritativeStateSource": valueText(authoritativeState.authoritativeStateSource),
            "lastAcceptedUpdateSource": valueText(authoritativeState.lastAcceptedUpdateSource),
            "lastIgnoredUpdateSource": valueText(authoritativeState.lastIgnoredUpdateSource),
            "staleBroadSnapshotIgnored": valueBool(authoritativeState.staleBroadSnapshotIgnored),
            "staleBroadSnapshotIgnoredCount": Number(authoritativeState.staleBroadSnapshotIgnoredCount || 0),
            "hotPathAcceptedCount": Number(authoritativeState.hotPathAcceptedCount || 0),
            "terminalEventAcceptedCount": Number(authoritativeState.terminalEventAcceptedCount || 0),
            "playbackIdSwitchCount": Number(authoritativeState.playbackIdSwitchCount || 0),
            "playbackIdMismatchIgnoredCount": Number(authoritativeState.playbackIdMismatchIgnoredCount || 0),
            "voiceVisualActiveFlapCount": Number(authoritativeState.voiceVisualActiveFlapCount || 0),
            "qml_update_rate_hz": root.visualVoiceStateApplyRateDuringSpeaking,
            "qml_latency_from_bridge_ms": Math.max(0, now - root.visualVoiceStateLastAppliedMs),
            "visualVoiceStateApplyCount": root.visualVoiceStateApplyCount,
            "voiceEventCountDuringSpeaking": root.voiceEventCountDuringSpeaking,
            "targetVoiceVisualEnergy": anchorHost.targetVoiceVisualEnergy,
            "smoothedVoiceVisualEnergy": anchorHost.smoothedVoiceVisualEnergy,
            "finalSpeakingEnergy": anchorHost.qmlFinalSpeakingEnergy,
            "speakingEnergyAttackVersion": anchorHost.speakingEnergyAttackVersion,
            "voiceVisualEnergy": Number(authoritativeState.authoritativeVoiceVisualEnergy || anchorHost.qmlReceivedVoiceVisualEnergy || 0),
            "startupLimiterActive": anchorHost.startupLimiterActive,
            "startupBoostActive": anchorHost.startupBoostActive,
            "startupBoostAmount": anchorHost.startupBoostAmount,
            "earlySpeechOvershootDetected": anchorHost.earlySpeechOvershootDetected,
            "lateSpeechCompressionDetected": anchorHost.lateSpeechCompressionDetected,
            "speakingDynamicsPhase": anchorHost.speakingDynamicsPhase,
            "speakingDynamicsConfidence": anchorHost.speakingDynamicsConfidence,
            "energyRecentMin": anchorHost.energyRecentMin,
            "energyRecentMax": anchorHost.energyRecentMax,
            "energyDynamicRange": anchorHost.energyDynamicRange,
            "adaptiveGain": anchorHost.adaptiveGain,
            "finalSpeakingEnergyGain": anchorHost.finalSpeakingEnergyGain,
            "finalSpeakingEnergyClampReason": anchorHost.finalSpeakingEnergyClampReason,
            "finalEnergyCompressionRatio": anchorHost.finalEnergyCompressionRatio,
            "effectiveAnchorRenderer": anchorHost.effectiveAnchorRenderer,
            "anchorRendererArchitectureVersion": anchorHost.anchorRendererArchitectureVersion,
            "anchorRendererArchitecture": anchorHost.anchorRendererArchitecture,
            "staticFrameLayerEnabled": anchorHost.staticFrameLayerEnabled,
            "dynamicCoreLayerEnabled": anchorHost.dynamicCoreLayerEnabled,
            "fullFrameVoiceCanvasRepaintDisabled": anchorHost.fullFrameVoiceCanvasRepaintDisabled,
            "staticFramePaintCount": anchorHost.staticFramePaintCount,
            "staticFrameRequestPaintCount": anchorHost.staticFrameRequestPaintCount,
            "staticFrameLastPaintTimeMs": anchorHost.staticFrameLastPaintTimeMs,
            "dynamicCorePaintCount": anchorHost.dynamicCorePaintCount,
            "dynamicCoreRequestPaintCount": anchorHost.dynamicCoreRequestPaintCount,
            "dynamicCoreLastPaintTimeMs": anchorHost.dynamicCoreLastPaintTimeMs,
            "blobScaleDrive": anchorHost.blobScaleDrive,
            "blobDeformationDrive": anchorHost.blobDeformationDrive,
            "blobRadiusScale": anchorHost.blobRadiusScale,
            "radianceDrive": anchorHost.radianceDrive,
            "ringDrive": anchorHost.ringDrive,
            "visualAmplitudeCompressionRatio": anchorHost.visualAmplitudeCompressionRatio,
            "visualAmplitudeLatencyMs": anchorHost.visualAmplitudeLatencyMs,
            "finalSpeakingEnergyUpdatedAtMs": anchorHost.finalSpeakingEnergyUpdatedAtMs,
            "voiceVisualTargetUpdatedAtMs": anchorHost.voiceVisualTargetUpdatedAtMs,
            "voiceVisualTargetAgeMs": anchorHost.voiceVisualTargetAgeMs,
            "voiceVisualFirstTrueAtMs": anchorHost.voiceVisualFirstTrueAtMs,
            "qmlFirstVoiceVisualTrueAtMs": anchorHost.qmlFirstVoiceVisualTrueAtMs,
            "speakingStateEnteredAtMs": anchorHost.speakingStateEnteredAtMs,
            "anchorSpeakingStartDelayMs": anchorHost.anchorSpeakingStartDelayMs,
            "anchorSpeakingVisualActive": anchorHost.anchorSpeakingVisualActive,
            "anchorCurrentVisualState": anchorHost.anchorCurrentVisualState,
            "anchorMotionMode": anchorHost.anchorMotionMode,
            "anchorPaintCount": anchorHost.qmlAnchorPaintCount,
            "anchorRequestPaintCount": anchorHost.qmlAnchorRequestPaintCount,
            "anchorLocalSpeakingFrameTickCount": anchorHost.localSpeakingFrameTickCount,
            "anchorLastPaintTimeMs": anchorHost.qmlLastPaintTimeMs,
            "anchorFrameDeltaMs": anchorHost.anchorFrameDeltaMs,
            "localSpeakingFrameClockActive": anchorHost.localSpeakingFrameClockActive,
            "anchorEnergyToPaintLatencyMs": anchorHost.anchorEnergyToPaintLatencyMs,
            "anchorStaleEnergyReason": anchorHost.anchorStaleEnergyReason,
            "stateLatchReason": anchorHost.stateLatchReason,
            "latchBugReason": anchorHost.latchBugReason,
            "anchorReleaseReason": anchorHost.anchorReleaseReason,
            "anchorSpeakingEnteredAtMs": anchorHost.anchorSpeakingEnteredAtMs,
            "anchorSpeakingExitedAtMs": anchorHost.anchorSpeakingExitedAtMs,
            "currentAnchorPlaybackId": anchorHost.currentAnchorPlaybackId,
            "lastAnchorPlaybackId": anchorHost.lastAnchorPlaybackId,
            "anchorPlaybackIdSwitchCount": anchorHost.anchorPlaybackIdSwitchCount,
            "anchorAcceptedPlaybackId": anchorHost.anchorAcceptedPlaybackId,
            "anchorIgnoredPlaybackId": anchorHost.anchorIgnoredPlaybackId,
            "anchorSpeakingEntryPlaybackId": anchorHost.anchorSpeakingEntryPlaybackId,
            "anchorSpeakingExitPlaybackId": anchorHost.anchorSpeakingExitPlaybackId,
            "anchorSpeakingEntryReason": anchorHost.anchorSpeakingEntryReason,
            "anchorSpeakingExitReason": anchorHost.anchorSpeakingExitReason,
            "qsgRendererPlaybackId": anchorHost.qsgRendererPlaybackId,
            "qsgRendererReceivedEnergyForPlaybackId": anchorHost.qsgRendererReceivedEnergyForPlaybackId,
            "qsgRendererPaintedPlaybackId": anchorHost.qsgRendererPaintedPlaybackId,
            "qsgReflectionParityVersion": anchorHost.qsgReflectionParityVersion,
            "qsgReflectionShape": anchorHost.qsgReflectionShape,
            "qsgReflectionRoundedRectDisabled": anchorHost.qsgReflectionRoundedRectDisabled,
            "qsgReflectionUsesLegacyGeometry": anchorHost.qsgReflectionUsesLegacyGeometry,
            "qsgReflectionAnimated": anchorHost.qsgReflectionAnimated,
            "qsgReflectionOffsetX": anchorHost.qsgReflectionOffsetX,
            "qsgReflectionOffsetY": anchorHost.qsgReflectionOffsetY,
            "qsgReflectionOpacity": anchorHost.qsgReflectionOpacity,
            "qsgReflectionSoftness": anchorHost.qsgReflectionSoftness,
            "qsgReflectionClipInsideBlob": anchorHost.qsgReflectionClipInsideBlob,
            "qsgBlobEdgeFeatherVersion": anchorHost.qsgBlobEdgeFeatherVersion,
            "qsgBlobEdgeFeatherEnabled": anchorHost.qsgBlobEdgeFeatherEnabled,
            "qsgBlobEdgeFeatherMatchesLegacySoftness": anchorHost.qsgBlobEdgeFeatherMatchesLegacySoftness,
            "qsgBlobEdgeFeatherOpacity": anchorHost.qsgBlobEdgeFeatherOpacity,
            "finalSpeakingEnergyPlaybackId": anchorHost.finalSpeakingEnergyPlaybackId,
            "blobDrivePlaybackId": anchorHost.blobDrivePlaybackId,
            "sharedAnimationClockFps": stormforgeAnimationClock.measuredFps,
            "sharedAnimationClockFrameCounter": stormforgeAnimationClock.frameCounter,
            "sharedAnimationClockLongFrameCount": stormforgeAnimationClock.longFrameCount,
            "frameSwappedFps": 0,
            "maxFrameGapMs": stormforgeAnimationClock.maxFrameGapMs,
            "longFramesOver33Ms": stormforgeAnimationClock.longFrameCount,
            "longFramesOver50Ms": stormforgeAnimationClock.longFrameCount,
            "longFramesOver100Ms": stormforgeAnimationClock.longFrameCount,
            "sharedAnimationClockFpsDuringSpeaking": root.visualVoiceSpeakingActive ? stormforgeAnimationClock.measuredFps : 0,
            "anchorPaintFps": root.anchorPaintFpsDuringSpeaking,
            "anchorRequestPaintFps": root.anchorRequestPaintFpsDuringSpeaking,
            "dynamicCorePaintFps": root.dynamicCorePaintFpsDuringSpeaking,
            "fogTickFps": root.fogTickFpsDuringSpeaking,
            "fog_active": atmosphereSlot.fogActive,
            "playback_status": valueText(authoritativeState.active_playback_status),
            "voice_visual_active": valueBool(authoritativeState.voice_visual_active),
            "speaking_visual_active": root.visualVoiceSpeakingActive,
            "raw_audio_present": false
        })
    }

    onVoiceStateChanged: {
        var now = Date.now()
        root.pendingVoiceState = root.voiceState || ({})
        root._pendingVoiceStateSerial += 1
        root.lastVoiceEventAtMs = now
        if (voiceSupportsSpeakingFor(root.pendingVoiceState)) {
            root.voiceEventCountDuringSpeaking += 1
            root._voiceEventWindowCount += 1
        }
        if (!root.sharedAnimationClockEnabled)
            root.applyPendingVoiceStateForVisualFrame(now)
    }

    onVoiceVisualStateChanged: {
        var now = Date.now()
        if (voiceSupportsSpeakingFor(root.voiceVisualState)) {
            root.voiceEventCountDuringSpeaking += 1
            root._voiceEventWindowCount += 1
        }
        root.lastVoiceEventAtMs = now
    }

    Component.onCompleted: {
        var now = Date.now()
        root.pendingVoiceState = root.voiceState || ({})
        root._pendingVoiceStateSerial += 1
        root.applyPendingVoiceStateForVisualFrame(now)
    }

    StormforgeAnimationClock {
        id: stormforgeAnimationClock
        objectName: "stormforgeAnimationClock"
        running: root.sharedAnimationClockEnabled && root.visible
        speakingActive: root.visualVoiceSpeakingActive
        onFrameTick: function(animationTimeMs, deltaTimeMs, wallTimeMs, frameCounter) {
            root.applyPendingVoiceStateForVisualFrame(wallTimeMs)
            root.emitProductionVoiceDiagnostic(wallTimeMs)
        }
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
            width: Math.min(Math.max(parent.width * 0.23, 248), 320)
            height: width + sf.space6
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(parent.height * 0.16, parent.height * 0.36 - height * 0.5)
            voiceState: root.visualVoiceState
            voiceVisualState: root.voiceVisualState
            stateTone: root.ghostTone
            stateSource: root.ghostToneSource
            anchorCoreAvailable: root.anchorCoreAvailable
            anchorCoreSource: root.anchorCoreSource
            visualizerDiagnosticMode: root.anchorVisualizerMode
            anchorRenderer: root.anchorRenderer
            renderLoopDiagnosticsEnabled: root.anchorVisualizerMode !== "auto"
            visualClockAnimationTimeMs: stormforgeAnimationClock.animationTimeMs
            visualClockDeltaMs: stormforgeAnimationClock.deltaTimeMs
            visualClockWallTimeMs: stormforgeAnimationClock.wallTimeMs
            visualClockFrameCounter: stormforgeAnimationClock.frameCounter
            visualClockMeasuredFps: stormforgeAnimationClock.measuredFps
            visualClockLongFrameCount: stormforgeAnimationClock.longFrameCount
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
            captureActive: root.captureActive
            draftText: root.draftText
            hintText: root.hintText
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
            visualClockAnimationTimeSec: stormforgeAnimationClock.animationTimeSec
            visualClockDeltaMs: stormforgeAnimationClock.deltaTimeMs
            visualClockFrameCounter: stormforgeAnimationClock.frameCounter
            visualClockMeasuredFps: stormforgeAnimationClock.measuredFps
            speakingActive: root.visualVoiceSpeakingActive
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
