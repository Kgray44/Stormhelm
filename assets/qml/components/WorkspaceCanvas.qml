import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root

    signal activateOpenedItem(string itemId)
    signal closeOpenedItem(string itemId)
    property bool panelMode: false

    property var canvasData: ({
        eyebrow: "",
        title: "",
        summary: "",
        body: "",
        viewKind: "overview",
        stats: [],
        factGroups: [],
        lanes: [],
        networkDisplay: ({}),
        timeline: [],
        items: [],
        highlights: [],
        panels: [],
        taskGroups: [],
        chips: [],
        columns: [],
        openedItems: [],
        activeItem: ({})
    })
    readonly property var safeData: root.canvasData || ({
        eyebrow: "",
        title: "",
        summary: "",
        body: "",
        viewKind: "overview",
        stats: [],
        factGroups: [],
        lanes: [],
        networkDisplay: ({}),
        timeline: [],
        items: [],
        highlights: [],
        panels: [],
        taskGroups: [],
        chips: [],
        columns: [],
        openedItems: [],
        activeItem: ({})
    })
    readonly property var activeItem: root.safeData.activeItem || ({})
    readonly property bool showWorkspaceItem: {
        var section = root.safeData.sectionKey || ""
        return (root.safeData.openedItems || []).length > 0
                && ["opened-items", "open-pages", "working-set"].indexOf(section) >= 0
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: root.panelMode ? 12 : 18

        ColumnLayout {
            Layout.fillWidth: true
            spacing: root.panelMode ? 4 : 6

            Text {
                text: root.safeData.eyebrow
                color: "#b58a62"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: 11
                font.letterSpacing: 1.8
                visible: text.length > 0
            }

            Text {
                text: root.safeData.title
                color: "#edf7fb"
                font.family: "Bahnschrift SemiCondensed"
                font.pixelSize: root.panelMode ? 22 : 29
                font.letterSpacing: 1.1
            }

            Text {
                text: root.safeData.summary
                color: "#c7dbe5"
                font.family: "Segoe UI Semibold"
                font.pixelSize: root.panelMode ? 13 : 15
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            Text {
                text: root.safeData.body
                color: "#8ea8b4"
                font.family: "Segoe UI"
                font.pixelSize: root.panelMode ? 12 : 13
                wrapMode: Text.Wrap
                lineHeight: 1.24
                Layout.fillWidth: true
                visible: !root.panelMode || text.length < 180
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 8
            visible: root.safeData.chips.length > 0

            Repeater {
                model: root.safeData.chips

                delegate: Rectangle {
                    required property var modelData
                    radius: 13
                    color: "#0f1c25"
                    border.width: 1
                    border.color: "#2f526171"
                    height: 28
                    width: chipRow.implicitWidth + 20
                    opacity: 0.9

                    Row {
                        id: chipRow
                        anchors.centerIn: parent
                        spacing: 7

                        Text {
                            text: modelData.label
                            color: "#7f9cab"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 10
                            font.letterSpacing: 1.2
                        }

                        Text {
                            text: modelData.value
                            color: "#e2f1f8"
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        Loader {
            Layout.fillWidth: true
            Layout.fillHeight: true
            sourceComponent: {
                if (root.showWorkspaceItem)
                    return workspaceItemComponent
                switch (root.safeData.viewKind || "overview") {
                case "facts":
                    return factsComponent
                case "watch":
                    return watchComponent
                case "signals":
                case "thread":
                    return timelineComponent
                case "collection":
                case "notes":
                    return collectionComponent
                case "findings":
                    return findingsComponent
                case "session":
                    return sessionComponent
                case "tasks":
                    return tasksComponent
                default:
                    return overviewComponent
                }
            }
        }
    }

    Component {
        id: workspaceItemComponent

        ColumnLayout {
            spacing: 12

            OpenedItemsStrip {
                Layout.fillWidth: true
                items: root.safeData.openedItems
                activeItemId: root.activeItem.itemId || ""
                onActivateItem: function(itemId) { root.activateOpenedItem(itemId) }
                onCloseItem: function(itemId) { root.closeOpenedItem(itemId) }
            }

            Loader {
                Layout.fillWidth: true
                Layout.fillHeight: true
                sourceComponent: root.activeItem.viewer === "browser" ? browserComponent : fileComponent
            }
        }
    }

    Component {
        id: browserComponent

        BrowserSurface {
            itemData: root.activeItem
        }
    }

    Component {
        id: fileComponent

        FileViewerSurface {
            itemData: root.activeItem
        }
    }

    Component {
        id: overviewComponent

        RowLayout {
            spacing: 20

            Repeater {
                model: root.safeData.columns

                delegate: Item {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 1

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 12

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3

                            Text {
                                text: modelData.title
                                color: "#d9e9f1"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 16
                                font.letterSpacing: 1.1
                            }

                            Text {
                                text: modelData.summary
                                color: "#7f99a6"
                                font.family: "Segoe UI"
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            height: 1
                            color: "#315062"
                            opacity: 0.34
                        }

                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 10
                            model: modelData.entries

                            delegate: Item {
                                required property var modelData
                                width: ListView.view.width
                                height: entryColumn.implicitHeight + 10

                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    height: 1
                                    color: "#284556"
                                    opacity: 0.22
                                }

                                Column {
                                    id: entryColumn
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    spacing: 4

                                    Text {
                                        text: modelData.primary
                                        width: parent.width
                                        color: "#eef7fb"
                                        font.family: "Segoe UI Semibold"
                                        font.pixelSize: 13
                                        wrapMode: Text.Wrap
                                    }

                                    Text {
                                        text: modelData.secondary
                                        width: parent.width
                                        color: "#88a4b1"
                                        font.family: "Bahnschrift SemiCondensed"
                                        font.pixelSize: 10
                                        font.letterSpacing: 1.2
                                        wrapMode: Text.Wrap
                                    }

                                    Text {
                                        text: modelData.detail
                                        visible: text.length > 0
                                        width: parent.width
                                        color: "#b7cbd5"
                                        font.family: "Segoe UI"
                                        font.pixelSize: 12
                                        wrapMode: Text.Wrap
                                        lineHeight: 1.22
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: factsComponent

        ColumnLayout {
            spacing: 16

            Flow {
                Layout.fillWidth: true
                spacing: 10
                visible: (root.safeData.stats || []).length > 0

                Repeater {
                    model: root.safeData.stats || []

                    delegate: Rectangle {
                        required property var modelData
                        radius: 16
                        color: "#10202a"
                        border.width: 1
                        border.color: "#345767"
                        height: 38
                        width: statRow.implicitWidth + 24

                        Row {
                            id: statRow
                            anchors.centerIn: parent
                            spacing: 8

                            Text {
                                text: modelData.label
                                color: "#86a2af"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 10
                                font.letterSpacing: 1.3
                            }

                            Text {
                                text: modelData.value
                                color: "#edf7fb"
                                font.family: "Segoe UI Semibold"
                                font.pixelSize: 12
                            }
                        }
                    }
                }
            }
            NetworkHealthSurface {
                Layout.fillWidth: true
                visible: Boolean((root.safeData.networkDisplay || {}).available)
                displayData: root.safeData.networkDisplay || ({})
                panelMode: root.panelMode
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 14
                model: root.safeData.factGroups || []

                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width
                    height: factColumn.implicitHeight + 18
                    radius: 20
                    color: "#0f1b24"
                    border.width: 1
                    border.color: "#315060"
                    opacity: 0.9

                    ColumnLayout {
                        id: factColumn
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 10

                        Text {
                            text: modelData.title
                            color: "#e3f1f7"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 17
                            font.letterSpacing: 1.0
                        }

                        Text {
                            text: modelData.summary
                            color: "#86a0ae"
                            font.family: "Segoe UI"
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }

                        Repeater {
                            model: modelData.rows || []

                            delegate: RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 12

                                Text {
                                    Layout.preferredWidth: 118
                                    text: modelData.label
                                    color: "#7d99a8"
                                    font.family: "Bahnschrift SemiCondensed"
                                    font.pixelSize: 11
                                    font.letterSpacing: 1.1
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        text: modelData.value
                                        color: "#eef7fb"
                                        font.family: "Segoe UI Semibold"
                                        font.pixelSize: 12
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                    }

                                    Text {
                                        text: modelData.detail
                                        visible: text.length > 0
                                        color: "#9db4c0"
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
            }
        }
    }

    Component {
        id: watchComponent

        ColumnLayout {
            spacing: 16

            Flow {
                Layout.fillWidth: true
                spacing: 10
                visible: (root.safeData.stats || []).length > 0

                Repeater {
                    model: root.safeData.stats || []

                    delegate: Rectangle {
                        required property var modelData
                        radius: 16
                        color: "#111d27"
                        border.width: 1
                        border.color: "#35586b"
                        height: 38
                        width: statRow.implicitWidth + 24

                        Row {
                            id: statRow
                            anchors.centerIn: parent
                            spacing: 8

                            Text {
                                text: modelData.label
                                color: "#89a2af"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 10
                                font.letterSpacing: 1.3
                            }

                            Text {
                                text: modelData.value
                                color: "#edf7fb"
                                font.family: "Segoe UI Semibold"
                                font.pixelSize: 12
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 16

                Repeater {
                    model: root.safeData.lanes || []

                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 22
                        color: "#0f1a23"
                        border.width: 1
                        border.color: "#2f5062"
                        opacity: 0.92

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 10

                            Text {
                                text: modelData.title
                                color: "#e5f2f8"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 16
                            }

                            Text {
                                text: modelData.summary
                                color: "#849fad"
                                font.family: "Segoe UI"
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }

                            ListView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                spacing: 10
                                model: modelData.entries || []

                                delegate: Column {
                                    required property var modelData
                                    width: ListView.view.width
                                    spacing: 3

                                    Text {
                                        text: modelData.title
                                        width: parent.width
                                        color: "#eef7fb"
                                        font.family: "Segoe UI Semibold"
                                        font.pixelSize: 12
                                        wrapMode: Text.Wrap
                                    }

                                    Text {
                                        text: modelData.eyebrow + (modelData.meta ? "  " + modelData.meta : "")
                                        width: parent.width
                                        color: "#8ba6b4"
                                        font.family: "Bahnschrift SemiCondensed"
                                        font.pixelSize: 10
                                        font.letterSpacing: 1.1
                                        wrapMode: Text.Wrap
                                    }

                                    Text {
                                        text: modelData.detail
                                        width: parent.width
                                        color: "#b9ccd6"
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

    Component {
        id: timelineComponent

        ListView {
            clip: true
            spacing: 12
            model: root.safeData.timeline || []

            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width
                height: timelineColumn.implicitHeight + 18
                radius: 18
                color: "#0f1a23"
                border.width: 1
                border.color: "#305061"
                opacity: 0.9

                ColumnLayout {
                    id: timelineColumn
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 6

                    Text {
                        text: modelData.eyebrow
                        color: "#b58a62"
                        font.family: "Bahnschrift SemiCondensed"
                        font.pixelSize: 10
                        font.letterSpacing: 1.3
                    }

                    Text {
                        text: modelData.title
                        color: "#edf7fb"
                        font.family: "Segoe UI Semibold"
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Text {
                        text: modelData.detail
                        color: "#9bb2bf"
                        font.family: "Segoe UI"
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Text {
                        text: modelData.meta
                        visible: text.length > 0
                        color: "#7d98a6"
                        font.family: "Bahnschrift SemiCondensed"
                        font.pixelSize: 10
                        font.letterSpacing: 1.2
                    }
                }
            }
        }
    }

    Component {
        id: collectionComponent

        ListView {
            clip: true
            spacing: 12
            model: root.safeData.items || []

            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width
                height: itemColumn.implicitHeight + 18
                radius: 18
                color: "#101b24"
                border.width: 1
                border.color: "#325162"
                opacity: 0.92

                ColumnLayout {
                    id: itemColumn
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        Text {
                            Layout.fillWidth: true
                            text: modelData.title
                            color: "#edf7fb"
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                        }

                        Rectangle {
                            radius: 12
                            color: "#173142"
                            border.width: 1
                            border.color: "#5d889b"
                            height: 22
                            width: badgeText.implicitWidth + 16

                            Text {
                                id: badgeText
                                anchors.centerIn: parent
                                text: modelData.badge
                                color: "#d8eaf2"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 10
                                font.letterSpacing: 1.1
                            }
                        }
                    }

                    Text {
                        text: modelData.subtitle
                        color: "#84a0ae"
                        font.family: "Bahnschrift SemiCondensed"
                        font.pixelSize: 10
                        font.letterSpacing: 1.2
                    }

                    Text {
                        text: modelData.role
                        color: "#c8dae3"
                        font.family: "Segoe UI"
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Text {
                        text: modelData.detail
                        color: "#7f98a5"
                        font.family: "Segoe UI"
                        font.pixelSize: 11
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }

    Component {
        id: findingsComponent

        GridLayout {
            columns: width > 720 ? 2 : 1
            rowSpacing: 14
            columnSpacing: 14

            Repeater {
                model: root.safeData.highlights || []

                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 150
                    radius: 20
                    color: "#101b24"
                    border.width: 1
                    border.color: "#315162"
                    opacity: 0.92

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 8

                        Text {
                            text: modelData.source
                            color: "#b58a62"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 10
                            font.letterSpacing: 1.3
                        }

                        Text {
                            text: modelData.title
                            color: "#eef7fb"
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: 14
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }

                        Text {
                            text: modelData.summary
                            color: "#a6bcc7"
                            font.family: "Segoe UI"
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }
    }

    Component {
        id: sessionComponent

        ColumnLayout {
            spacing: 14

            Flow {
                Layout.fillWidth: true
                spacing: 10
                visible: (root.safeData.stats || []).length > 0

                Repeater {
                    model: root.safeData.stats || []

                    delegate: Rectangle {
                        required property var modelData
                        radius: 15
                        color: "#12212b"
                        border.width: 1
                        border.color: "#36596b"
                        height: 34
                        width: badgeRow.implicitWidth + 20

                        Row {
                            id: badgeRow
                            anchors.centerIn: parent
                            spacing: 8

                            Text {
                                text: modelData.label
                                color: "#86a0ae"
                                font.family: "Bahnschrift SemiCondensed"
                                font.pixelSize: 10
                                font.letterSpacing: 1.2
                            }

                            Text {
                                text: modelData.value
                                color: "#eef7fb"
                                font.family: "Segoe UI Semibold"
                                font.pixelSize: 11
                            }
                        }
                    }
                }
            }

            Repeater {
                model: root.safeData.panels || []

                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    radius: 18
                    color: "#101b24"
                    border.width: 1
                    border.color: "#315061"
                    opacity: 0.9
                    implicitHeight: sessionColumn.implicitHeight + 18

                    ColumnLayout {
                        id: sessionColumn
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 8

                        Text {
                            text: modelData.title
                            color: "#e4f2f8"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 15
                        }

                        Text {
                            text: modelData.summary
                            color: "#edf7fb"
                            font.family: "Segoe UI Semibold"
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }

                        Text {
                            text: modelData.detail
                            color: "#9cb4c0"
                            font.family: "Segoe UI"
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }

                        Repeater {
                            model: modelData.entries || []

                            delegate: RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 12

                                Text {
                                    Layout.preferredWidth: 96
                                    text: modelData.label
                                    color: "#7d99a8"
                                    font.family: "Bahnschrift SemiCondensed"
                                    font.pixelSize: 10
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.value
                                    color: "#e3f0f7"
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

    Component {
        id: tasksComponent

        RowLayout {
            spacing: 14

            Repeater {
                model: root.safeData.taskGroups || []

                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 20
                    color: "#101b24"
                    border.width: 1
                    border.color: "#305061"
                    opacity: 0.92

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 10

                        Text {
                            text: modelData.title
                            color: "#e5f2f8"
                            font.family: "Bahnschrift SemiCondensed"
                            font.pixelSize: 15
                        }

                        ListView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 10
                            model: modelData.entries || []

                            delegate: Column {
                                required property var modelData
                                width: ListView.view.width
                                spacing: 4

                                Text {
                                    text: modelData.title
                                    width: parent.width
                                    color: "#eef7fb"
                                    font.family: "Segoe UI Semibold"
                                    font.pixelSize: 12
                                    wrapMode: Text.Wrap
                                }

                                Text {
                                    text: String(modelData.status || "").replace("_", " ")
                                    width: parent.width
                                    color: "#8ca7b5"
                                    font.family: "Bahnschrift SemiCondensed"
                                    font.pixelSize: 10
                                    font.letterSpacing: 1.2
                                    wrapMode: Text.Wrap
                                }

                                Text {
                                    text: modelData.detail
                                    width: parent.width
                                    color: "#b7cbd5"
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
