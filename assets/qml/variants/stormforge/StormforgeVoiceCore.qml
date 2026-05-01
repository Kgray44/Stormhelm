import QtQuick 2.15

Item {
    id: root

    property var voiceState: ({})
    property string assistantState: "idle"
    readonly property string resolvedState: resolveVoiceState()
    readonly property color accentColor: sf.stateAccent(resolvedState)

    implicitWidth: 188
    implicitHeight: 188

    StormforgeTokens {
        id: sf
    }

    function textValue(value) {
        if (value === undefined || value === null)
            return ""
        return String(value).toLowerCase()
    }

    function resolveVoiceState() {
        var phase = textValue(root.voiceState.voice_current_phase)
        var anchor = textValue(root.voiceState.voice_anchor_state)
        var playback = textValue(root.voiceState.active_playback_status)
        var assistant = textValue(root.assistantState)
        var combined = phase + " " + anchor + " " + playback + " " + assistant

        if (root.voiceState.speaking_visual_active || playback === "playing" || combined.indexOf("speaking") >= 0)
            return "speaking"
        if (combined.indexOf("failed") >= 0 || combined.indexOf("error") >= 0)
            return "failed"
        if (combined.indexOf("blocked") >= 0 || combined.indexOf("warning") >= 0)
            return "blocked"
        if (combined.indexOf("acting") >= 0 || combined.indexOf("execut") >= 0)
            return "acting"
        if (combined.indexOf("thinking") >= 0 || combined.indexOf("routing") >= 0 || combined.indexOf("processing") >= 0)
            return "thinking"
        if (combined.indexOf("listening") >= 0 || combined.indexOf("capture") >= 0)
            return "listening"
        if (combined.indexOf("wake") >= 0 || combined.indexOf("ready") >= 0)
            return "active"
        return "idle"
    }

    Rectangle {
        id: outerRing
        anchors.fill: parent
        radius: width / 2
        color: Qt.rgba(sf.abyss.r, sf.abyss.g, sf.abyss.b, 0.24)
        border.width: 1
        border.color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.58)
    }

    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.76
        height: width
        radius: width / 2
        color: Qt.rgba(sf.deepBlue.r, sf.deepBlue.g, sf.deepBlue.b, 0.42)
        border.width: 1
        border.color: Qt.rgba(sf.lineSoft.r, sf.lineSoft.g, sf.lineSoft.b, 0.5)
    }

    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.42
        height: width
        radius: width / 2
        color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.18)
        border.width: 1
        border.color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.76)
        opacity: 0.84
    }

    Repeater {
        model: 24

        delegate: Rectangle {
            required property int index

            width: index % 6 === 0 ? 2 : 1
            height: index % 6 === 0 ? 12 : 7
            radius: 1
            color: index % 6 === 0 ? root.accentColor : sf.lineStrong
            opacity: index % 6 === 0 ? 0.76 : 0.34
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            transform: [
                Rotation {
                    origin.x: 0
                    origin.y: root.height * 0.38
                    angle: index * 15
                },
                Translate {
                    y: -root.height * 0.38
                }
            ]
        }
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: sf.space4
        text: root.resolvedState
        color: sf.textSecondary
        font.family: "Bahnschrift SemiCondensed"
        font.pixelSize: sf.fontSm
        opacity: 0.82
    }
}
