import QtQuick 2.15

Rectangle {
    id: root

    property string stateTone: "idle"

    height: 1
    color: stateTone === "idle" ? Qt.rgba(sf.lineSoft.r, sf.lineSoft.g, sf.lineSoft.b, 0.62) : sf.stateStroke(stateTone)

    StormforgeTokens {
        id: sf
    }
}
