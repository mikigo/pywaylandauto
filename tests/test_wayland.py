from pywaylandauto.backends.wlroots.wayland import (
    pack_message, unpack_args, to_fixed, from_fixed,
    VIRTUAL_POINTER_REQ, VIRTUAL_KEYBOARD_REQ,
)

class TestPackMessage:
    def test_virtual_pointer_motion(self):
        msg = pack_message(1, *VIRTUAL_POINTER_REQ["motion"],
                           (0, to_fixed(10.5), to_fixed(-20.25)))
        args, _ = unpack_args("uff", msg, 8, [])
        assert args[1] == to_fixed(10.5)

    def test_virtual_keyboard_key(self):
        msg = pack_message(1, *VIRTUAL_KEYBOARD_REQ["key"], (0, 30, 1))
        args, _ = unpack_args("uuu", msg, 8, [])
        assert args == [0, 30, 1]

class TestWlFixed:
    def test_roundtrip(self):
        assert to_fixed(1.0) == 256
        assert from_fixed(256) == 1.0
        assert to_fixed(0.5) == 128