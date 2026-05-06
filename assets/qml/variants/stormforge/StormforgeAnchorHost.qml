import QtQuick 2.15

Item {
    id: root

    property var voiceState: ({})
    property string assistantState: "idle"
    property string stateTone: "idle"
    property string stateSource: ""
    property string label: ""
    property string sublabel: ""
    property real intensity: -1
    property bool active: true
    property bool disabled: false
    property bool warning: false
    property real speakingLevel: -1
    property real audioLevel: 0
    property real progress: 0
    property real pulseStrength: 0
    property bool compact: false
    property real visualClockAnimationTimeMs: -1
    property real visualClockDeltaMs: 0
    property real visualClockWallTimeMs: 0
    property int visualClockFrameCounter: 0
    property real visualClockMeasuredFps: 0
    property int visualClockLongFrameCount: 0
    property string visualizerDiagnosticMode: "auto"
    property string anchorRenderer: "legacy_blob_reference"
    property bool renderLoopDiagnosticsEnabled: false
    property bool anchorCoreAvailable: true
    property url anchorCoreSource: Qt.resolvedUrl("StormforgeAnchorCore.qml")
    property var voiceVisualState: ({})

    readonly property string componentRole: "stormforge_anchor_host"
    readonly property bool ownsAnchorPlacement: true
    readonly property bool ownsAnchorAnimation: false
    readonly property bool ownsAnchorIdentity: false
    readonly property string anchorHostMode: "core"
    readonly property bool finalAnchorImplemented: true
    readonly property alias resolvedState: anchorCore.resolvedState
    readonly property alias resolvedLabel: anchorCore.resolvedLabel
    readonly property alias resolvedSublabel: anchorCore.resolvedSublabel
    readonly property alias motionProfile: anchorCore.motionProfile
    readonly property alias animationRunning: anchorCore.animationRunning
    readonly property alias effectiveSpeakingLevel: anchorCore.effectiveSpeakingLevel
    readonly property alias audioReactiveSource: anchorCore.audioReactiveSource
    readonly property alias derivedAnchorVisualState: anchorCore.derivedAnchorVisualState
    readonly property alias anchorVisualStateSource: anchorCore.anchorVisualStateSource
    readonly property alias anchorStateBindingVersion: anchorCore.anchorStateBindingVersion
    readonly property alias statePrecedenceVersion: anchorCore.statePrecedenceVersion
    readonly property alias visualStateLatchVersion: anchorCore.visualStateLatchVersion
    readonly property alias rawDerivedVisualState: anchorCore.rawDerivedVisualState
    readonly property alias latchedVisualState: anchorCore.latchedVisualState
    readonly property alias stateLatchReason: anchorCore.stateLatchReason
    readonly property alias latchBugReason: anchorCore.latchBugReason
    readonly property alias rawSpeakingActive: anchorCore.rawSpeakingActive
    readonly property alias visualSpeakingActive: anchorCore.visualSpeakingActive
    readonly property alias speakingLatched: anchorCore.speakingLatched
    readonly property alias supportedVisualStates: anchorCore.supportedVisualStates
    readonly property alias neverVanishInvariantVersion: anchorCore.neverVanishInvariantVersion
    readonly property alias voiceAvailabilityState: anchorCore.voiceAvailabilityState
    readonly property alias voiceOfflineDoesNotHideAnchor: anchorCore.voiceOfflineDoesNotHideAnchor
    readonly property alias finalVisibilityFloorApplied: anchorCore.finalVisibilityFloorApplied
    readonly property alias finalAnchorVisible: anchorCore.finalAnchorVisible
    readonly property alias finalAnchorOpacityFloor: anchorCore.finalAnchorOpacityFloor
    readonly property alias finalBlobOpacity: anchorCore.finalBlobOpacity
    readonly property alias finalRingOpacity: anchorCore.finalRingOpacity
    readonly property alias finalCenterGlowOpacity: anchorCore.finalCenterGlowOpacity
    readonly property alias finalSignalPointOpacity: anchorCore.finalSignalPointOpacity
    readonly property alias finalBearingTickOpacity: anchorCore.finalBearingTickOpacity
    readonly property alias sharedVisualClockActive: anchorCore.sharedVisualClockActive
    readonly property alias localSpeakingFrameClockActive: anchorCore.localSpeakingFrameClockActive
    readonly property alias voiceVisualSyncVersion: anchorCore.voiceVisualSyncVersion
    readonly property alias audioReactiveUsesVisualClock: anchorCore.audioReactiveUsesVisualClock
    readonly property alias rawAudioEventsDoNotRequestPaint: anchorCore.rawAudioEventsDoNotRequestPaint
    readonly property alias visualClockFps: anchorCore.visualClockFps
    readonly property alias playbackEnvelopeVersion: anchorCore.playbackEnvelopeVersion
    readonly property alias playbackEnvelopeVisualDriveVersion: anchorCore.playbackEnvelopeVisualDriveVersion
    readonly property alias envelopeDynamicsVersion: anchorCore.envelopeDynamicsVersion
    readonly property alias sourceLatchVersion: anchorCore.sourceLatchVersion
    readonly property alias timelineVisualizerVersion: anchorCore.timelineVisualizerVersion
    readonly property alias envelopeBackedProceduralBaseEnabled: anchorCore.envelopeBackedProceduralBaseEnabled
    readonly property alias envelopeDrivesVisualDynamics: anchorCore.envelopeDrivesVisualDynamics
    readonly property alias speakingPlateauSuppressionEnabled: anchorCore.speakingPlateauSuppressionEnabled
    readonly property alias centerUniformSpeakingScaleDisabled: anchorCore.centerUniformSpeakingScaleDisabled
    readonly property alias sourceFlapGuardEnabled: anchorCore.sourceFlapGuardEnabled
    readonly property alias visualizerSourceSwitchingDisabled: anchorCore.visualizerSourceSwitchingDisabled
    readonly property alias playbackEnvelopeRequiresTimebaseAlignment: anchorCore.playbackEnvelopeRequiresTimebaseAlignment
    readonly property alias proceduralFallbackContinuityEnabled: anchorCore.proceduralFallbackContinuityEnabled
    readonly property alias qmlPlaybackEnvelopeSupported: anchorCore.qmlPlaybackEnvelopeSupported
    readonly property alias qmlPlaybackEnvelopeAvailable: anchorCore.qmlPlaybackEnvelopeAvailable
    readonly property alias qmlPlaybackEnvelopeUsable: anchorCore.qmlPlaybackEnvelopeUsable
    readonly property alias qmlPlaybackEnvelopeSource: anchorCore.qmlPlaybackEnvelopeSource
    readonly property alias qmlPlaybackEnvelopeEnergy: anchorCore.qmlPlaybackEnvelopeEnergy
    readonly property alias qmlPlaybackEnvelopeVisualDrive: anchorCore.qmlPlaybackEnvelopeVisualDrive
    readonly property alias qmlEnvelopeExpandedEnergy: anchorCore.qmlEnvelopeExpandedEnergy
    readonly property alias qmlEnvelopeDynamicRange: anchorCore.qmlEnvelopeDynamicRange
    readonly property alias envelopeRecentMin: anchorCore.envelopeRecentMin
    readonly property alias envelopeRecentMax: anchorCore.envelopeRecentMax
    readonly property alias envelopeDynamicRange: anchorCore.envelopeDynamicRange
    readonly property alias envelopeDynamicEnergy: anchorCore.envelopeDynamicEnergy
    readonly property alias envelopeExpandedEnergy: anchorCore.envelopeExpandedEnergy
    readonly property alias envelopeAdaptiveGain: anchorCore.envelopeAdaptiveGain
    readonly property alias envelopeTransientEnergy: anchorCore.envelopeTransientEnergy
    readonly property alias speakingBaseEnergy: anchorCore.speakingBaseEnergy
    readonly property alias proceduralCarrierEnergy: anchorCore.proceduralCarrierEnergy
    readonly property alias qmlPlaybackEnvelopeSampleCount: anchorCore.qmlPlaybackEnvelopeSampleCount
    readonly property alias qmlPlaybackEnvelopeSampleAgeMs: anchorCore.qmlPlaybackEnvelopeSampleAgeMs
    readonly property alias qmlEnvelopeTimelineAvailable: anchorCore.qmlEnvelopeTimelineAvailable
    readonly property alias qmlEnvelopeTimelineSampleCount: anchorCore.qmlEnvelopeTimelineSampleCount
    readonly property alias qmlPlaybackVisualTimeMs: anchorCore.qmlPlaybackVisualTimeMs
    readonly property alias qmlEnvelopeSampleTimeMs: anchorCore.qmlEnvelopeSampleTimeMs
    readonly property alias qmlEnvelopeInterpolationIndex: anchorCore.qmlEnvelopeInterpolationIndex
    readonly property alias qmlEnvelopeInterpolationAlpha: anchorCore.qmlEnvelopeInterpolationAlpha
    readonly property alias qmlEnvelopeTimeOffsetMs: anchorCore.qmlEnvelopeTimeOffsetMs
    readonly property alias qmlEnvelopeTimeOffsetAppliedMs: anchorCore.qmlEnvelopeTimeOffsetAppliedMs
    readonly property alias qmlEstimatedOutputLatencyMs: anchorCore.qmlEstimatedOutputLatencyMs
    readonly property alias envelopeSyncCalibrationVersion: anchorCore.envelopeSyncCalibrationVersion
    readonly property alias playbackEnvelopeVisualSyncCalibrationEnabled: anchorCore.playbackEnvelopeVisualSyncCalibrationEnabled
    readonly property alias envelopeSyncDebugShowSync: anchorCore.envelopeSyncDebugShowSync
    readonly property alias envelopeVisualOffsetMs: anchorCore.envelopeVisualOffsetMs
    readonly property alias qmlEnvelopeAlignmentMode: anchorCore.qmlEnvelopeAlignmentMode
    readonly property alias playbackEnvelopeTimebaseAligned: anchorCore.playbackEnvelopeTimebaseAligned
    readonly property alias playbackEnvelopeUsableReason: anchorCore.playbackEnvelopeUsableReason
    readonly property alias playbackEnvelopeStale: anchorCore.playbackEnvelopeStale
    readonly property alias speakingEnergySourceLatched: anchorCore.speakingEnergySourceLatched
    readonly property alias speakingEnergySourceCandidate: anchorCore.speakingEnergySourceCandidate
    readonly property alias speakingEnergySourceSwitchCount: anchorCore.speakingEnergySourceSwitchCount
    readonly property alias speakingEnergySourceLatchPlaybackId: anchorCore.speakingEnergySourceLatchPlaybackId
    readonly property alias visualizerSourceStrategy: anchorCore.visualizerSourceStrategy
    readonly property alias visualizerSourceLocked: anchorCore.visualizerSourceLocked
    readonly property alias visualizerSourcePlaybackId: anchorCore.visualizerSourcePlaybackId
    readonly property alias visualizerSourceSwitchCount: anchorCore.visualizerSourceSwitchCount
    readonly property alias visualizerSourceCandidate: anchorCore.visualizerSourceCandidate
    readonly property alias envelopeCrossfadeAlpha: anchorCore.envelopeCrossfadeAlpha
    readonly property alias envelopeFallbackActive: anchorCore.envelopeFallbackActive
    readonly property alias playbackEnvelopeFirstUsableAtMs: anchorCore.playbackEnvelopeFirstUsableAtMs
    readonly property alias qmlSpeakingVisualActive: anchorCore.qmlSpeakingVisualActive
    readonly property alias qmlProceduralFallbackActive: anchorCore.qmlProceduralFallbackActive
    readonly property alias qmlFinalSpeakingEnergy: anchorCore.qmlFinalSpeakingEnergy
    readonly property alias finalSpeakingEnergyUpdatedAtMs: anchorCore.finalSpeakingEnergyUpdatedAtMs
    readonly property alias qmlSpeakingEnergySource: anchorCore.qmlSpeakingEnergySource
    readonly property alias qmlReceivedVoiceVisualEnergy: anchorCore.qmlReceivedVoiceVisualEnergy
    readonly property alias qmlReceivedVoiceVisualSource: anchorCore.qmlReceivedVoiceVisualSource
    readonly property alias qmlReceivedPlaybackId: anchorCore.qmlReceivedPlaybackId
    readonly property alias qmlReceivedEnergyTimeMs: anchorCore.qmlReceivedEnergyTimeMs
    readonly property alias qmlSpeechEnergySource: anchorCore.qmlSpeechEnergySource
    readonly property alias qmlVoiceVisualActive: anchorCore.qmlVoiceVisualActive
    readonly property alias qmlEnergySampleAgeMs: anchorCore.qmlEnergySampleAgeMs
    readonly property alias qmlAnchorPaintCount: anchorCore.qmlAnchorPaintCount
    readonly property alias qmlAnchorRequestPaintCount: anchorCore.qmlAnchorRequestPaintCount
    readonly property alias localSpeakingFrameTickCount: anchorCore.localSpeakingFrameTickCount
    readonly property alias qmlLastPaintTimeMs: anchorCore.qmlLastPaintTimeMs
    readonly property alias qmlFrameTimeMs: anchorCore.qmlFrameTimeMs
    readonly property alias anchorSpeakingVisualActive: anchorCore.anchorSpeakingVisualActive
    readonly property alias anchorCurrentVisualState: anchorCore.anchorCurrentVisualState
    readonly property alias anchorMotionMode: anchorCore.anchorMotionMode
    readonly property alias anchorFrameDeltaMs: anchorCore.anchorFrameDeltaMs
    readonly property alias anchorEnergyToPaintLatencyMs: anchorCore.anchorEnergyToPaintLatencyMs
    readonly property alias anchorStaleEnergyReason: anchorCore.anchorStaleEnergyReason
    readonly property alias anchorReleaseReason: anchorCore.anchorReleaseReason
    readonly property alias anchorSpeakingEnteredAtMs: anchorCore.anchorSpeakingEnteredAtMs
    readonly property alias anchorSpeakingExitedAtMs: anchorCore.anchorSpeakingExitedAtMs
    readonly property alias currentAnchorPlaybackId: anchorCore.currentAnchorPlaybackId
    readonly property alias lastAnchorPlaybackId: anchorCore.lastAnchorPlaybackId
    readonly property alias anchorPlaybackIdSwitchCount: anchorCore.anchorPlaybackIdSwitchCount
    readonly property alias anchorAcceptedPlaybackId: anchorCore.anchorAcceptedPlaybackId
    readonly property alias anchorIgnoredPlaybackId: anchorCore.anchorIgnoredPlaybackId
    readonly property alias anchorSpeakingEntryPlaybackId: anchorCore.anchorSpeakingEntryPlaybackId
    readonly property alias anchorSpeakingExitPlaybackId: anchorCore.anchorSpeakingExitPlaybackId
    readonly property alias anchorSpeakingEntryReason: anchorCore.anchorSpeakingEntryReason
    readonly property alias anchorSpeakingExitReason: anchorCore.anchorSpeakingExitReason
    readonly property alias finalSpeakingEnergyPlaybackId: anchorCore.finalSpeakingEnergyPlaybackId
    readonly property alias blobDrivePlaybackId: anchorCore.blobDrivePlaybackId
    readonly property alias qmlAnchorReactiveChainVersion: anchorCore.qmlAnchorReactiveChainVersion
    readonly property alias targetVoiceVisualEnergy: anchorCore.targetVoiceVisualEnergy
    readonly property alias smoothedVoiceVisualEnergy: anchorCore.smoothedVoiceVisualEnergy
    readonly property alias speakingEnergyAttackVersion: anchorCore.speakingEnergyAttackVersion
    readonly property alias startupLimiterActive: anchorCore.startupLimiterActive
    readonly property alias startupBoostActive: anchorCore.startupBoostActive
    readonly property alias startupBoostAmount: anchorCore.startupBoostAmount
    readonly property alias earlySpeechOvershootDetected: anchorCore.earlySpeechOvershootDetected
    readonly property alias lateSpeechCompressionDetected: anchorCore.lateSpeechCompressionDetected
    readonly property alias speakingDynamicsPhase: anchorCore.speakingDynamicsPhase
    readonly property alias speakingDynamicsConfidence: anchorCore.speakingDynamicsConfidence
    readonly property alias energyRecentMin: anchorCore.energyRecentMin
    readonly property alias energyRecentMax: anchorCore.energyRecentMax
    readonly property alias energyDynamicRange: anchorCore.energyDynamicRange
    readonly property alias adaptiveGain: anchorCore.adaptiveGain
    readonly property alias finalSpeakingEnergyGain: anchorCore.finalSpeakingEnergyGain
    readonly property alias finalSpeakingEnergyClampReason: anchorCore.finalSpeakingEnergyClampReason
    readonly property alias finalEnergyCompressionRatio: anchorCore.finalEnergyCompressionRatio
    readonly property alias effectiveAnchorRenderer: anchorCore.effectiveAnchorRenderer
    readonly property alias anchorRendererArchitectureVersion: anchorCore.anchorRendererArchitectureVersion
    readonly property alias anchorRendererArchitecture: anchorCore.anchorRendererArchitecture
    readonly property alias staticFrameLayerEnabled: anchorCore.staticFrameLayerEnabled
    readonly property alias dynamicCoreLayerEnabled: anchorCore.dynamicCoreLayerEnabled
    readonly property alias fullFrameVoiceCanvasRepaintDisabled: anchorCore.fullFrameVoiceCanvasRepaintDisabled
    readonly property alias staticFramePaintCount: anchorCore.staticFramePaintCount
    readonly property alias staticFrameRequestPaintCount: anchorCore.staticFrameRequestPaintCount
    readonly property alias staticFrameLastPaintTimeMs: anchorCore.staticFrameLastPaintTimeMs
    readonly property alias dynamicCorePaintCount: anchorCore.dynamicCorePaintCount
    readonly property alias dynamicCoreRequestPaintCount: anchorCore.dynamicCoreRequestPaintCount
    readonly property alias dynamicCoreLastPaintTimeMs: anchorCore.dynamicCoreLastPaintTimeMs
    readonly property alias qsgRendererPlaybackId: anchorCore.qsgRendererPlaybackId
    readonly property alias qsgRendererReceivedEnergyForPlaybackId: anchorCore.qsgRendererReceivedEnergyForPlaybackId
    readonly property alias qsgRendererPaintedPlaybackId: anchorCore.qsgRendererPaintedPlaybackId
    readonly property alias qsgReflectionParityVersion: anchorCore.qsgReflectionParityVersion
    readonly property alias qsgReflectionShape: anchorCore.qsgReflectionShape
    readonly property alias qsgReflectionRoundedRectDisabled: anchorCore.qsgReflectionRoundedRectDisabled
    readonly property alias qsgReflectionUsesLegacyGeometry: anchorCore.qsgReflectionUsesLegacyGeometry
    readonly property alias qsgReflectionAnimated: anchorCore.qsgReflectionAnimated
    readonly property alias qsgReflectionOffsetX: anchorCore.qsgReflectionOffsetX
    readonly property alias qsgReflectionOffsetY: anchorCore.qsgReflectionOffsetY
    readonly property alias qsgReflectionOpacity: anchorCore.qsgReflectionOpacity
    readonly property alias qsgReflectionSoftness: anchorCore.qsgReflectionSoftness
    readonly property alias qsgReflectionClipInsideBlob: anchorCore.qsgReflectionClipInsideBlob
    readonly property alias qsgBlobEdgeFeatherVersion: anchorCore.qsgBlobEdgeFeatherVersion
    readonly property alias qsgBlobEdgeFeatherEnabled: anchorCore.qsgBlobEdgeFeatherEnabled
    readonly property alias qsgBlobEdgeFeatherMatchesLegacySoftness: anchorCore.qsgBlobEdgeFeatherMatchesLegacySoftness
    readonly property alias qsgBlobEdgeFeatherOpacity: anchorCore.qsgBlobEdgeFeatherOpacity
    readonly property alias blobScaleDrive: anchorCore.blobScaleDrive
    readonly property alias blobDeformationDrive: anchorCore.blobDeformationDrive
    readonly property alias blobRadiusScale: anchorCore.blobRadiusScale
    readonly property alias radianceDrive: anchorCore.radianceDrive
    readonly property alias ringDrive: anchorCore.ringDrive
    readonly property alias visualAmplitudeCompressionRatio: anchorCore.visualAmplitudeCompressionRatio
    readonly property alias visualAmplitudeLatencyMs: anchorCore.visualAmplitudeLatencyMs
    readonly property alias voiceVisualTargetUpdatedAtMs: anchorCore.voiceVisualTargetUpdatedAtMs
    readonly property alias voiceVisualTargetAgeMs: anchorCore.voiceVisualTargetAgeMs
    readonly property alias voiceVisualFirstTrueAtMs: anchorCore.voiceVisualFirstTrueAtMs
    readonly property alias qmlFirstVoiceVisualTrueAtMs: anchorCore.qmlFirstVoiceVisualTrueAtMs
    readonly property alias speakingStateEnteredAtMs: anchorCore.speakingStateEnteredAtMs
    readonly property alias anchorSpeakingStartDelayMs: anchorCore.anchorSpeakingStartDelayMs
    readonly property alias proceduralFallbackReason: anchorCore.proceduralFallbackReason
    readonly property alias envelopeUnavailableFallbackWorks: anchorCore.envelopeUnavailableFallbackWorks
    readonly property alias finalSpeakingEnergyNonZeroDuringFallback: anchorCore.finalSpeakingEnergyNonZeroDuringFallback
    readonly property alias anchorPaintCountPerSecond: anchorCore.anchorPaintCountPerSecond
    readonly property alias anchorRequestPaintCountPerSecond: anchorCore.anchorRequestPaintCountPerSecond
    readonly property alias speakingEnvelopeUpdateCountPerSecond: anchorCore.speakingEnvelopeUpdateCountPerSecond
    readonly property alias speakingVisualLatencyEstimateMs: anchorCore.speakingVisualLatencyEstimateMs
    readonly property alias liveVoiceIsolationVersion: anchorCore.liveVoiceIsolationVersion
    readonly property alias requestedAnchorVisualizerMode: anchorCore.requestedAnchorVisualizerMode
    readonly property alias effectiveAnchorVisualizerMode: anchorCore.effectiveAnchorVisualizerMode
    readonly property alias anchorVisualizerModeForced: anchorCore.anchorVisualizerModeForced
    readonly property alias forcedVisualizerModeHonored: anchorCore.forcedVisualizerModeHonored
    readonly property alias forcedVisualizerModeUnavailableReason: anchorCore.forcedVisualizerModeUnavailableReason
    readonly property alias visualizerStrategySelectedBy: anchorCore.visualizerStrategySelectedBy
    readonly property alias anchorReactiveAnimationDisabledByMode: anchorCore.anchorReactiveAnimationDisabledByMode
    readonly property alias anchorVisualizerModeUnavailable: anchorCore.anchorVisualizerModeUnavailable
    readonly property alias anchorVisualizerModeUnavailableReason: anchorCore.anchorVisualizerModeUnavailableReason
    readonly property alias finalSpeakingEnergyMinDuringSpeaking: anchorCore.finalSpeakingEnergyMinDuringSpeaking
    readonly property alias finalSpeakingEnergyMaxDuringSpeaking: anchorCore.finalSpeakingEnergyMaxDuringSpeaking
    readonly property alias envelopeTimelineReadyAtPlaybackStart: anchorCore.envelopeTimelineReadyAtPlaybackStart

    implicitWidth: anchorCore.implicitWidth
    implicitHeight: anchorCore.implicitHeight

    function voiceAnchorLabel() {
        var anchor = root.voiceState && root.voiceState.voice_anchor ? root.voiceState.voice_anchor : ({})
        if (anchor && anchor.state_label !== undefined && anchor.state_label !== null)
            return String(anchor.state_label)
        return ""
    }

    function allowVoiceAnchorLabel() {
        var tone = root.stateTone.length > 0 ? root.stateTone : root.assistantState
        if (root.stateSource === "voice_state" || root.stateSource === "speaking_playback_state")
            return true
        return tone === "idle" || tone === "ready" || tone === "wake_detected"
    }

    StormforgeAnchorCore {
        id: anchorCore
        objectName: "stormforgeAnchorCore"
        anchors.fill: parent
        voiceState: root.voiceState
        voiceVisualState: root.voiceVisualState
        assistantState: root.stateTone.length > 0 ? root.stateTone : root.assistantState
        state: root.stateTone.length > 0 ? root.stateTone : root.assistantState
        stateSourceHint: root.stateSource
        label: root.label.length > 0 ? root.label : (root.allowVoiceAnchorLabel() ? root.voiceAnchorLabel() : "")
        sublabel: root.sublabel
        intensity: root.intensity
        active: root.active
        disabled: root.disabled
        warning: root.warning
        speakingLevel: root.speakingLevel
        audioLevel: root.audioLevel
        progress: root.progress
        pulseStrength: root.pulseStrength
        compact: root.compact
        visualizerDiagnosticMode: root.visualizerDiagnosticMode
        anchorRenderer: root.anchorRenderer
        renderLoopDiagnosticsEnabled: root.renderLoopDiagnosticsEnabled
        visualClockAnimationTimeMs: root.visualClockAnimationTimeMs
        visualClockDeltaMs: root.visualClockDeltaMs
        visualClockWallTimeMs: root.visualClockWallTimeMs
        visualClockFrameCounter: root.visualClockFrameCounter
        visualClockMeasuredFps: root.visualClockMeasuredFps
        visualClockLongFrameCount: root.visualClockLongFrameCount
    }
}
