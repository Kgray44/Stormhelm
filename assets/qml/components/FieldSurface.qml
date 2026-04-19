import QtQuick 2.15

Item {
    id: root

    default property alias contentData: content.data

    property real radius: 28
    property real padding: 18
    property color tintColor: "#1a2430"
    property color edgeColor: "#5f8da7"
    property color glowColor: "#78c3da"
    property real fillOpacity: 0.7
    property real edgeOpacity: 0.34
    property real lineOpacity: 0.1
    property bool accentTopLine: true

    implicitWidth: 260
    implicitHeight: 160

    Behavior on tintColor {
        ColorAnimation { duration: 420; easing.type: Easing.InOutQuad }
    }

    Behavior on edgeColor {
        ColorAnimation { duration: 420; easing.type: Easing.InOutQuad }
    }

    Behavior on glowColor {
        ColorAnimation { duration: 420; easing.type: Easing.InOutQuad }
    }

    Behavior on fillOpacity {
        NumberAnimation { duration: 320; easing.type: Easing.InOutQuad }
    }

    Behavior on edgeOpacity {
        NumberAnimation { duration: 320; easing.type: Easing.InOutQuad }
    }

    Behavior on lineOpacity {
        NumberAnimation { duration: 320; easing.type: Easing.InOutQuad }
    }

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: Qt.rgba(root.tintColor.r, root.tintColor.g, root.tintColor.b, root.fillOpacity * 0.12)
        border.width: 1
        border.color: Qt.rgba(root.edgeColor.r, root.edgeColor.g, root.edgeColor.b, root.edgeOpacity)
        antialiasing: true

        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.08, 0.12, 0.16, root.fillOpacity * 0.68) }
            GradientStop { position: 0.46; color: Qt.rgba(0.08, 0.13, 0.18, root.fillOpacity * 0.34) }
            GradientStop { position: 1.0; color: Qt.rgba(0.06, 0.09, 0.13, root.fillOpacity * 0.58) }
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: root.radius - 1
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(root.glowColor.r, root.glowColor.g, root.glowColor.b, root.edgeOpacity * 0.18)
        opacity: 0.7
        antialiasing: true
    }

    Rectangle {
        width: parent.width * 0.82
        height: parent.height * 0.3
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: parent.height * 0.04
        radius: height / 2
        color: Qt.rgba(root.glowColor.r, root.glowColor.g, root.glowColor.b, 0.02)
        antialiasing: true
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.topMargin: root.radius * 0.48
        height: 1
        color: Qt.rgba(0.73, 0.9, 0.97, root.lineOpacity)
        visible: root.accentTopLine
        opacity: 0.56
    }

    Rectangle {
        width: parent.width * 0.44
        height: parent.height * 0.44
        radius: width / 2
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        color: Qt.rgba(root.glowColor.r, root.glowColor.g, root.glowColor.b, 0.028)
        antialiasing: true
    }

    Repeater {
        model: 2

        Rectangle {
            width: parent.width * (0.82 - index * 0.18)
            height: 1
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: root.padding + index * 16
            color: Qt.rgba(0.7, 0.88, 0.95, root.lineOpacity * (0.65 - index * 0.12))
            opacity: 0.52
        }
    }

    Item {
        id: content
        anchors.fill: parent
        anchors.margins: root.padding
    }
}
