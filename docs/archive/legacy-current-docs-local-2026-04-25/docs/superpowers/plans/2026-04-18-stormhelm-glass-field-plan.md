# Stormhelm Glass Field And Local Mode Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Stormhelm's abstract oval-and-circle background with a restrained old-ship glass field, and add local `/deck` and `/ghost` commands that switch visible modes instantly without routing through the core assistant flow.

**Architecture:** Keep the existing Ghost-to-Deck transition model and central anchor intact while rebuilding the background as one shared material layer. Split the work into three pieces: UI-local mode command interception in the controller, explicit Windows material profiles in Python, and a new QML glass-field component backed by a compiled ShaderEffect asset that deepens from Ghost to Deck.

**Tech Stack:** Python 3.12, PySide6, Qt Quick/QML, ShaderEffect, Windows blur/acrylic composition APIs, pytest

---

## File Structure

- Modify: `C:\Stormhelm\src\stormhelm\ui\controllers\main_controller.py`
  - Intercept `/deck` and `/ghost` before normal chat send and keep the behavior local to the UI shell.
- Create: `C:\Stormhelm\tests\test_main_controller.py`
  - Cover local mode command interception and regression for normal chat send.
- Modify: `C:\Stormhelm\src\stormhelm\ui\windows_effects.py`
  - Introduce explicit Ghost-vs-Deck material profiles instead of inline magic values.
- Create: `C:\Stormhelm\tests\test_windows_effects.py`
  - Verify Ghost stays lighter and Deck stays deeper at the support-layer level.
- Create: `C:\Stormhelm\assets\qml\components\GlassFieldLayer.qml`
  - Own the sea-worn glass rendering inputs and expose a testable `objectName`.
- Create: `C:\Stormhelm\assets\qml\shaders\ship_glass.frag`
  - Source fragment shader for restrained refraction, pane drift, and old-glass surface behavior.
- Create: `C:\Stormhelm\assets\qml\shaders\ship_glass.frag.qsb`
  - Compiled shader asset consumed by `ShaderEffect`.
- Modify: `C:\Stormhelm\assets\qml\components\StormBackground.qml`
  - Remove the abstract ovals/circles and orchestrate the new shared glass field.
- Create: `C:\Stormhelm\tests\test_qml_shell.py`
  - Smoke-test that the main shell still loads and that the shared glass field is present in both Ghost and Deck.

## Task 1: Intercept `/deck` And `/ghost` Locally

**Files:**
- Create: `C:\Stormhelm\tests\test_main_controller.py`
- Modify: `C:\Stormhelm\src\stormhelm\ui\controllers\main_controller.py`
- Test: `C:\Stormhelm\tests\test_main_controller.py`

- [ ] **Step 1: Write the failing controller tests**

```python
from __future__ import annotations

from PySide6 import QtCore

from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.controllers.main_controller import MainController


class DummyClient(QtCore.QObject):
    error_occurred = QtCore.Signal(str, str)
    snapshot_received = QtCore.Signal(dict)
    health_received = QtCore.Signal(dict)
    chat_received = QtCore.Signal(dict)
    note_saved = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.sent_messages: list[str] = []
        self.saved_notes: list[tuple[str, str]] = []
        self.snapshot_calls = 0

    def fetch_snapshot(self) -> None:
        self.snapshot_calls += 1

    def send_message(self, message: str) -> None:
        self.sent_messages.append(message)

    def save_note(self, title: str, content: str) -> None:
        self.saved_notes.append((title, content))


def test_main_controller_intercepts_local_deck_command(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._send_message("/deck")

    assert bridge.mode_value == "deck"
    assert bridge.statusLine == "Command Deck unfolded."
    assert client.sent_messages == []


def test_main_controller_intercepts_local_ghost_command(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)
    bridge.setMode("deck")

    controller._send_message("/ghost")

    assert bridge.mode_value == "ghost"
    assert bridge.statusLine == "Ghost Mode holding steady."
    assert client.sent_messages == []


def test_main_controller_still_sends_normal_messages(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._send_message("plot a safe course")

    assert client.sent_messages == ["plot a safe course"]
```

- [ ] **Step 2: Run the controller test to verify it fails**

