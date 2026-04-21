import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    property var displayData: ({})
    property bool panelMode: false
    property bool detailsExpanded: false

    implicitHeight: surfaceColumn.implicitHeight

    function statePalette(state) {
        switch (String(state || "").toLowerCase()) {
        case "healthy":
            return { fill: "#12242d", edge: "#4d7d87", accent: "#9ad4c7", text: "#eef9f6" }
        case "warning":
            return { fill: "#221c1a", edge: "#85685b", accent: "#f0bd8a", text: "#fff2e6" }
        case "attention":
            return { fill: "#1e1a22", edge: "#70608a", accent: "#c9b6ff", text: "#f5f0ff" }
        default:
            return { fill: "#101a22", edge: "#446275", accent: "#84bfd5", text: "#eef7fb" }
        }
    }

    function severityAccent(severity) {
        switch (String(severity || "").toLowerCase()) {
        case "warning":
            return "#e3a66e"
        case "attention":
            return "#9fc9da"
        case "steady":
            return "#9ad4c7"
        default:
            return "#87a5b3"
        }
    }

    readonly property var heroPalette: statePalette((displayData.hero || {}).state)
    readonly property var metricItems: displayData.metrics || []
    readonly property var eventItems: displayData.events || []
    readonly property var detailItems: displayData.details || []
    readonly property var trendData: displayData.trend || ({})
    readonly property var providerData: displayData.provider || ({})

    ColumnLayout {
        id: surfaceColumn
        width: root.width
        spacing: root.panelMode ? 12 : 14

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: heroColumn.implicitHeight + 24
            radius: 24
            color: root.heroPalette.fill
            border.width: 1
            border.color: root.heroPalette.edge
            opacity: 0.96

            Behavior on color {
                ColorAnimation { duration: 220 }
            }

            ColumnLayout {
                id: heroColumn
                anchors.fill: parent
                anchors.margins: 16
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Rectangle {
                        width: 10
                        height: 10
                        radius: 5
                        color: root.heroPalette.accent
                        opacity: 0.92
                    }

                    Text {
                        Layout.fillWidth: true
                        text: (root.displayData.hero || {}).status || "Monitoring"
                        color: root.heroPalette.text
                        font.family: "Bahnschrift SemiCondensed"
                        font.pixelSize: root.panelMode ? 21 : 25
                        font.letterSpacing: 0.8
                        wrapMode: Text.Wrap
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: (root.displayData.hero || {}).summary || ""
                    color: "#d9e8ef"
                    font.family: "Segoe UI Semibold"
                    font.pixelSize: root.panelMode ? 13 : 14
                    wrapMode: Text.Wrap
                    lineHeight: 1.18
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 8

                    Repeater {
                        model: [
                            { "label": "Assessment", "value": (root.displayData.hero || {}).assessment || "Gathering attribution" },
                            { "label": "Confidence", "value": (root.displayData.hero || {}).confidence || "Low confidence" },
                            { "label": "Evidence", "value": (root.displayData.hero || {}).evidence || "Building recent history" }
                        ]

                        delegate: Rectangle {
                            required property var modelData
                            radius: 14
                            color: "#0d161d"
                            border.width: 1
                            border.color: "#385263"
                            height: 28
                            width: chipRow.implicitWidth + 18

                            Row {
                                id: chipRow
                                anchors.centerIn: parent
                                spacing: 6

                                Text {
                                    text: modelData.label
                                    color: "#8aa5b2"
                                    font.family: "Bahnschrift SemiCondensed"
                                    font.pixelSize: 10
                                    font.letterSpacing: 1.2
                                }

                                Text {
                                    text: modelData.value
                                    color: "#edf7fb"
                                    font.family: "Segoe UI Semibold"
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: width > 620 ? 4 : 2
            columnSpacing: 10
            rowSpacing: 10
            visible: root.metricItems.length > 0

            Repeater {
                model: root.metricItems

                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: metricColumn.implicitHeight + 18
                    radius: 18
                    color: "#101b24"
                    border.width: 1
                    border.color: "#335364"
                    opacity: 0.94

                    ColumnLayout {
                        id: metricColumn
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 4

                        Text {
                            text: modelData.label
                            color: "#87a4b2"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 11
                            font.letterSpacing: 1.2
                        }

                        Text {
                            text: modelData.value
                            color: root.severityAccent(modelData.severity)
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: root.panelMode ? 18 : 22
                        }

                        Text {
                            text: modelData.detail
                            visible: text.length > 0
                            color: "#bfd2dc"
                            font.family: "Segoe UI"
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: trendColumn.implicitHeight + 18
            radius: 20
            color: "#0f1a23"
            border.width: 1
            border.color: "#315061"
            opacity: 0.94

            ColumnLayout {
                id: trendColumn
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3

                        Text {
                            text: "Recent Quality"
                            color: "#ddebf3"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 15
                        }

                        Text {
                            text: (root.trendData || {}).summary || "Building recent history"
                            color: "#8fa6b3"
                            font.family: "Segoe UI"
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }

                    Rectangle {
                        radius: 12
                        color: "#152430"
                        border.width: 1
                        border.color: "#39596b"
                        height: 24
                        width: trendBadge.implicitWidth + 14

                        Text {
                            id: trendBadge
                            anchors.centerIn: parent
                            text: (root.trendData || {}).state === "ready" ? "Live trend" : "Gathering"
                            color: "#e2f1f8"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 10
                            font.letterSpacing: 1.0
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    implicitHeight: 120

                    Canvas {
                        id: trendCanvas
                        anchors.fill: parent
                        visible: ((root.trendData || {}).points || []).length > 1
                        antialiasing: true

                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.reset()
                            var points = (root.trendData || {}).points || []
                            if (points.length < 2)
                                return

                            var margin = 10
                            var widthUsable = width - margin * 2
                            var heightUsable = height - margin * 2
                            var maxLatency = 1
                            for (var i = 0; i < points.length; ++i) {
                                maxLatency = Math.max(maxLatency, Number(points[i].latency_ms || 0), Number(points[i].gateway_latency_ms || 0))
                            }

                            ctx.strokeStyle = "rgba(85, 123, 142, 0.35)"
                            ctx.lineWidth = 1
                            ctx.beginPath()
                            ctx.moveTo(margin, height - margin)
                            ctx.lineTo(width - margin, height - margin)
                            ctx.stroke()

                            ctx.strokeStyle = "#9fd0e2"
                            ctx.lineWidth = 2
                            ctx.beginPath()
                            for (var j = 0; j < points.length; ++j) {
                                var x = margin + (widthUsable * j / Math.max(points.length - 1, 1))
                                var y = height - margin - ((Number(points[j].latency_ms || 0) / maxLatency) * heightUsable)
                                if (j === 0)
                                    ctx.moveTo(x, y)
                                else
                                    ctx.lineTo(x, y)
                            }
                            ctx.stroke()

                            ctx.strokeStyle = "rgba(240, 189, 138, 0.9)"
                            ctx.lineWidth = 1.5
                            ctx.beginPath()
                            for (var k = 0; k < points.length; ++k) {
                                var gx = margin + (widthUsable * k / Math.max(points.length - 1, 1))
                                var gy = height - margin - ((Number(points[k].gateway_latency_ms || 0) / maxLatency) * heightUsable)
                                if (k === 0)
                                    ctx.moveTo(gx, gy)
                                else
                                    ctx.lineTo(gx, gy)
                            }
                            ctx.stroke()

                            for (var m = 0; m < points.length; ++m) {
                                var loss = Number(points[m].packet_loss_pct || 0)
                                if (loss <= 0)
                                    continue
                                var lx = margin + (widthUsable * m / Math.max(points.length - 1, 1))
                                var barHeight = Math.min(heightUsable * 0.4, loss * 6)
                                ctx.fillStyle = "rgba(227, 166, 110, 0.55)"
                                ctx.fillRect(lx - 3, height - margin - barHeight, 6, barHeight)
                            }
                        }

                        Connections {
                            target: root
                            function onDisplayDataChanged() { trendCanvas.requestPaint() }
                        }
                    }

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        visible: !trendCanvas.visible
                        spacing: 6

                        Text {
                            text: "Building recent history"
                            color: "#e3f1f7"
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: 13
                        }

                        Text {
                            text: "Stormhelm is collecting enough latency, jitter, and loss samples to draw the recent trend cleanly."
                            color: "#93acb8"
                            font.family: "Segoe UI"
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: eventColumn.implicitHeight + 18
            radius: 20
            color: "#101a23"
            border.width: 1
            border.color: "#305061"
            opacity: 0.94

            ColumnLayout {
                id: eventColumn
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                Text {
                    text: "Recent Events"
                    color: "#ddeaf3"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: 15
                }

                Repeater {
                    model: root.eventItems

                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 10

                        Rectangle {
                            width: 7
                            height: 7
                            radius: 4
                            color: root.severityAccent(modelData.severity)
                            opacity: 0.95
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            RowLayout {
                                Layout.fillWidth: true

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    color: "#eef7fb"
                                    font.family: "Segoe UI Semibold"
                                    font.pixelSize: 12
                                    wrapMode: Text.Wrap
                                }

                                Text {
                                    text: modelData.meta
                                    color: "#88a4b1"
                                    font.family: "Bahnschrift SemiCondensed"
                                    font.pixelSize: 10
                                    font.letterSpacing: 1.1
                                }
                            }

                            Text {
                                text: modelData.detail
                                visible: text.length > 0
                                color: "#afc3cd"
                                font.family: "Segoe UI"
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: providerColumn.implicitHeight + 18
            radius: 18
            color: "#101a22"
            border.width: 1
            border.color: "#315061"
            opacity: 0.94

            ColumnLayout {
                id: providerColumn
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Text {
                            text: "External Quality"
                            color: "#ddebf3"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 15
                        }

                        Text {
                            text: root.providerData.value || "External quality"
                            color: "#edf7fb"
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }

                    Rectangle {
                        radius: 12
                        color: "#152430"
                        border.width: 1
                        border.color: "#39596b"
                        height: 24
                        width: providerStateText.implicitWidth + 14

                        Text {
                            id: providerStateText
                            anchors.centerIn: parent
                            text: root.providerData.state || "Unavailable"
                            color: "#e2f1f8"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 10
                            font.letterSpacing: 1.0
                        }
                    }
                }

                Text {
                    text: root.providerData.detail || "Stormhelm does not have external quality enrichment yet."
                    color: "#bfd2dc"
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }

                Text {
                    text: root.providerData.meta || ""
                    visible: text.length > 0
                    color: "#88a4b1"
                    font.family: "Bahnschrift SemiCondensed"
                    font.pixelSize: 10
                    font.letterSpacing: 1.1
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: detailsStack.implicitHeight + 16
            radius: 18
            color: "#0f1820"
            border.width: 1
            border.color: "#304d5d"
            opacity: 0.94

            ColumnLayout {
                id: detailsStack
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 34
                    radius: 14
                    color: "#13212b"
                    border.width: 1
                    border.color: "#36586a"

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 8

                        Text {
                            Layout.fillWidth: true
                            text: "Supporting details"
                            color: "#e4f2f8"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 13
                        }

                        Text {
                            text: root.detailsExpanded ? "Hide" : "Show"
                            color: "#90abb8"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 10
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: root.detailsExpanded = !root.detailsExpanded
                    }
                }

                Item {
                    Layout.fillWidth: true
                    height: root.detailsExpanded ? detailsColumn.implicitHeight + 4 : 0
                    clip: true

                    Behavior on height {
                        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
                    }

                    ColumnLayout {
                        id: detailsColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        spacing: 6
                        opacity: root.detailsExpanded ? 1 : 0

                        Behavior on opacity {
                            NumberAnimation { duration: 140 }
                        }

                        Repeater {
                            model: root.detailItems

                            delegate: RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 12

                                Text {
                                    Layout.preferredWidth: 106
                                    text: modelData.label
                                    color: "#7e9aa8"
                                    font.family: "Bahnschrift SemiCondensed"
                                    font.pixelSize: 10
                                    font.letterSpacing: 1.1
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.value
                                    color: "#d8e7ee"
                                    font.family: "Segoe UI"
                                    font.pixelSize: 11
                                    wrapMode: Text.Wrap
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
