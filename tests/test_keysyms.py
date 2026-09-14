from pywaylandauto.keysyms import KEYSYMS, UNICODE_BASE, lookup

class TestLookup:
    def test_named_keysym(self):
        assert lookup("Return") == 0xFF0D
        assert lookup("enter") == 0xFF0D
    def test_single_char(self):
        assert lookup("a") == ord("a")
        assert lookup("A") == ord("A")
    def test_unicode(self):
        assert lookup("中") == UNICODE_BASE + ord("中")
    def test_int_passthrough(self):
        assert lookup(0xFF0D) == 0xFF0D
    def test_unknown_returns_none(self):
        assert lookup("nonexistent") is None