import QtQuick 2.15

StormforgeStatusChip {
    id: root

    property string resultState: "unverified"
    readonly property string resultFamily: resolvedTone

    stateTone: resultState
}
