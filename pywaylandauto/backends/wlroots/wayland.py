"""Wayland wire protocol codec + connection — pure stdlib.

Wire format (wayland.xml, native byte order):
  * 8-byte header: u32 object_id, u32 (length << 16) | opcode;
    length includes the header.
  * Args are 4-byte units, no extra alignment:
      u/i -> 4 bytes, f -> 4 bytes (wl_fixed 24.8),
      s -> u32 length (incl. NUL) + bytes + pad to 4,
      o/n -> 4 bytes (object / new id),
      h -> fd via SCM_RIGHTS, ZERO payload bytes.
Unknown events are skipped by header length (safe: every message is framed).
"""

import logging
import os
import socket
import struct
import time

log = logging.getLogger(__name__)

HEADER = struct.Struct("=II")

# interface -> request table: name -> (opcode, signature)
DISPLAY_REQ = {"sync": (0, "n"), "get_registry": (1, "n")}
DISPLAY_EVT = {"error": (0, "ous"), "delete_id": (1, "u")}
REGISTRY_REQ = {"bind": (0, "usun")}
REGISTRY_EVT = {"global": (0, "usu"), "global_remove": (1, "u")}
CALLBACK_EVT = {"done": (0, "u")}
SEAT_REQ = {"get_pointer": (0, "n"), "get_keyboard": (1, "n"),
            "get_touch": (2, "n"), "release": (3, "")}
SEAT_EVT = {"capabilities": (0, "u"), "name": (1, "s")}
KEYBOARD_EVT = {"keymap": (0, "uhu")}  # enter/leave/key/modifiers: unhandled -> skipped
OUTPUT_REQ = {"release": (0, "")}
VIRTUAL_POINTER_MGR_REQ = {
    "create_virtual_pointer": (0, "on"),
    "create_virtual_pointer_with_output": (1, "oon"),
}
VIRTUAL_POINTER_REQ = {
    "motion": (0, "uff"), "motion_absolute": (1, "uff"),
    "button": (2, "uuu"), "axis": (3, "uuf"), "frame": (4, ""),
    "axis_source": (5, "u"), "axis_stop": (6, "uu"),
    "axis_discrete": (7, "uufi"), "release": (8, ""),
}
VIRTUAL_KEYBOARD_MGR_REQ = {"create_virtual_keyboard": (0, "on")}
VIRTUAL_KEYBOARD_REQ = {
    "keymap": (0, "uhu"), "key": (1, "uuu"),
    "modifiers": (2, "uuuuu"), "release": (3, ""),
}

REQ_TABLES = {
    "wl_display": DISPLAY_REQ, "wl_registry": REGISTRY_REQ,
    "wl_seat": SEAT_REQ, "wl_output": OUTPUT_REQ,
    "zwlr_virtual_pointer_manager_v1": VIRTUAL_POINTER_MGR_REQ,
    "zwlr_virtual_pointer_v1": VIRTUAL_POINTER_REQ,
    "zwlr_virtual_keyboard_manager_v1": VIRTUAL_KEYBOARD_MGR_REQ,
    "zwlr_virtual_keyboard_v1": VIRTUAL_KEYBOARD_REQ,
    "wl_data_device_manager": {"get_data_device": (0, "no")},
    "wl_data_device": {"set_selection": (0, "oo"), "release": (1, "")},
    "wl_data_source": {"offer": (0, "s"), "destroy": (1, "")},
    "zwlr_data_control_manager_v1": {
        "create_data_source": (0, "n"),
        "get_data_device": (1, "no"),
    },
    "zwlr_data_control_device_v1": {
        "set_selection": (0, "o"), "destroy": (1, ""),
    },
    "zwlr_data_control_source_v1": {
        "offer": (0, "s"), "destroy": (1, ""),
    },
}
EVT_TABLES = {
    "wl_display": DISPLAY_EVT, "wl_registry": REGISTRY_EVT,
    "wl_callback": CALLBACK_EVT, "wl_seat": SEAT_EVT,
    "wl_keyboard": KEYBOARD_EVT,
    "wl_data_source": {"target": (0, "s"), "send": (1, "sh"), "cancelled": (2, "")},
    "wl_data_device": {"data_offer": (0, "n"), "selection": (1, "o")},
    "wl_data_offer": {"offer": (0, "s")},
    "zwlr_data_control_source_v1": {
        "send": (0, "sh"), "cancelled": (1, ""),
    },
}


class WaylandError(Exception):
    """Wayland connection-level failure."""


def to_fixed(value: float) -> int:
    """float -> wl_fixed 24.8."""
    return int(value * 256.0)


def from_fixed(value: int) -> float:
    return value / 256.0


def pack_message(object_id: int, opcode: int, sig: str, args=()) -> bytes:
    payload = bytearray()
    idx = 0
    for c in sig:
        if c == "u":
            payload += struct.pack("=I", args[idx])
        elif c == "i":
            payload += struct.pack("=i", args[idx])
        elif c == "f":
            payload += struct.pack("=i", args[idx])  # wl_fixed is i32
        elif c in "on":
            payload += struct.pack("=I", args[idx])
        elif c == "s":
            raw = args[idx].encode("utf-8") + b"\0"
            payload += struct.pack("=I", len(raw))
            payload += raw + b"\0" * ((4 - len(raw) % 4) % 4)
        elif c == "h":
            pass  # fd travels via SCM_RIGHTS, not the payload
        else:
            raise ValueError(f"unknown signature char {c!r}")
        idx += 1
    return HEADER.pack(object_id, ((8 + len(payload)) << 16) | opcode) \
        + bytes(payload)


