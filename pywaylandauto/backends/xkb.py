"""Minimal xkb_keymap text parser: keysym -> (keycode, level).

The EIS keyboard delivers the XKB keymap (xkb_keymap text format) and takes
evdev keycodes, so keysym-to-keycode translation happens client-side.  If the
keymap is missing or unparseable (e.g. binary keymaps), a built-in US evdev
table is the fallback.
"""

import logging
import re

from ..keysyms import UNICODE_BASE, lookup as lookup_keysym

log = logging.getLogger(__name__)

# X11 keysym names used in xkb_symbols sections (beyond plain characters).
SYMBOL_NAMES: dict[str, int] = {
    "exclam": 0x21, "at": 0x40, "numbersign": 0x23, "dollar": 0x24,
    "percent": 0x25, "asciicircum": 0x5E, "ampersand": 0x26,
    "asterisk": 0x2A, "parenleft": 0x28, "parenright": 0x29,
    "minus": 0x2D, "underscore": 0x5F, "equal": 0x3D, "plus": 0x2B,
    "bracketleft": 0x5B, "braceleft": 0x7B, "bracketright": 0x5D,
    "braceright": 0x7D, "semicolon": 0x3B, "colon": 0x3A,
    "apostrophe": 0x27, "quotedbl": 0x22, "grave": 0x60,
    "asciitilde": 0x7E, "backslash": 0x5C, "bar": 0x7C, "comma": 0x2C,
    "less": 0x3C, "period": 0x2E, "greater": 0x3E, "slash": 0x2F,
    "question": 0x3F, "space": 0x20,
}

_UNICODE_RE = re.compile(r"^U\+?([0-9a-fA-F]{1,6})$")
_KEYCODE_RE = re.compile(r"<\s*([A-Za-z0-9_]+)\s*>\s*=\s*(\d+)")
_ALIAS_RE = re.compile(r"alias\s*<\s*([A-Za-z0-9_]+)\s*>\s*=\s*<\s*([A-Za-z0-9_]+)\s*>")
_KEY_SYMBOLS_RE = re.compile(
    r"key\s*<\s*([A-Za-z0-9_]+)\s*>\s*\{\s*\[([^\]]+)\]\s*\}"
)


def _symbol_value(token: str) -> int | None:
    token = token.strip()
    if not token or token == "NoSymbol":
        return None
    m = _UNICODE_RE.match(token)
    if m:
        codepoint = int(m.group(1), 16)
        return UNICODE_BASE + codepoint if codepoint > 0xFF else codepoint
    if len(token) == 1:
        return ord(token)
    known = SYMBOL_NAMES.get(token.lower())
    if known is not None:
        return known
    known = lookup_keysym(token)
    if known is not None:
        return known
    log.debug("unknown keysym name %r in keymap", token)
    return None


class Keymap:
    def __init__(self):
        # keycode -> list of keysyms per level
        self._levels: dict[int, list[int]] = {}

    def add_key(self, keycode: int, keysyms: list[int]) -> None:
        self._levels[keycode] = keysyms

    def resolve(self, keysym: int) -> tuple[int, int] | None:
        """Return (keycode, level) for a keysym, or None."""
        for keycode, levels in self._levels.items():
            for level, value in enumerate(levels):
                if value == keysym:
                    return keycode, level
        return None

    def __bool__(self) -> bool:
        return bool(self._levels)


def parse_keymap_text(text: str) -> Keymap:
    keymap = Keymap()
    aliases: dict[str, str] = {}
    try:
        keycodes = text.split('xkb_keycodes')[1].split('xkb_types')[0]
        for m in _KEYCODE_RE.finditer(keycodes):
            aliases[m.group(1)] = m.group(1)
            # keycode values are declared here; stored per name
        for m in _ALIAS_RE.finditer(keycodes):
            aliases[m.group(1)] = m.group(2)
        name_to_keycode = {}
        for m in _KEYCODE_RE.finditer(keycodes):
            name_to_keycode[m.group(1)] = int(m.group(2))
        for alias, target in aliases.items():
            if alias not in name_to_keycode and target in name_to_keycode:
                name_to_keycode[alias] = name_to_keycode[target]

        symbols = text.split('xkb_symbols')[1] if 'xkb_symbols' in text else ""
        symbols = symbols.split('xkb_geometry')[0] if 'xkb_geometry' in symbols else symbols
        for m in _KEY_SYMBOLS_RE.finditer(symbols):
            name, body = m.group(1), m.group(2)
            keycode = name_to_keycode.get(name)
            if keycode is None:
                continue
            levels = []
            for token in body.split(","):
                value = _symbol_value(token)
                if value is not None:
                    levels.append(value)
            if levels:
                keymap.add_key(keycode, levels)
    except (IndexError, ValueError) as e:
        log.warning("xkb keymap parse failed: %s", e)
        return Keymap()
    return keymap


