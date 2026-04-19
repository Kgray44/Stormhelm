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

    readonly property string visiblePrimary: root.captureActive
                                           ? (root.draftText.length > 0 ? root.draftText : "Signal the helm")
                                           : root.primaryText
    readonly property string visibleSecondary: root.captureActive ? root.hintText : root.secondaryText
    readonly property bool showCaret: root.captureActive && (Math.floor(root.caretPhase) % 2 === 0)
    readonly property color accentColor: root.stateName === "warning" ? "#c59159"
                                             : root.stateName === "acting" ? "#c4a067"
                                             : root.stateName === "speaking" ? "#a3e2ef"
                                             : root.stateName === "listening" ? "#8fd8d9"
                                             : root.stateName === "thinking" ? "#8dbfda"
                                             : "#78c2da"
    readonly property color primaryColor: root.captureActive && root.draftText.length === 0 ? "#a8bfca"
                                              : root.stateName === "warning" ? "#f3ddc2"
                                              : "#edf8fb"
    readonly property color secondaryColor: root.stateName === "warning" ? "#cda980" : "#8eabb8"

    implicitWidth: 440
    implicitHeight: root.captureActive ? 72 : 64

    NumberAnimation on caretPhase {
        from: 0
        to: 2
        loops: Animation.Infinite
        duration: 1100
        running: root.captureActive
    }

    FieldSurface {
        anchors.fill: parent
        radius: 30
        padding: 14
        tintColor: "#16222d"
        edgeColor: root.accentColor
        glowColor: root.accentColor
        fillOpacity: root.shellMode === "ghost" ? 0.72 : 0.82
        edgeOpacity: 0.18 + root.deckProgress * 0.1 + (root.captureActive ? 0.08 : 0)
        lineOpacity: 0.06 + root.deckProgress * 0.04

        Column {
            anchors.fill: parent
            spacing: 4

            Text {
                text: root.eyebrow
                color: Qt.tint("#90afbe", Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.28))
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: 11
                font.letterSpacing: 1.9
                visible: text.length > 0

                Behavior on color {
                    ColorAnimation { duration: 360; easing.type: Easing.InOutQuad }
                }
            }

            Text {
                text: root.visiblePrimary + (root.captureActive && root.showCaret ? " |" : "")
                color: root.primaryColor
                font.family: "Segoe UI Semibold"
                font.pixelSize: 15
                wrapMode: Text.Wrap
                maximumLineCount: root.captureActive ? 3 : 2
                elide: root.captureActive ? Text.ElideNone : Text.ElideRight

                Behavior on color {
                    ColorAnimation { duration: 360; easing.type: Easing.InOutQuad }
                }
            }

            Text {
                text: root.visibleSecondary
                color: root.secondaryColor
                font.family: "Segoe UI"
                font.pixelSize: 11
                wrapMode: Text.Wrap
                visible: text.length > 0

                Behavior on color {
                    ColorAnimation { duration: 360; easing.type: Easing.InOutQuad }
                }
            }
        }
    }
}
