import QtQuick 2.15

StormforgeCard {
    id: root

    property var card: ({})
    readonly property string cardTone: sf.normalizeState(
        card.resultState
        || card.state
        || card.status
        || card.routeState
        || "planned"
    )

    title: String(card.title || card.routeLabel || "")
    subtitle: String(card.subtitle || card.familyLabel || card.resultState || "")
    body: String(card.body || card.summary || card.microResponse || "")
    stateTone: cardTone
    elevation: sf.elevationLow
    fillOpacity: 0.72
    width: 260
    height: 108

    StormforgeTokens {
        id: sf
    }

    StormforgeResultBadge {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.rightMargin: sf.space3
        anchors.topMargin: sf.space3
        label: root.cardTone
        resultState: root.cardTone
        visible: root.cardTone !== "planned" && root.cardTone !== "idle"
    }
}
