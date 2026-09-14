from pywaylandauto.backends.xkb import Keymap, parse_keymap_text, us_fallback, build_resolver

SAMPLE_KEYMAP = """
xkb_keymap {
xkb_keycodes "evdev" { minimum = 8; maximum = 255; <ESC> = 9; <AE01> = 10; <LFSH> = 50; };
xkb_types "default" {};
xkb_compatibility "default" {};
xkb_symbols "pc+us" {
    key <ESC>  { [ Escape ] };
    key <AE01> { [ 1, exclam ] };
    key <LFSH> { [ Shift_L ] };
};
};
"""

class TestKeymap:
    def test_parse(self):
        km = parse_keymap_text(SAMPLE_KEYMAP)
        assert km.resolve(0xFF1B) == (9, 0)
        assert km.resolve(ord("!")) == (10, 1)
    def test_unknown(self):
        km = parse_keymap_text(SAMPLE_KEYMAP)
        assert km.resolve(0xFFFF) is None

class TestUsFallback:
    def test_has_keys(self):
        km = us_fallback()
        assert km.resolve(ord("a")) is not None
        assert km.resolve(0xFF0D) is not None

    def test_resolver_hybrid(self):
        resolve = build_resolver(SAMPLE_KEYMAP)
        assert resolve(0xFF1B) == (9, 0)
        assert resolve(ord("x")) is not None