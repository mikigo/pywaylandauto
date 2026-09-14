"""X11 keysym names — without the XK_ prefix, case-insensitive, with aliases.

Single characters resolve via their codepoint: Latin-1 (U+0020..U+00FF)
maps to the codepoint itself (X11 Latin-1 keysyms), anything beyond maps to
the X11 Unicode keysym 0x01000000 | codepoint.
"""

_KEYSYMS: dict[str, int] = {
    # specials
    "return": 0xFF0D,
    "enter": 0xFF0D,
    "tab": 0xFF09,
    "escape": 0xFF1B,
    "esc": 0xFF1B,
    "backspace": 0xFF08,
    "delete": 0xFFFF,
    "del": 0xFFFF,
    "insert": 0xFF63,
    "print": 0xFF61,
    "pause": 0xFF13,
    "menu": 0xFF67,
    # navigation
    "left": 0xFF51,
    "up": 0xFF52,
    "right": 0xFF53,
    "down": 0xFF54,
    "home": 0xFF50,
    "end": 0xFF57,
    "page_up": 0xFF55,
    "page_down": 0xFF56,
    "pgup": 0xFF55,
    "pgdn": 0xFF56,
    # function keys
    **{f"f{i}": 0xFFBE + i - 1 for i in range(1, 13)},
    # modifiers
    "control_l": 0xFFE3,
    "control_r": 0xFFE4,
    "ctrl": 0xFFE3,
    "control": 0xFFE3,
    "shift_l": 0xFFE1,
    "shift_r": 0xFFE2,
    "shift": 0xFFE1,
    "alt_l": 0xFFE9,
    "alt_r": 0xFFEA,
    "alt": 0xFFE9,
    "super_l": 0xFFEB,
    "super_r": 0xFFEC,
    "super": 0xFFEB,
    "win": 0xFFEB,
    "cmd": 0xFFEB,
    "meta_l": 0xFFE7,
    "meta_r": 0xFFE8,
    "meta": 0xFFE7,
    # locks
    "caps_lock": 0xFFE5,
    "num_lock": 0xFF7F,
    "scroll_lock": 0xFF14,
    # spacing
    "space": 0x20,
    "spacebar": 0x20,
    # punctuation convenience (ASCII chars resolve by ord() anyway)
    "plus": 0x2B,
    "minus": 0x2D,
    "comma": 0x2C,
    "period": 0x2E,
    "semicolon": 0x3B,
    "slash": 0x2F,
    "backslash": 0x5C,
    "quoteleft": 0x60,
    "quoteright": 0x27,
}

KEYSYMS: dict[str, int] = dict(_KEYSYMS)  # public, mutable copy

# X11 Unicode keysym base: 0x01000000 + codepoint.
UNICODE_BASE = 0x01000000


def lookup(name: str | int) -> int | None:
    """Resolve a keysym name (or int keysym) to an int keysym, or None."""
    if isinstance(name, int):
        return name if 0 <= name <= 0xFFFFFFFF else None
    if not isinstance(name, str):
        return None
    if len(name) == 1:
        # Single characters resolve by their own codepoint — case matters
        # here ("A" != "a"), unlike for named keysyms.
        codepoint = ord(name)
        if codepoint <= 0xFF:
            return codepoint
        if codepoint <= 0x10FFFF:
            return UNICODE_BASE + codepoint
    key = name.lower()
    if key in KEYSYMS:
        return KEYSYMS[key]
    if key.startswith("0x"):
        try:
            value = int(key, 16)
        except ValueError:
            return None
        if 0 <= value <= 0xFFFFFFFF:
            return value
    return None
