import struct
from pywaylandauto.backends.eis.messages import (
    pack_message, unpack_header, unpack_args,
    HANDSHAKE_REQ, POINTER_REQ, SCROLL_REQ, BUTTON_REQ, KEYBOARD_REQ, KEYBOARD_EVT,
)

class TestPackMessage:
    def test_handshake_version(self):
        msg = pack_message(0, *HANDSHAKE_REQ["handshake_version"], (1,))
        obj_id, length, opcode = unpack_header(msg)
        assert obj_id == 0 and opcode == 0
        args, _ = unpack_args("u", msg, 16, [])
        assert args == [1]

    def test_pointer_motion_relative(self):
        msg = pack_message(5, *POINTER_REQ["motion_relative"], (10.5, -20.25))
        args, _ = unpack_args("ff", msg, 16, [])
        assert args == [10.5, -20.25]

    def test_scroll_discrete(self):
        msg = pack_message(5, *SCROLL_REQ["scroll_discrete"], (0, 3))
        args, _ = unpack_args("ii", msg, 16, [])
        assert args == [0, 3]

    def test_button(self):
        msg = pack_message(5, *BUTTON_REQ["button"], (0x110, 1))
        args, _ = unpack_args("uu", msg, 16, [])
        assert args == [0x110, 1]

    def test_keyboard_key(self):
        msg = pack_message(5, *KEYBOARD_REQ["key"], (30, 1))
        args, _ = unpack_args("uu", msg, 16, [])
        assert args == [30, 1]

    def test_fd_arg_is_zero_bytes(self):
        msg = pack_message(5, *KEYBOARD_EVT["keymap"], (1, 1024, 42))
        obj_id, length, opcode = unpack_header(msg)
        assert length == 16 + 8

class TestUnpackHeader:
    def test_valid(self):
        data = struct.pack("=QII", 42, 32, 7)
        obj_id, length, opcode = unpack_header(data)
        assert obj_id == 42 and length == 32 and opcode == 7

    def test_short_raises(self):
        import pytest
        with pytest.raises(ValueError, match="short"):
            unpack_header(b"\x00" * 8)