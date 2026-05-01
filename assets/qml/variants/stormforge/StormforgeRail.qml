import QtQuick 2.15

StormforgeGlassPanel {
    id: root

    property string orientation: "vertical"

    surfaceRole: "rail"
    fillColor: sf.railFill
    fillOpacity: 0.82
    radius: sf.radiusCard

    StormforgeTokens {
        id: sf
    }
}
