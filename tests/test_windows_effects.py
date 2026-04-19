from stormhelm.ui.windows_effects import (
    ACCENT_DISABLED,
    ACCENT_ENABLE_BLURBEHIND,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TRANSPARENT,
    exstyle_for_mode,
    material_profile,
)


def test_material_profile_keeps_ghost_lighter_than_deck() -> None:
    ghost = material_profile(ghost_mode=True)
    deck = material_profile(ghost_mode=False)

    assert ghost.accent_state == ACCENT_DISABLED
    assert deck.accent_state == ACCENT_ENABLE_BLURBEHIND
    assert ghost.gradient_color != deck.gradient_color
    assert ghost.edge_alpha < deck.edge_alpha
    assert ghost.extend_frame is False
    assert deck.extend_frame is False


def test_material_profile_uses_shared_accent_flags() -> None:
    ghost = material_profile(ghost_mode=True)
    deck = material_profile(ghost_mode=False)

    assert ghost.accent_flags == deck.accent_flags == (0x20 | 0x40 | 0x80)


def test_material_profile_keeps_ghost_far_lighter_than_deck() -> None:
    ghost = material_profile(ghost_mode=True)
    deck = material_profile(ghost_mode=False)

    assert (ghost.gradient_color >> 24) == 0x00
    assert 0x08 <= (deck.gradient_color >> 24) <= 0x18
    assert ghost.edge_alpha == 0x00


def test_exstyle_for_mode_makes_ghost_click_through() -> None:
    ghost_add, ghost_clear = exstyle_for_mode(ghost_mode=True)
    deck_add, deck_clear = exstyle_for_mode(ghost_mode=False)

    assert ghost_add & WS_EX_LAYERED
    assert ghost_add & WS_EX_TRANSPARENT
    assert ghost_add & WS_EX_NOACTIVATE
    assert ghost_clear == 0

    assert deck_add & WS_EX_LAYERED
    assert deck_clear & WS_EX_TRANSPARENT
    assert deck_clear & WS_EX_NOACTIVATE
