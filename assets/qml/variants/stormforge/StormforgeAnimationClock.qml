import QtQuick 2.15

Item {
    id: root

    readonly property string renderCadenceVersion: "UI-P2R"
    property bool running: true
    property bool speakingActive: false
    property int targetFps: 60
    property int minAcceptableFps: 30
    readonly property int frameIntervalMs: Math.max(1, Math.round(1000 / Math.max(1, root.targetFps)))
    property real animationTimeMs: 0
    readonly property real animationTimeSec: root.animationTimeMs / 1000.0
    property real deltaTimeMs: root.frameIntervalMs
    property real wallTimeMs: 0
    property int frameCounter: 0
    property real measuredFps: 0
    property int droppedFrameCount: 0
    property int longFrameCount: 0
    property int speakingLongFrameCount: 0
    property real lastFrameGapMs: 0
    property real maxFrameGapMs: 0
    property real maxSpeakingFrameGapMs: 0
    property real measuredSpeakingFps: 0
    readonly property bool cadenceStable: root.frameCounter <= 4
        || (root.measuredFps >= root.minAcceptableFps && root.maxFrameGapMs <= 100)
    readonly property bool speakingCadenceStable: !root.speakingActive
        || root.frameCounter <= 4
        || (root.measuredSpeakingFps >= root.minAcceptableFps && root.maxSpeakingFrameGapMs <= 100)

    property real _lastTickWallMs: 0
    property real _sampleWindowStartedMs: 0
    property int _sampleWindowFrames: 0
    property int _speakingWindowFrames: 0

    signal frameTick(real animationTimeMs, real deltaTimeMs, real wallTimeMs, int frameCounter)

    function resetTiming(now) {
        root._lastTickWallMs = now
        root._sampleWindowStartedMs = now
        root._sampleWindowFrames = 0
        root._speakingWindowFrames = 0
        root.wallTimeMs = now
        root.lastFrameGapMs = 0
    }

    Timer {
        id: visualFrameTimer
        interval: root.frameIntervalMs
        repeat: true
        running: root.running
        onTriggered: {
            var now = Date.now()
            if (root._lastTickWallMs <= 0)
                root.resetTiming(now)
            var gap = Math.max(0, now - root._lastTickWallMs)
            var boundedDelta = Math.min(Math.max(gap, root.frameIntervalMs * 0.5), 1000 / Math.max(1, root.minAcceptableFps))
            root._lastTickWallMs = now
            root.wallTimeMs = now
            root.lastFrameGapMs = gap
            root.maxFrameGapMs = Math.max(root.maxFrameGapMs, gap)
            if (gap > 50)
                root.longFrameCount += 1
            if (gap > 100)
                root.droppedFrameCount += 1
            if (root.speakingActive) {
                root.maxSpeakingFrameGapMs = Math.max(root.maxSpeakingFrameGapMs, gap)
                if (gap > 50)
                    root.speakingLongFrameCount += 1
            }
            root.deltaTimeMs = boundedDelta
            root.animationTimeMs += boundedDelta
            root.frameCounter += 1
            root._sampleWindowFrames += 1
            if (root.speakingActive)
                root._speakingWindowFrames += 1

            var elapsed = now - root._sampleWindowStartedMs
            if (elapsed >= 1000) {
                var scale = 1000.0 / Math.max(1, elapsed)
                root.measuredFps = root._sampleWindowFrames * scale
                root.measuredSpeakingFps = root.speakingActive ? root._speakingWindowFrames * scale : root.measuredFps
                root._sampleWindowFrames = 0
                root._speakingWindowFrames = 0
                root._sampleWindowStartedMs = now
            }

            root.frameTick(root.animationTimeMs, root.deltaTimeMs, root.wallTimeMs, root.frameCounter)
        }
    }

    onRunningChanged: {
        if (root.running)
            root.resetTiming(Date.now())
    }

    Component.onCompleted: root.resetTiming(Date.now())
}