# -- US evdev fallback ---------------------------------------------------
# keycode -> (base keysym, shifted keysym); level 0 = base, level 1 = shifted.

_US_ROWS: list[list[tuple[int, str, str] | None]] = [
    # digit row
    [(2, "1", "!"), (3, "2", "@"), (4, "3", "#"), (5, "4", "$"),
     (6, "5", "%"), (7, "6", "^"), (8, "7", "&"), (9, "8", "*"),
     (10, "9", "("), (11, "0", ")"), (12, "-", "_"), (13, "=", "+")],
    # qwerty row
    [(16, "q", "Q"), (17, "w", "W"), (18, "e", "E"), (19, "r", "R"),
     (20, "t", "T"), (21, "y", "Y"), (22, "u", "U"), (23, "i", "I"),
     (24, "o", "O"), (25, "p", "P"), (26, "[", "{"), (27, "]", "}"),
     (43, "\\", "|")],
    # home row
    [(30, "a", "A"), (31, "s", "S"), (32, "d", "D"), (33, "f", "F"),
     (34, "g", "G"), (35, "h", "H"), (36, "j", "J"), (37, "k", "K"),
     (38, "l", "L"), (39, ";", ":"), (40, "'", '"')],
    # bottom row
    [(44, "z", "Z"), (45, "x", "X"), (46, "c", "C"), (47, "v", "V"),
     (48, "b", "B"), (49, "n", "N"), (50, "m", "M"), (51, ",", "<"),
     (52, ".", ">"), (53, "/", "?")],
    # specials: (keycode, keysym, level 0)
    [(57, " ", " "), (28, "Return", "Return"), (15, "Tab", "Tab"),
     (1, "Escape", "Escape"), (14, "BackSpace", "BackSpace"),
     (111, "Delete", "Delete"), (105, "Left", "Left"), (106, "Right", "Right"),
     (103, "Up", "Up"), (108, "Down", "Down"), (102, "Home", "Home"),
     (107, "End", "End"), (104, "Page_Up", "Page_Up"),
     (109, "Page_Down", "Page_Down"), (58, "Caps_Lock", "Caps_Lock"),
     (42, "Shift_L", "Shift_L"), (54, "Shift_R", "Shift_R"),
     (29, "Control_L", "Control_L"), (97, "Control_R", "Control_R"),
     (56, "Alt_L", "Alt_L"), (100, "Alt_R", "Alt_R"),
     (125, "Super_L", "Super_L"), (126, "Super_R", "Super_R"),
     (59, "F1", "F1"), (60, "F2", "F2"), (61, "F3", "F3"), (62, "F4", "F4"),
     (63, "F5", "F5"), (64, "F6", "F6"), (65, "F7", "F7"), (66, "F8", "F8"),
     (67, "F9", "F9"), (68, "F10", "F10"), (87, "F11", "F11"),
     (88, "F12", "F12"),
]]

_FALLBACK: Keymap | None = None


def us_fallback() -> Keymap:
    global _FALLBACK
    if _FALLBACK is None:
        keymap = Keymap()
        for row in _US_ROWS:
            for entry in row:
                if entry is None:
                    continue
                keycode, base, shifted = entry
                base_sym = lookup_keysym(base)
                if base_sym is None:
                    continue
                if shifted != base:
                    shifted_sym = lookup_keysym(shifted)
                    if shifted_sym is not None:
                        keymap.add_key(keycode, [base_sym, shifted_sym])
                        continue
                keymap.add_key(keycode, [base_sym])
        _FALLBACK = keymap
    return _FALLBACK


def build_resolver(keymap_text: str | None):
    """Return a keysym -> (keycode, level) resolver (fallback-aware).

    The parsed keymap wins when it knows the keysym; the US table covers
    anything it lacks (partial keymaps are common).
    """
    keymap = parse_keymap_text(keymap_text) if keymap_text else Keymap()
    if not keymap:
        log.warning("keymap unusable — falling back to the US table")
        return us_fallback().resolve

    def resolve(keysym: int) -> tuple[int, int] | None:
        resolved = keymap.resolve(keysym)
        if resolved is not None:
            return resolved
        return us_fallback().resolve(keysym)

    return resolve
