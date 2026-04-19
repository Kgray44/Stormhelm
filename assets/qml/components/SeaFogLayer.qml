import QtQuick 2.15

Item {
    id: root

    property real phase: 0
    property real layerOpacity: 0.02
    property real layerScale: 0.6
    property real phaseOffset: 0.0
    property real fullField: 0.2
    property real centerBias: 0.6
    property vector2d drift: Qt.vector2d(0.008, -0.004)
    property vector2d focusPoint: Qt.vector2d(0.5, 0.56)
    property vector2d spread: Qt.vector2d(0.34, 0.22)
    property vector4d tintColor: Qt.vector4d(0.46, 0.58, 0.62, 1.0)

    ShaderEffect {
        anchors.fill: parent
        blending: true

        property real time: root.phase
        property real depth: root.layerOpacity
        property real layerScale: root.layerScale
        property real phaseOffset: root.phaseOffset
        property real fullField: root.fullField
        property real centerBias: root.centerBias
        property vector2d drift: root.drift
        property vector2d focusPoint: root.focusPoint
        property vector2d spread: root.spread
        property vector4d tintColor: root.tintColor

        fragmentShader: Qt.resolvedUrl("../shaders/sea_fog.frag.qsb")
    }
}