Run: `C:\Stormhelm\.venv\Scripts\python.exe -m pytest C:\Stormhelm\tests\test_main_controller.py -q`

Expected: FAIL because `MainController._send_message()` currently forwards `/deck` and `/ghost` to `client.send_message()` instead of switching UI modes locally.

- [ ] **Step 3: Implement minimal local mode command handling**

```python
from __future__ import annotations

from PySide6 import QtCore

from stormhelm.app.launcher import ensure_core_running
from stormhelm.config.models import AppConfig
from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.client import CoreApiClient


class MainController(QtCore.QObject):
    def __init__(self, *, config: AppConfig, bridge: UiBridge, client: CoreApiClient) -> None:
        super().__init__(bridge)
        self.config = config
        self.bridge = bridge
        self.client = client
        self._core_online = False

        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setInterval(self.config.ui.poll_interval_ms)
        self.refresh_timer.timeout.connect(self.poll)

        self.bridge.sendMessageRequested.connect(self._send_message)
        self.bridge.saveNoteRequested.connect(self._save_note)

        self.client.error_occurred.connect(self._handle_error)
        self.client.snapshot_received.connect(self._handle_snapshot)
        self.client.health_received.connect(self._handle_health)
        self.client.chat_received.connect(self._handle_chat)
        self.client.note_saved.connect(self._handle_note_saved)

    def _handle_local_mode_command(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if normalized == "/deck":
            self.bridge.showWindow()
            self.bridge.setMode("deck")
            return True
        if normalized == "/ghost":
            self.bridge.showWindow()
            self.bridge.setMode("ghost")
            return True
        return False

    def _send_message(self, message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        if self._handle_local_mode_command(text):
            return
        self.client.send_message(text)
```

- [ ] **Step 4: Run the controller test to verify it passes**

Run: `C:\Stormhelm\.venv\Scripts\python.exe -m pytest C:\Stormhelm\tests\test_main_controller.py -q`

Expected: PASS with `3 passed`

- [ ] **Step 5: Commit**

```bash
git add C:\Stormhelm\src\stormhelm\ui\controllers\main_controller.py C:\Stormhelm\tests\test_main_controller.py
git commit -m "feat: add local deck and ghost mode commands"
```

## Task 2: Make Ghost And Deck Material Depth Explicit In Python

**Files:**
- Create: `C:\Stormhelm\tests\test_windows_effects.py`
- Modify: `C:\Stormhelm\src\stormhelm\ui\windows_effects.py`
- Test: `C:\Stormhelm\tests\test_windows_effects.py`

- [ ] **Step 1: Write the failing Windows material profile tests**

```python
from stormhelm.ui.windows_effects import (
    ACCENT_ENABLE_ACRYLICBLURBEHIND,
    ACCENT_ENABLE_BLURBEHIND,
    material_profile,
)


def test_material_profile_keeps_ghost_lighter_than_deck() -> None:
    ghost = material_profile(ghost_mode=True)
    deck = material_profile(ghost_mode=False)

    assert ghost.accent_state == ACCENT_ENABLE_BLURBEHIND
    assert deck.accent_state == ACCENT_ENABLE_ACRYLICBLURBEHIND
    assert ghost.gradient_color != deck.gradient_color
    assert ghost.edge_alpha < deck.edge_alpha


def test_material_profile_uses_shared_accent_flags() -> None:
    ghost = material_profile(ghost_mode=True)
    deck = material_profile(ghost_mode=False)

    assert ghost.accent_flags == deck.accent_flags == (0x20 | 0x40 | 0x80)
```

- [ ] **Step 2: Run the Windows effects test to verify it fails**

Run: `C:\Stormhelm\.venv\Scripts\python.exe -m pytest C:\Stormhelm\tests\test_windows_effects.py -q`

Expected: FAIL with `ImportError` or `AttributeError` because `material_profile()` does not exist yet.

- [ ] **Step 3: Introduce explicit Ghost and Deck material profiles**

