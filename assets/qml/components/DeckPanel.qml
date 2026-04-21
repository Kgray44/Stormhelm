import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    default property alias panelContent: contentHost.data

    signal gridCommitted(string panelId, int gridX, int gridY, int colSpan, int rowSpan)
    signal pinnedChangedRequested(string panelId, bool pinned)
    signal collapsedChangedRequested(string panelId, bool collapsed)
    signal hiddenChangedRequested(string panelId, bool hidden)

    property var panelData: ({})
    property real cellWidth: 96
    property real rowHeight: 84
    property real gutter: 14
    property int gridColumns: 12
    property int gridRows: 8
    property real layoutWidth: 0
    property real layoutHeight: 0
    property rect reservedRect: Qt.rect(0, 0, 0, 0)
    property real revealProgress: 1.0
    property bool normalizingGeometry: false

    property int liveGridX: Number((panelData || {}).gridX || 0)
    property int liveGridY: Number((panelData || {}).gridY || 0)
    property int liveColSpan: Number((panelData || {}).colSpan || 4)
    property int liveRowSpan: Number((panelData || {}).rowSpan || 3)
    property bool livePinned: Boolean((panelData || {}).pinned)
    property bool liveCollapsed: Boolean((panelData || {}).collapsed)
    readonly property int minCols: Math.max(2, Number((panelData || {}).minCols || 2))
    readonly property int minRows: Math.max(2, Number((panelData || {}).minRows || 2))
    readonly property string edgeHint: String((panelData || {}).edge || "center")
    readonly property real revealOffsetX: edgeHint === "left" ? -26 : edgeHint === "right" ? 26 : 0
    readonly property real revealOffsetY: edgeHint === "bottom" ? 22 : edgeHint === "center" ? 10 : 0
    readonly property bool engaged: dragArea.drag.active
                                  || rightResize.pressed
                                  || bottomResize.pressed
                                  || cornerResize.pressed
                                  || leftResize.pressed
                                  || topResize.pressed
    readonly property real collapsedHeight: headerRow.implicitHeight + 20

    width: 320
    height: 280

    z: engaged ? 40 : (livePinned ? 24 : 12)
    scale: engaged ? 1.01 : 1.0
    opacity: root.revealProgress

    Behavior on x {
        enabled: !root.engaged
        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
    }
    Behavior on y {
        enabled: !root.engaged
        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
    }
    Behavior on width {
        enabled: !root.engaged
        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
    }
    Behavior on height {
        enabled: !root.engaged
        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
    }
    Behavior on scale {
        NumberAnimation { duration: 140; easing.type: Easing.InOutQuad }
    }
    Behavior on opacity {
        NumberAnimation { duration: 180; easing.type: Easing.InOutQuad }
    }

    transform: [
        Translate {
            x: (1 - root.revealProgress) * root.revealOffsetX
            y: (1 - root.revealProgress) * root.revealOffsetY
        }
    ]

    function gridStepX() {
        return root.cellWidth + root.gutter
    }

    function gridStepY() {
        return root.rowHeight + root.gutter
    }

    function clamp(value, low, high) {
        return Math.max(low, Math.min(high, value))
    }

    function rectsOverlap(ax, ay, aw, ah, bx, by, bw, bh) {
        return Math.max(ax, bx) < Math.min(ax + aw, bx + bw) && Math.max(ay, by) < Math.min(ay + ah, by + bh)
    }

    function gridToX(gridX) {
        return gridX * root.gridStepX()
    }

    function gridToY(gridY) {
        return gridY * root.gridStepY()
    }

    function spanToWidth(colSpan) {
        return colSpan * root.cellWidth + Math.max(0, colSpan - 1) * root.gutter
    }

    function spanToHeight(rowSpan) {
        return rowSpan * root.rowHeight + Math.max(0, rowSpan - 1) * root.gutter
    }

    function syncFromModel() {
        if (root.engaged) {
            return
        }
        root.liveGridX = Number((root.panelData || {}).gridX || 0)
        root.liveGridY = Number((root.panelData || {}).gridY || 0)
        root.liveColSpan = Math.max(root.minCols, Number((root.panelData || {}).colSpan || 4))
        root.liveRowSpan = Math.max(root.minRows, Number((root.panelData || {}).rowSpan || 3))
        root.livePinned = Boolean((root.panelData || {}).pinned)
        root.liveCollapsed = Boolean((root.panelData || {}).collapsed)
        root.applyGridGeometry()
    }

    function applyGridGeometry() {
        root.x = root.gridToX(root.liveGridX)
        root.y = root.gridToY(root.liveGridY)
        root.width = root.spanToWidth(root.liveColSpan)
        root.height = root.liveCollapsed ? root.collapsedHeight : root.spanToHeight(root.liveRowSpan)
    }

    function constrainToLayoutBounds() {
        root.x = root.clamp(root.x, 0, Math.max(0, root.layoutWidth - root.width))
        root.y = root.clamp(root.y, 0, Math.max(0, root.layoutHeight - root.height))
        root.width = Math.min(root.width, root.layoutWidth)
        root.height = Math.min(root.height, root.layoutHeight)
    }

    function enforceReservedClearance() {
        if (root.reservedRect.width <= 0 || root.reservedRect.height <= 0) {
            return
        }
        if (!root.rectsOverlap(root.x, root.y, root.width, root.height, root.reservedRect.x, root.reservedRect.y, root.reservedRect.width, root.reservedRect.height)) {
            return
        }

        var shoulderGap = root.gutter
        if (root.edgeHint === "left") {
            root.x = Math.min(root.x, root.reservedRect.x - root.width - shoulderGap)
        } else if (root.edgeHint === "right") {
            root.x = Math.max(root.x, root.reservedRect.x + root.reservedRect.width + shoulderGap)
        } else {
            root.y = Math.max(root.y, root.reservedRect.y + root.reservedRect.height + shoulderGap)
        }
        if (root.rectsOverlap(root.x, root.y, root.width, root.height, root.reservedRect.x, root.reservedRect.y, root.reservedRect.width, root.reservedRect.height)) {
            root.y = Math.max(root.y, root.reservedRect.y + root.reservedRect.height + shoulderGap)
        }
    }

    function normalizeLiveGeometry() {
        if (root.normalizingGeometry) {
            return
        }
        root.normalizingGeometry = true
        root.constrainToLayoutBounds()
        root.enforceReservedClearance()
        root.constrainToLayoutBounds()
        root.normalizingGeometry = false
    }

    function commitGeometry() {
        root.normalizeLiveGeometry()
        var maxGridX = Math.max(0, root.gridColumns - root.liveColSpan)
        var maxGridY = Math.max(0, root.gridRows - root.liveRowSpan)
        root.liveGridX = root.clamp(Math.round(root.x / root.gridStepX()), 0, maxGridX)
        root.liveGridY = root.clamp(Math.round(root.y / root.gridStepY()), 0, maxGridY)
        root.liveColSpan = root.clamp(Math.round((root.width + root.gutter) / root.gridStepX()), root.minCols, root.gridColumns)
        root.liveRowSpan = root.clamp(Math.round((Math.max(root.height, root.collapsedHeight) + root.gutter) / root.gridStepY()), root.minRows, root.gridRows)
        root.applyGridGeometry()
        root.gridCommitted(String((root.panelData || {}).panelId || ""), root.liveGridX, root.liveGridY, root.liveColSpan, root.liveRowSpan)
    }

    onPanelDataChanged: syncFromModel()
    onCellWidthChanged: applyGridGeometry()
    onRowHeightChanged: applyGridGeometry()
    onGutterChanged: applyGridGeometry()
    onXChanged: if (root.engaged) { root.normalizeLiveGeometry() }
    onYChanged: if (root.engaged) { root.normalizeLiveGeometry() }
    onWidthChanged: if (root.engaged) { root.normalizeLiveGeometry() }
    onHeightChanged: if (root.engaged) { root.normalizeLiveGeometry() }
    Component.onCompleted: syncFromModel()

    FieldSurface {
        anchors.fill: parent
        radius: 28
        padding: 14
        tintColor: "#101922"
        edgeColor: root.engaged ? "#82c8df" : (root.livePinned ? "#72b7cb" : "#5b8396")
        glowColor: root.engaged ? "#a8e9ff" : "#80c6dd"
        fillOpacity: root.engaged ? 0.86 : 0.74
        edgeOpacity: root.engaged ? 0.34 : 0.24
        lineOpacity: root.engaged ? 0.1 : 0.06
        accentTopLine: false

        ColumnLayout {
            anchors.fill: parent
            spacing: 10

            Rectangle {
                id: headerBar
                Layout.fillWidth: true
                implicitHeight: headerRow.implicitHeight + 8
                radius: 18
                color: Qt.rgba(0.07, 0.12, 0.16, root.engaged ? 0.38 : 0.24)
                border.width: 1
                border.color: Qt.rgba(0.47, 0.74, 0.84, root.engaged ? 0.34 : 0.18)

                RowLayout {
                    id: headerRow
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 8

                    Row {
                        spacing: 4

                        Repeater {
                            model: 3

                            delegate: Rectangle {
                                width: 4
                                height: 12
                                radius: 2
                                color: "#6d95a8"
                                opacity: 0.45 + index * 0.08
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1

                        Text {
                            text: String((root.panelData || {}).title || "")
                            color: "#edf7fb"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 12
                            font.letterSpacing: 1.1
                            elide: Text.ElideRight
                        }

                        Text {
                            text: String((root.panelData || {}).subtitle || "")
                            visible: text.length > 0
                            color: "#86a2af"
                            font.family: "Segoe UI"
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                    }

                    Row {
                        id: headerButtons
                        z: 3
                        spacing: 6

                        Rectangle {
                            width: 22
                            height: 22
                            radius: 11
                            color: root.livePinned ? "#173a4d" : "#10181f"
                            border.width: 1
                            border.color: root.livePinned ? "#8fd6ec" : "#476577"

                            Text {
                                anchors.centerIn: parent
                                text: "P"
                                color: "#e6f3f9"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 10
                            }

                            MouseArea {
                                anchors.fill: parent
                                preventStealing: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.pinnedChangedRequested(String((root.panelData || {}).panelId || ""), !root.livePinned)
                            }
                        }

                        Rectangle {
                            width: 22
                            height: 22
                            radius: 11
                            color: root.liveCollapsed ? "#173a4d" : "#10181f"
                            border.width: 1
                            border.color: root.liveCollapsed ? "#8fd6ec" : "#476577"

                            Text {
                                anchors.centerIn: parent
                                text: root.liveCollapsed ? "+" : "-"
                                color: "#e6f3f9"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 12
                            }

                            MouseArea {
                                anchors.fill: parent
                                preventStealing: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.collapsedChangedRequested(String((root.panelData || {}).panelId || ""), !root.liveCollapsed)
                            }
                        }

                        Rectangle {
                            width: 22
                            height: 22
                            radius: 11
                            color: "#10181f"
                            border.width: 1
                            border.color: "#476577"

                            Text {
                                anchors.centerIn: parent
                                text: "x"
                                color: "#e6f3f9"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 10
                            }

                            MouseArea {
                                anchors.fill: parent
                                preventStealing: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.hiddenChangedRequested(String((root.panelData || {}).panelId || ""), true)
                            }
                        }
                    }
                }

                MouseArea {
                    id: dragArea
                    z: 1
                    x: 8
                    y: 0
                    width: Math.max(0, headerBar.width - headerButtons.width - 28)
                    height: parent.height
                    drag.target: root
                    drag.axis: Drag.XAndYAxis
                    drag.minimumX: 0
                    drag.minimumY: 0
                    drag.maximumX: Math.max(0, root.layoutWidth - root.width)
                    drag.maximumY: Math.max(0, root.layoutHeight - root.height)
                    cursorShape: Qt.OpenHandCursor
                    onPressed: cursorShape = Qt.ClosedHandCursor
                    onReleased: {
                        cursorShape = Qt.OpenHandCursor
                        root.commitGeometry()
                    }
                }
            }

            Item {
                id: contentHost
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: !root.liveCollapsed
                clip: true
            }
        }
    }

    MouseArea {
        id: rightResize
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        width: 10
        hoverEnabled: true
        cursorShape: Qt.SizeHorCursor
        property real startWidth: 0
        property real startMouseX: 0
        onPressed: function(mouse) {
            startWidth = root.width
            startMouseX = mouse.x
        }
        onPositionChanged: function(mouse) {
            if (pressed) {
                root.width = Math.max(root.spanToWidth(root.minCols), startWidth + mouse.x - startMouseX)
            }
        }
        onReleased: root.commitGeometry()
    }

    MouseArea {
        id: bottomResize
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 10
        hoverEnabled: true
        cursorShape: Qt.SizeVerCursor
        property real startHeight: 0
        property real startMouseY: 0
        onPressed: function(mouse) {
            startHeight = root.height
            startMouseY = mouse.y
        }
        onPositionChanged: function(mouse) {
            if (pressed) {
                root.height = Math.max(root.spanToHeight(root.minRows), startHeight + mouse.y - startMouseY)
            }
        }
        onReleased: root.commitGeometry()
    }

    MouseArea {
        id: cornerResize
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: 18
        height: 18
        hoverEnabled: true
        cursorShape: Qt.SizeFDiagCursor
        property real startWidth: 0
        property real startHeight: 0
        property real startMouseX: 0
        property real startMouseY: 0
        onPressed: function(mouse) {
            startWidth = root.width
            startHeight = root.height
            startMouseX = mouse.x
            startMouseY = mouse.y
        }
        onPositionChanged: function(mouse) {
            if (pressed) {
                root.width = Math.max(root.spanToWidth(root.minCols), startWidth + mouse.x - startMouseX)
                root.height = Math.max(root.spanToHeight(root.minRows), startHeight + mouse.y - startMouseY)
            }
        }
        onReleased: root.commitGeometry()
    }

    MouseArea {
        id: leftResize
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 10
        hoverEnabled: true
        cursorShape: Qt.SizeHorCursor
        property real startWidth: 0
        property real startX: 0
        property real startMouseX: 0
        onPressed: function(mouse) {
            startWidth = root.width
            startX = root.x
            startMouseX = mouse.x
        }
        onPositionChanged: function(mouse) {
            if (pressed) {
                var delta = mouse.x - startMouseX
                var nextWidth = Math.max(root.spanToWidth(root.minCols), startWidth - delta)
                var widthDelta = nextWidth - startWidth
                root.x = Math.max(0, startX - widthDelta)
                root.width = nextWidth
            }
        }
        onReleased: root.commitGeometry()
    }

    MouseArea {
        id: topResize
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 10
        hoverEnabled: true
        cursorShape: Qt.SizeVerCursor
        property real startHeight: 0
        property real startY: 0
        property real startMouseY: 0
        onPressed: function(mouse) {
            startHeight = root.height
            startY = root.y
            startMouseY = mouse.y
        }
        onPositionChanged: function(mouse) {
            if (pressed) {
                var delta = mouse.y - startMouseY
                var nextHeight = Math.max(root.spanToHeight(root.minRows), startHeight - delta)
                var heightDelta = nextHeight - startHeight
                root.y = Math.max(0, startY - heightDelta)
                root.height = nextHeight
            }
        }
        onReleased: root.commitGeometry()
    }
}
