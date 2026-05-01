import QtQuick 2.15

Item {
    id: root

    property var voiceState: ({})
    property string assistantState: "idle"
    property string stateTone: "idle"
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
    property bool anchorCoreAvailable: true
    property url anchorCoreSource: Qt.resolvedUrl("StormforgeAnchorCore.qml")

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

    implicitWidth: anchorCore.implicitWidth
    implicitHeight: anchorCore.implicitHeight

    function voiceAnchorLabel() {
        var anchor = root.voiceState && root.voiceState.voice_anchor ? root.voiceState.voice_anchor : ({})
        if (anchor && anchor.state_label !== undefined && anchor.state_label !== null)
            return String(anchor.state_label)
        return ""
    }

    StormforgeAnchorCore {
        id: anchorCore
        objectName: "stormforgeAnchorCore"
        anchors.fill: parent
        voiceState: root.voiceState
        assistantState: root.stateTone.length > 0 ? root.stateTone : root.assistantState
        state: root.stateTone.length > 0 ? root.stateTone : root.assistantState
        label: root.label.length > 0 ? root.label : root.voiceAnchorLabel()
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
    }
}