```python
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

from PySide6 import QtGui


if sys.platform.startswith("win"):
    from ctypes import wintypes

    class ACCENT_POLICY(ctypes.Structure):
        _fields_ = [
            ("AccentState", ctypes.c_int),
            ("AccentFlags", ctypes.c_int),
            ("GradientColor", ctypes.c_uint32),
            ("AnimationId", ctypes.c_int),
        ]


    class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
        _fields_ = [
            ("Attribute", ctypes.c_int),
            ("Data", ctypes.c_void_p),
            ("SizeOfData", ctypes.c_size_t),
        ]


    class MARGINS(ctypes.Structure):
        _fields_ = [
            ("cxLeftWidth", ctypes.c_int),
            ("cxRightWidth", ctypes.c_int),
            ("cyTopHeight", ctypes.c_int),
            ("cyBottomHeight", ctypes.c_int),
        ]


WCA_ACCENT_POLICY = 19
ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


@dataclass(frozen=True)
class MaterialProfile:
    accent_state: int
    gradient_color: int
    edge_alpha: int
    accent_flags: int = 0x20 | 0x40 | 0x80


def _gradient_color(alpha: int, red: int, green: int, blue: int) -> int:
    return ((alpha & 0xFF) << 24) | ((blue & 0xFF) << 16) | ((green & 0xFF) << 8) | (red & 0xFF)


def material_profile(ghost_mode: bool) -> MaterialProfile:
    if ghost_mode:
        return MaterialProfile(
            accent_state=ACCENT_ENABLE_BLURBEHIND,
            gradient_color=_gradient_color(0x24, 0x17, 0x25, 0x31),
            edge_alpha=0x24,
        )
    return MaterialProfile(
        accent_state=ACCENT_ENABLE_ACRYLICBLURBEHIND,
        gradient_color=_gradient_color(0x46, 0x12, 0x1f, 0x2a),
        edge_alpha=0x46,
    )


def apply_stormhelm_material(window: QtGui.QWindow, *, ghost_mode: bool) -> str:
    if not sys.platform.startswith("win"):
        return "unsupported"

    hwnd = int(window.winId())
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    margins = MARGINS(-1, -1, -1, -1)
    try:
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
    except Exception:
        pass

    profile = material_profile(ghost_mode=ghost_mode)
    accent = ACCENT_POLICY()
    accent.AccentState = profile.accent_state
    accent.AccentFlags = profile.accent_flags
    accent.GradientColor = profile.gradient_color
    accent.AnimationId = 0

    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attribute = WCA_ACCENT_POLICY
    data.Data = ctypes.cast(ctypes.byref(accent), ctypes.c_void_p)
    data.SizeOfData = ctypes.sizeof(accent)

    set_window_composition_attribute = getattr(user32, "SetWindowCompositionAttribute", None)
    if set_window_composition_attribute is None:
        return "missing-api"

    result = set_window_composition_attribute(hwnd, ctypes.byref(data))
    return "applied" if result else "failed"
```

- [ ] **Step 4: Run the Windows effects test to verify it passes**

Run: `C:\Stormhelm\.venv\Scripts\python.exe -m pytest C:\Stormhelm\tests\test_windows_effects.py -q`

Expected: PASS with `2 passed`

- [ ] **Step 5: Commit**

```bash
git add C:\Stormhelm\src\stormhelm\ui\windows_effects.py C:\Stormhelm\tests\test_windows_effects.py
git commit -m "refactor: define explicit stormhelm material profiles"
```

## Task 3: Replace The Abstract Background With A Shared Ship-Glass Field

**Files:**
- Create: `C:\Stormhelm\assets\qml\components\GlassFieldLayer.qml`
- Create: `C:\Stormhelm\assets\qml\shaders\ship_glass.frag`
- Create: `C:\Stormhelm\assets\qml\shaders\ship_glass.frag.qsb`
- Create: `C:\Stormhelm\tests\test_qml_shell.py`
- Modify: `C:\Stormhelm\assets\qml\components\StormBackground.qml`
- Test: `C:\Stormhelm\tests\test_qml_shell.py`

- [ ] **Step 1: Write the failing QML shell smoke test**

