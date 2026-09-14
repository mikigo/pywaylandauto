"""EIS wire protocol codec — libei 1.5.0 (proto/protocol.xml, brei wire).

Wire format (verified against brei-shared.c @ 1.5.0):
  * 16-byte header, NATIVE byte order: u64 object_id, u32 length (incl.
    header), u32 opcode.
  * Args are 4-byte units, no extra per-arg padding:
      u/i/f -> 4 bytes (f = C float), x/o/n/t -> 8 bytes,
      s     -> u32 length (incl. NUL) + bytes, padded to 4,
      h     -> fd delivered via SCM_RIGHTS, ZERO payload bytes.
  * Opcodes are per-interface, numbered by declaration order in
    protocol.xml (requests and events each start at 0).
"""

import struct

HEADER = struct.Struct("=QII")

# per-interface opcode/signature tables (from proto/protocol.xml @ 1.5.0)
HANDSHAKE_REQ = {
    "handshake_version": (0, "u"),
    "finish": (1, ""),
    "context_type": (2, "u"),
    "name": (3, "s"),
    "interface_version": (4, "su"),
}
HANDSHAKE_EVT = {
    "handshake_version": (0, "u"),
    "interface_version": (1, "su"),
    "connection": (2, "unu"),
}
CONNECTION_REQ = {"sync": (0, "nu"), "disconnect": (1, "")}
CONNECTION_EVT = {
    "disconnected": (0, "uus"),
    "seat": (1, "nu"),
    "invalid_object": (2, "ut"),
    "ping": (3, "nu"),
}
SEAT_REQ = {"release": (0, ""), "bind": (1, "t")}
SEAT_EVT = {
    "destroyed": (0, "u"),
    "name": (1, "s"),
    "capability": (2, "ts"),
    "done": (3, ""),
    "device": (4, "nu"),
}
DEVICE_REQ = {
    "release": (0, ""),
    "start_emulating": (1, "uu"),
    "stop_emulating": (2, "u"),
    "frame": (3, "ut"),
}
DEVICE_EVT = {
    "destroyed": (0, "u"),
    "name": (1, "s"),
    "device_type": (2, "u"),
    "dimensions": (3, "uu"),
    "region": (4, "uuuuf"),
    "interface": (5, "nsu"),
    "done": (6, ""),
    # 7.. are receiver-side events we never advertise (version 1)
}
POINTER_REQ = {"release": (0, ""), "motion_relative": (1, "ff")}
POINTER_ABS_REQ = {"release": (0, ""), "motion_absolute": (1, "ff")}
SCROLL_REQ = {
    "release": (0, ""),
    "scroll": (1, "ff"),
    "scroll_discrete": (2, "ii"),
    "scroll_stop": (3, "ii"),
}
BUTTON_REQ = {"release": (0, ""), "button": (1, "uu")}
KEYBOARD_REQ = {"release": (0, ""), "key": (1, "uu")}
KEYBOARD_EVT = {
    "destroyed": (0, "u"),
    "keymap": (1, "uuh"),
    "key": (2, "uuu"),
    "modifiers": (3, "uuuuu"),
}
PINGPONG_REQ = {"done": (0, "")}

CTX_RECEIVER = 1
CTX_SENDER = 2

DEVICE_TYPE_VIRTUAL = 1
DEVICE_TYPE_PHYSICAL = 2

KEYMAP_XKB = 1


def _round4(n: int) -> int:
    return (n + 3) & ~3


def pack_message(object_id: int, opcode: int, sig: str, args: tuple = ()) -> bytes:
    """Serialize one EIS message; args must match sig ('h' args are ignored —
    fds are attached out-of-band via SCM_RIGHTS)."""
    payload = bytearray()
    idx = 0
    for c in sig:
        if c in "uif":
            fmt = {"u": "=I", "i": "=i", "f": "=f"}[c]
            payload += struct.pack(fmt, args[idx])
        elif c in "xotn":
            payload += struct.pack("=Q", args[idx])
        elif c == "s":
            raw = args[idx].encode("utf-8") + b"\0"
            payload += struct.pack("=I", len(raw))
            payload += raw + b"\0" * (_round4(len(raw)) - len(raw))
        elif c == "h":
            pass  # fd travels via SCM_RIGHTS, not the payload
        else:
            raise ValueError(f"unknown signature char {c!r}")
        idx += 1
    return HEADER.pack(object_id, 16 + len(payload), opcode) + bytes(payload)


def unpack_header(data: bytes) -> tuple[int, int, int]:
    if len(data) < 16:
        raise ValueError("short EIS header")
    return HEADER.unpack(data[:16])


def unpack_args(sig: str, data: bytes, offset: int, fds: list) -> tuple[list, int]:
    """Decode args of `sig` starting at `offset`; 'h' args consume one fd
    from `fds`.  Returns (args, new_offset)."""
    args = []
    p = offset
    for c in sig:
        if c in "uif":
            fmt = {"u": "=I", "i": "=i", "f": "=f"}[c]
            args.append(struct.unpack_from(fmt, data, p)[0])
            p += 4
        elif c in "xotn":
            args.append(struct.unpack_from("=Q", data, p)[0])
            p += 8
        elif c == "s":
            (slen,) = struct.unpack_from("=I", data, p)
            p += 4
            raw = data[p:p + slen]
            args.append(raw.rstrip(b"\0").decode("utf-8", errors="replace"))
            p += _round4(slen)
        elif c == "h":
            args.append(fds.pop(0) if fds else -1)
        else:
            raise ValueError(f"unknown signature char {c!r}")
    return args, p