def unpack_header(data: bytes) -> tuple[int, int, int]:
    if len(data) < 8:
        raise ValueError("short Wayland header")
    obj_id, size_opcode = HEADER.unpack(data[:8])
    return obj_id, size_opcode >> 16, size_opcode & 0xFFFF


def unpack_args(sig: str, data: bytes, offset: int, fds: list) -> tuple[list, int]:
    args = []
    p = offset
    for c in sig:
        if c == "u":
            args.append(struct.unpack_from("=I", data, p)[0]); p += 4
        elif c == "i":
            args.append(struct.unpack_from("=i", data, p)[0]); p += 4
        elif c == "f":
            args.append(struct.unpack_from("=i", data, p)[0]); p += 4
        elif c in "on":
            args.append(struct.unpack_from("=I", data, p)[0]); p += 4
        elif c == "s":
            (slen,) = struct.unpack_from("=I", data, p); p += 4
            raw = data[p:p + slen]
            args.append(raw.rstrip(b"\0").decode("utf-8", errors="replace"))
            p += (slen + 3) & ~3
        elif c == "h":
            args.append(fds.pop(0) if fds else -1)
        else:
            raise ValueError(f"unknown signature char {c!r}")
    return args, p


class WaylandConnection:
    """One Wayland display connection: send/recv + event dispatch.

    Events dispatch to `_on_<iface>_<name>` methods on this object, or —
    if absent — on `self.handler` (the session that owns the connection).
    """

    def __init__(self, fd: int):
        self._sock = socket.socket(fileno=fd)
        self._sock.setblocking(False)
        self._buf = bytearray()
        self._pending_fds: list = []
        self.objects: dict[int, str] = {}  # object id -> interface name
        self.handler = None
        self._next_id = 1
        self.display_id = self.alloc_id()
        self.objects[self.display_id] = "wl_display"

    @classmethod
    def connect(cls, display: str) -> "WaylandConnection":
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime:
            raise WaylandError("XDG_RUNTIME_DIR is not set")
        path = os.path.join(runtime, display)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        try:
            sock.connect(path)
        except OSError as e:
            sock.close()
            raise WaylandError(f"cannot connect to {path}: {e}") from e
        return cls(sock.detach())

    @property
    def fd(self) -> int:
        return self._sock.fileno()

    def alloc_id(self) -> int:
        obj_id = self._next_id
        self._next_id += 1
        return obj_id

    def send(self, obj_id: int, iface: str, name: str, args) -> None:
        opcode, sig = REQ_TABLES[iface][name]
        payload = pack_message(obj_id, opcode, sig, args)
        fds = [a for a, c in zip(args, sig)
               if c == "h" and isinstance(a, int) and a >= 0]
        try:
            if fds:
                self._sock.sendmsg(
                    [payload], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                 struct.pack(f"{len(fds)}i", *fds))])
            else:
                self._sock.sendall(payload)
        except OSError as e:
            raise WaylandError(f"Wayland send failed: {e}") from e

    def bind(self, registry_id: int, name: int, iface: str,
             version: int) -> int:
        obj_id = self.alloc_id()
        self.objects[obj_id] = iface
        self.send(registry_id, "wl_registry", "bind",
                  (name, iface, version, obj_id))
        return obj_id

    def sync(self, timeout: float = 2.0) -> None:
        """Roundtrip: sync + wait for the callback's done event."""
        callback_id = self.alloc_id()
        self.objects[callback_id] = "wl_callback"
        self.send(self.display_id, "wl_display", "sync", (callback_id,))
        deadline = time.monotonic() + timeout
        while callback_id in self.objects:
            self.pump(deadline - time.monotonic())
            if time.monotonic() >= deadline:
                raise WaylandError("wl_display.sync roundtrip timed out")

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def pump(self, timeout: float = 0.0) -> None:
        """Drain pending events (non-blocking; timeout is a bound only)."""
        try:
            data, ancdata, _flags, _addr = self._sock.recvmsg(
                65536, socket.CMSG_SPACE(16 * 4))
        except BlockingIOError:
            return
        except OSError as e:
            raise WaylandError(f"Wayland recv failed: {e}") from e
        if not data:
            raise WaylandError("Wayland server closed the connection")
        for level, ctype, cdata in ancdata:
            if level == socket.SOL_SOCKET and ctype == socket.SCM_RIGHTS:
                self._pending_fds.extend(
                    struct.unpack(f"{len(cdata) // 4}i", cdata))
        self._buf.extend(data)
        while len(self._buf) >= 8:
            obj_id, size, opcode = unpack_header(bytes(self._buf[:8]))
            if len(self._buf) < size:
                break
            payload = bytes(self._buf[8:size])
            del self._buf[:size]
            self._dispatch(obj_id, opcode, payload)

    def _dispatch(self, obj_id: int, opcode: int, payload: bytes) -> None:
        iface = self.objects.get(obj_id, "")
        evts = EVT_TABLES.get(iface, {})
        name = sig = None
        for evt_name, (evt_opcode, evt_sig) in evts.items():
            if evt_opcode == opcode:
                name, sig = evt_name, evt_sig
                break
        if name is None:
            log.debug("ignoring Wayland event iface=%s opcode=%d", iface, opcode)
            return  # unknown/unregistered event — framed, safe to skip
        args, _ = unpack_args(sig, payload, 0, self._pending_fds)
        handler = getattr(self, f"_on_{iface}_{name}", None)
        if handler is None and self.handler is not None:
            handler = getattr(self.handler, f"_on_{iface}_{name}", None)
        if handler is not None:
            handler(obj_id, args)

    def _on_wl_callback_done(self, obj_id, args) -> None:
        self._last_callback_serial = args[0]
        self.objects.pop(obj_id, None)  # resolves pending sync()