```python
from __future__ import annotations

import os

from PySide6 import QtCore, QtQml, QtWidgets

from stormhelm.ui.app import resolve_main_qml_path
from stormhelm.ui.bridge import UiBridge


def _ensure_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_main_qml_exposes_shared_glass_field(temp_config) -> None:
    app = _ensure_app()
    bridge = UiBridge(temp_config)
    engine = QtQml.QQmlApplicationEngine()
    engine.rootContext().setContextProperty("stormhelmBridge", bridge)
    engine.rootContext().setContextProperty("stormhelmGhostInput", None)

    engine.load(QtCore.QUrl.fromLocalFile(str(resolve_main_qml_path(temp_config))))

    assert engine.rootObjects()
    root = engine.rootObjects()[0]
    glass = root.findChild(QtCore.QObject, "stormGlassField")
    assert glass is not None
    assert float(glass.property("deckProgress")) == 0.0

    bridge.setMode("deck")
    app.processEvents()

    assert float(glass.property("deckProgress")) == 1.0
```

- [ ] **Step 2: Run the QML shell test to verify it fails**

Run: `C:\Stormhelm\.venv\Scripts\python.exe -m pytest C:\Stormhelm\tests\test_qml_shell.py -q`

Expected: FAIL because the current background has no `stormGlassField` object and still uses the abstract oval-and-circle composition.

- [ ] **Step 3: Create the shared glass field component and shader source**

`C:\Stormhelm\assets\qml\components\GlassFieldLayer.qml`

```qml
import QtQuick 2.15

Item {
    id: root

    objectName: "stormGlassField"

    property string mode: "ghost"
    property real deckProgress: mode === "deck" ? 1 : 0
    property real phase: 0
    property real swell: 0

    NumberAnimation on phase {
        from: 0
        to: 1
        loops: Animation.Infinite
        duration: 24000
    }

    NumberAnimation on swell {
        from: 0
        to: 1
        loops: Animation.Infinite
        duration: 18000
    }

    Rectangle {
        anchors.fill: parent
        color: "#091119"
        opacity: 0.12 + root.deckProgress * 0.16
    }

    ShaderEffect {
        id: glassShader
        anchors.fill: parent
        blending: true

        property real time: root.phase
        property real depth: root.deckProgress
        property vector2d resolution: Qt.vector2d(width, height)

        fragmentShader: Qt.resolvedUrl("../shaders/ship_glass.frag.qsb")
    }

    Rectangle {
        anchors.fill: parent
        color: "#10202a"
        opacity: 0.08 + root.deckProgress * 0.12 + Math.sin(root.swell * Math.PI * 2) * 0.01
    }

    Repeater {
        model: 4

        Rectangle {
            width: parent.width * 0.32
            height: parent.height * 1.2
            x: parent.width * (-0.08 + index * 0.27)
            y: -parent.height * 0.08
            rotation: -4 + index * 2.3
            color: "#7fb6c8"
            opacity: 0.012 + root.deckProgress * 0.03
        }
    }
}
```

`C:\Stormhelm\assets\qml\shaders\ship_glass.frag`

```glsl
#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float depth;
    vec2 resolution;
};

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

void main() {
    vec2 uv = qt_TexCoord0;
    float fieldDepth = mix(0.18, 0.72, depth);

    float waveX = sin((uv.y * 9.0) + time * 6.28318 * 0.35) * 0.0045 * fieldDepth;
    float waveY = cos((uv.x * 8.0) + time * 6.28318 * 0.24) * 0.0035 * fieldDepth;
    vec2 warped = uv + vec2(waveX, waveY);

    float thickGlass = noise(warped * vec2(6.0, 9.0) + vec2(time * 0.4, -time * 0.25));
    float weather = noise(warped * vec2(22.0, 5.0) + vec2(-time * 0.08, time * 0.05));
    float pane = smoothstep(0.44, 0.0, abs(fract(warped.x * 2.15 + 0.08) - 0.5));
    float caustic = smoothstep(0.76, 1.0, sin((warped.y + thickGlass * 0.03) * 34.0 + time * 4.0) * 0.5 + 0.5);

    vec3 base = mix(vec3(0.03, 0.07, 0.09), vec3(0.06, 0.12, 0.15), fieldDepth);
    vec3 tint = base + vec3(0.03, 0.05, 0.06) * thickGlass;
    vec3 paneTint = vec3(0.04, 0.08, 0.10) * pane * (0.15 + fieldDepth * 0.25);
    vec3 causticTint = vec3(0.08, 0.16, 0.18) * caustic * (0.04 + fieldDepth * 0.06);
    vec3 weatherTint = vec3(0.02, 0.03, 0.035) * weather * 0.18;

    float alpha = mix(0.1, 0.33, fieldDepth) + pane * 0.03 + caustic * 0.035;
    fragColor = vec4(tint + paneTint + causticTint + weatherTint, alpha) * qt_Opacity;
}
```

