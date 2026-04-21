import QtQuick 2.15

Item {
    id: root

    property real coreBottom: 0
    property real deckProgress: 0
    property var messages: []
    property var contextCards: []
    property var cornerReadouts: []
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
    readonly property int messageStartIndex: Math.max(0, root.messages.length - 2)

    enabled: false

    function toneColor(baseColor) {
        if (root.adaptiveTone > 0) {
            return Qt.darker(baseColor, 1 + root.adaptiveTone * 0.7)
        }
        if (root.adaptiveTone < 0) {
            return Qt.lighter(baseColor, 1 + Math.abs(root.adaptiveTone) * 0.45)
        }
        return baseColor
    }

    function contrastColor(baseColor, boost) {
        return Qt.lighter(root.toneColor(baseColor), 1 + boost)
    }

    Repeater {
        model: root.cornerReadouts

        delegate: CornerReadout {
            required property var modelData

            width: 220
            label: modelData.label
            primary: modelData.primary
            secondary: modelData.secondary
            rightAligned: modelData.corner === "top_right" || modelData.corner === "bottom_right"
            tone: root.adaptiveTone
            contrastBoost: root.adaptiveTextContrast
            shadowOpacity: root.adaptiveShadowOpacity
            backdropOpacity: root.adaptiveBackdropOpacity
            anchors.top: modelData.corner === "top_left" || modelData.corner === "top_right" ? parent.top : undefined
            anchors.bottom: modelData.corner === "bottom_left" || modelData.corner === "bottom_right" ? parent.bottom : undefined
            anchors.left: modelData.corner === "top_left" || modelData.corner === "bottom_left" ? parent.left : undefined
            anchors.right: modelData.corner === "top_right" || modelData.corner === "bottom_right" ? parent.right : undefined
            anchors.topMargin: 42
            anchors.bottomMargin: 54
            anchors.leftMargin: 54
            anchors.rightMargin: 54
            opacity: (1 - root.deckProgress * 0.58) * 0.84
        }
    }

    Column {
        id: ghostContent
        width: Math.min(parent.width * 0.72, 940)
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.coreBottom + 14 + root.deckProgress * 26
        spacing: 14
        opacity: 1 - root.deckProgress * 0.46

        transform: Translate {
            id: ghostContentMotion
            x: root.contentOffsetX
            y: root.contentOffsetY

            Behavior on x {
                NumberAnimation { duration: 620; easing.type: Easing.InOutCubic }
            }
            Behavior on y {
                NumberAnimation { duration: 620; easing.type: Easing.InOutCubic }
            }
        }

        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width * 0.7, 620)
            spacing: 7
            visible: root.messages.length > 0

            Repeater {
                model: root.messages.slice(root.messageStartIndex)

                delegate: Item {
                    required property var modelData
                    width: parent.width
                    height: lineText.implicitHeight

                    Text {
                        id: lineText
                        width: parent.width
                        text: modelData.speaker + "   " + modelData.content
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        color: modelData.role === "user"
                            ? root.contrastColor("#d8eef8", root.adaptiveTextContrast * 0.35)
                            : root.contrastColor("#edf7fb", root.adaptiveTextContrast * 0.45)
                        font.family: modelData.role === "user" ? "Segoe UI Semibold" : "Segoe UI"
                        font.pixelSize: 13
                        opacity: 0.88
                        style: Text.Raised
                        styleColor: Qt.rgba(0.01, 0.04, 0.07, root.adaptiveShadowOpacity)
                    }
                }
            }
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 14
            visible: root.contextCards.length > 0
            opacity: 0.9 - root.deckProgress * 0.28

            Repeater {
                model: root.contextCards

                delegate: ContextCard {
                    required property var modelData
                    card: modelData
                    presentation: "ghost"
                    ghostStyle: ({
                        "tone": root.adaptiveTone,
                        "textContrast": root.adaptiveTextContrast,
                        "secondaryTextContrast": root.adaptiveSecondaryTextContrast,
                        "backdropOpacity": root.adaptiveBackdropOpacity
                    })
                }
            }
        }
    }
}
