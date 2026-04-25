import QtQuick 2.15

Item {
    id: root

    property string shellMode: "ghost"
    property string stateName: "idle"
    property string eyebrow: ""
    property string primaryText: ""
    property string secondaryText: ""
    property bool captureActive: false
    property string draftText: ""
    property string hintText: ""
    property real deckProgress: 0
    property real caretPhase: 0
    property var ghostStyle: ({})

    readonly property string visiblePrimary: root.captureActive
                                           ? (root.draftText.length > 0 ? root.draftText : "Signal the helm")
                                           : root.primaryText
    readonly property string visibleSecondary: root.captureActive ? root.hintText : root.secondaryText
    readonly property bool showCaret: root.captureActive && (Math.floor(root.caretPhase) % 2 === 0)
    readonly property real adaptiveTone: root.ghostStyle && root.ghostStyle["tone"] !== undefined ? Number(root.ghostStyle["tone"]) : 0
    readonly property real adaptiveSurfaceOpacity: root.ghostStyle && root.ghostStyle["surfaceOpacity"] !== undefined ? Number(root.ghostStyle["surfaceOpacity"]) : (root.shellMode === "ghost" ? 0.72 : 0.82)
    readonly property real adaptiveEdgeOpacity: root.ghostStyle && root.ghostStyle["edgeOpacity"] !== undefined ? Number(root.ghostStyle["edgeOpacity"]) : (0.18 + root.deckProgress * 0.1 + (root.captureActive ? 0.08 : 0))
    readonly property real adaptiveLineOpacity: root.ghostStyle && root.ghostStyle["lineOpacity"] !== undefined ? Number(root.ghostStyle["lineOpacity"]) : (0.06 + root.deckProgress * 0.04)
    readonly property real adaptiveTextContrast: root.ghostStyle && root.ghostStyle["textContrast"] !== undefined ? Number(root.ghostStyle["textContrast"]) : 0.08
    readonly property real adaptiveSecondaryTextContrast: root.ghostStyle && root.ghostStyle["secondaryTextContrast"] !== undefined ? Number(root.ghostStyle["secondaryTextContrast"]) : 0.05
    readonly property real adaptiveShadowOpacity: root.ghostStyle && root.ghostStyle["shadowOpacity"] !== undefined ? Number(root.ghostStyle["shadowOpacity"]) : 0.1
    property real visualAdaptiveTone: adaptiveTone
    property real visualAdaptiveSurfaceOpacity: adaptiveSurfaceOpacity
    property real visualAdaptiveEdgeOpacity: adaptiveEdgeOpacity
    property real visualAdaptiveLineOpacity: adaptiveLineOpacity
    property real visualAdaptiveTextContrast: adaptiveTextContrast
    property real visualAdaptiveSecondaryTextContrast: adaptiveSecondaryTextContrast
    property real visualAdaptiveShadowOpacity: adaptiveShadowOpacity
    readonly property color accentColor: root.stateName === "warning" ? "#c59159"
                                             : root.stateName === "acting" ? "#c4a067"
                                             : root.stateName === "speaking" ? "#a3e2ef"
                                             : root.stateName === "listening" ? "#8fd8d9"
                                             : root.stateName === "thinking" ? "#8dbfda"
                                             : "#78c2da"
    readonly property color primaryColor: root.captureActive && root.draftText.length === 0 ? root.contrastColor("#a8bfca", root.visualAdaptiveSecondaryTextContrast * 0.28)
                                              : root.stateName === "warning" ? root.contrastColor("#f3ddc2", root.visualAdaptiveTextContrast * 0.16)
                                              : root.contrastColor("#edf8fb", root.visualAdaptiveTextContrast * 0.4)
    readonly property color secondaryColor: root.stateName === "warning" ? root.contrastColor("#cda980", root.visualAdaptiveSecondaryTextContrast * 0.14) : root.contrastColor("#8eabb8", root.visualAdaptiveSecondaryTextContrast * 0.34)

    implicitWidth: 440
    implicitHeight: Math.max(root.captureActive ? 72 : 64, contentColumn.implicitHeight + 28)

    function toneColor(baseColor) {
        if (root.visualAdaptiveTone > 0) {
            return Qt.darker(baseColor, 1 + root.visualAdaptiveTone * 0.7)
        }
        if (root.visualAdaptiveTone < 0) {
            return Qt.lighter(baseColor, 1 + Math.abs(root.visualAdaptiveTone) * 0.45)
        }
        return baseColor
    }

    function contrastColor(baseColor, boost) {
        return Qt.lighter(root.toneColor(baseColor), 1 + boost)
    }

    NumberAnimation on caretPhase {
        from: 0
        to: 2
        loops: Animation.Infinite
        duration: 1100
        running: root.captureActive
    }

    onAdaptiveToneChanged: root.visualAdaptiveTone = root.adaptiveTone
    onAdaptiveSurfaceOpacityChanged: root.visualAdaptiveSurfaceOpacity = root.adaptiveSurfaceOpacity
    onAdaptiveEdgeOpacityChanged: root.visualAdaptiveEdgeOpacity = root.adaptiveEdgeOpacity
    onAdaptiveLineOpacityChanged: root.visualAdaptiveLineOpacity = root.adaptiveLineOpacity
    onAdaptiveTextContrastChanged: root.visualAdaptiveTextContrast = root.adaptiveTextContrast
    onAdaptiveSecondaryTextContrastChanged: root.visualAdaptiveSecondaryTextContrast = root.adaptiveSecondaryTextContrast
    onAdaptiveShadowOpacityChanged: root.visualAdaptiveShadowOpacity = root.adaptiveShadowOpacity

    Behavior on visualAdaptiveTone {
        NumberAnimation { duration: 520; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveSurfaceOpacity {
        NumberAnimation { duration: 520; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveEdgeOpacity {
        NumberAnimation { duration: 520; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveLineOpacity {
        NumberAnimation { duration: 520; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveTextContrast {
        NumberAnimation { duration: 520; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveSecondaryTextContrast {
        NumberAnimation { duration: 520; easing.type: Easing.InOutCubic }
    }
    Behavior on visualAdaptiveShadowOpacity {
        NumberAnimation { duration: 520; easing.type: Easing.InOutCubic }
    }

    FieldSurface {
        anchors.fill: parent
        radius: 30
        padding: 14
        tintColor: root.shellMode === "ghost" ? root.toneColor("#16222d") : "#101821"
        edgeColor: root.accentColor
        glowColor: root.accentColor
        fillOpacity: root.shellMode === "ghost" ? root.visualAdaptiveSurfaceOpacity : 0.88
        edgeOpacity: root.shellMode === "ghost" ? root.visualAdaptiveEdgeOpacity + (root.captureActive ? 0.04 : 0) : 0.24 + root.deckProgress * 0.12 + (root.captureActive ? 0.08 : 0)
        lineOpacity: root.shellMode === "ghost" ? root.visualAdaptiveLineOpacity : 0.08 + root.deckProgress * 0.05

        Column {
            id: contentColumn
            anchors.fill: parent
            spacing: 4

            Text {
                width: parent.width
                text: root.eyebrow
                color: root.contrastColor(Qt.tint("#90afbe", Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.28)), root.visualAdaptiveSecondaryTextContrast * 0.2)
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: 11
                font.letterSpacing: 1.9
                visible: text.length > 0
                style: Text.Raised
                styleColor: Qt.rgba(0.01, 0.04, 0.07, root.visualAdaptiveShadowOpacity)

                Behavior on color {
                    ColorAnimation { duration: 360; easing.type: Easing.InOutQuad }
                }
            }

            Text {
                width: parent.width
                text: root.visiblePrimary + (root.captureActive && root.showCaret ? " |" : "")
                color: root.primaryColor
                font.family: "Segoe UI Semibold"
                font.pixelSize: 15
                wrapMode: Text.WordWrap
                maximumLineCount: root.captureActive ? 3 : 2
                elide: root.captureActive ? Text.ElideNone : Text.ElideRight
                style: Text.Raised
                styleColor: Qt.rgba(0.01, 0.04, 0.07, root.visualAdaptiveShadowOpacity)

                Behavior on color {
                    ColorAnimation { duration: 360; easing.type: Easing.InOutQuad }
                }
            }

            Text {
                width: parent.width
                text: root.visibleSecondary
                color: root.secondaryColor
                font.family: "Segoe UI"
                font.pixelSize: 11
                wrapMode: Text.WordWrap
                visible: text.length > 0
                style: Text.Raised
                styleColor: Qt.rgba(0.01, 0.04, 0.07, root.visualAdaptiveShadowOpacity)

                Behavior on color {
                    ColorAnimation { duration: 360; easing.type: Easing.InOutQuad }
                }
            }
        }
    }
}