- [ ] **Step 4: Compile the shader asset**

Run: `C:\Stormhelm\.venv\Scripts\pyside6-qsb.exe C:\Stormhelm\assets\qml\shaders\ship_glass.frag -o C:\Stormhelm\assets\qml\shaders\ship_glass.frag.qsb`

Expected: command exits `0` and creates `C:\Stormhelm\assets\qml\shaders\ship_glass.frag.qsb`

- [ ] **Step 5: Replace `StormBackground.qml` with the new shared field orchestrator**

```qml
import QtQuick 2.15

Item {
    id: root

    property string mode: "ghost"
    property real deckProgress: mode === "deck" ? 1 : 0
    property real drift: 0

    NumberAnimation on drift {
        from: 0
        to: 1
        loops: Animation.Infinite
        duration: 30000
    }

    Rectangle {
        anchors.fill: parent
        color: mode === "ghost" ? "#071018" : "#08121a"
        opacity: mode === "ghost" ? 0.08 : 0.16
    }

    GlassFieldLayer {
        anchors.fill: parent
        mode: root.mode
        deckProgress: root.deckProgress
        phase: root.drift
        swell: root.drift
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.03, 0.06, 0.09, mode === "ghost" ? 0.06 : 0.12) }
            GradientStop { position: 0.55; color: Qt.rgba(0.05, 0.09, 0.12, mode === "ghost" ? 0.04 : 0.1) }
            GradientStop { position: 1.0; color: Qt.rgba(0.02, 0.04, 0.06, mode === "ghost" ? 0.07 : 0.16) }
        }
    }

    Repeater {
        model: mode === "ghost" ? 2 : 5

        Rectangle {
            width: parent.width * (0.18 + index * 0.08)
            height: 1
            x: parent.width * 0.08
            y: parent.height * (0.18 + index * 0.14) + Math.sin(root.drift * 6.28318 + index) * 2
            color: "#81b8cb"
            opacity: mode === "ghost" ? 0.018 : 0.045
        }
    }
}
```

- [ ] **Step 6: Run the QML shell test to verify it passes**

Run: `C:\Stormhelm\.venv\Scripts\python.exe -m pytest C:\Stormhelm\tests\test_qml_shell.py -q`

Expected: PASS with `1 passed`

- [ ] **Step 7: Run the focused regression slice**

Run: `C:\Stormhelm\.venv\Scripts\python.exe -m pytest C:\Stormhelm\tests\test_main_controller.py C:\Stormhelm\tests\test_windows_effects.py C:\Stormhelm\tests\test_qml_shell.py C:\Stormhelm\tests\test_ghost_input.py C:\Stormhelm\tests\test_ui_bridge.py -q`

Expected: PASS with all focused UI tests green

- [ ] **Step 8: Commit**

```bash
git add C:\Stormhelm\assets\qml\components\GlassFieldLayer.qml C:\Stormhelm\assets\qml\components\StormBackground.qml C:\Stormhelm\assets\qml\shaders\ship_glass.frag C:\Stormhelm\assets\qml\shaders\ship_glass.frag.qsb C:\Stormhelm\tests\test_qml_shell.py
git commit -m "feat: rebuild stormhelm background as ship glass field"
```

## Manual Verification Checklist

- [ ] Launch Stormhelm with `powershell -ExecutionPolicy Bypass -File .\scripts\run_ui.ps1`
- [ ] Confirm Ghost still feels spectral and lightly tinted rather than mostly opaque
- [ ] Press `Ctrl+Space`, type a message, and verify Ghost capture still works
- [ ] Send `/deck` and confirm the mode deepens immediately without a chat reply
- [ ] Send `/ghost` and confirm the mode recedes immediately without a chat reply
- [ ] Compare Ghost vs Deck visually and confirm Deck has noticeably deeper glass, blur, and distortion
- [ ] Check that the old giant oval/circle background language is gone
