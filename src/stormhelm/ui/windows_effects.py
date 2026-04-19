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
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SWP_NOACTIVATE = 0x0010


@dataclass(frozen=True)
class MaterialProfile:
    accent_state: int
    gradient_color: int
    edge_alpha: int
    accent_flags: int = 0x20 | 0x40 | 0x80
    extend_frame: bool = False


def _gradient_color(alpha: int, red: int, green: int, blue: int) -> int:
    return ((alpha & 0xFF) << 24) | ((blue & 0xFF) << 16) | ((green & 0xFF) << 8) | (red & 0xFF)


def material_profile(ghost_mode: bool) -> MaterialProfile:
    if ghost_mode:
        return MaterialProfile(
            accent_state=ACCENT_DISABLED,
            gradient_color=_gradient_color(0x00, 0x00, 0x00, 0x00),
            edge_alpha=0x00,
            extend_frame=False,
        )
    return MaterialProfile(
        accent_state=ACCENT_ENABLE_BLURBEHIND,
        gradient_color=_gradient_color(0x12, 0x08, 0x10, 0x16),
        edge_alpha=0x12,
        extend_frame=False,
    )


def exstyle_for_mode(ghost_mode: bool) -> tuple[int, int]:
    base = WS_EX_LAYERED
    if ghost_mode:
        return base | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE, 0
    return base, WS_EX_TRANSPARENT | WS_EX_NOACTIVATE


def apply_window_interaction_mode(window: QtGui.QWindow, *, ghost_mode: bool) -> str:
    if not sys.platform.startswith("win"):
        return "unsupported"

    hwnd = int(window.winId())
    user32 = ctypes.windll.user32
    get_window_long_ptr = getattr(user32, "GetWindowLongPtrW", None)
    set_window_long_ptr = getattr(user32, "SetWindowLongPtrW", None)
    if get_window_long_ptr is None or set_window_long_ptr is None:
        return "missing-style-api"

    add_bits, clear_bits = exstyle_for_mode(ghost_mode=ghost_mode)
    current = int(get_window_long_ptr(hwnd, GWL_EXSTYLE))
    updated = (current | add_bits) & ~clear_bits
    if updated != current:
        set_window_long_ptr(hwnd, GWL_EXSTYLE, updated)
        user32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE,
        )
    return "applied"


def apply_stormhelm_material(window: QtGui.QWindow, *, ghost_mode: bool) -> str:
    if not sys.platform.startswith("win"):
        return "unsupported"

    hwnd = int(window.winId())
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    profile = material_profile(ghost_mode=ghost_mode)
    margins = MARGINS(-1, -1, -1, -1) if profile.extend_frame else MARGINS(0, 0, 0, 0)
    try:
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
    except Exception:
        pass
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
