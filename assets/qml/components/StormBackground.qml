import QtQuick 2.15

Item {
    id: root
    objectName: "stormBackground"

    property string mode: "ghost"
    property real deckProgress: mode === "deck" ? 1 : 0
    property real topVeilStrength: mode === "ghost" ? 0.010 : 0.028

    DeckGlassLayer {
        anchors.fill: parent
        mode: root.mode
        deckProgress: root.deckProgress
    }

    SeaFogField {
        anchors.fill: parent
        mode: root.mode
        deckProgress: root.deckProgress
    }
}
