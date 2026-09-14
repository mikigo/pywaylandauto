"""EIS backend — compositor-agnostic EIS client with pluggable connection."""

import logging
import os
import socket
import struct
import time

from . import messages as m
from .kylin import connect as _default_connect
from ..base import BUTTONS, PRESS, RELEASE, Backend, BackendError
from ..xkb import us_fallback

log = logging.getLogger(__name__)

_INTERFACES = {
    "ei_connection": (1, m.CONNECTION_REQ, m.CONNECTION_EVT),
    "ei_callback": (1, {}, {"done": (0, "")}),
    "ei_pingpong": (1, m.PINGPONG_REQ, {}),
    "ei_seat": (1, m.SEAT_REQ, m.SEAT_EVT),
    "ei_device": (1, m.DEVICE_REQ, m.DEVICE_EVT),
    "ei_pointer": (1, m.POINTER_REQ, {}),
    "ei_pointer_absolute": (1, m.POINTER_ABS_REQ, {}),
    "ei_scroll": (1, m.SCROLL_REQ, {}),
    "ei_button": (1, m.BUTTON_REQ, {}),
    "ei_keyboard": (1, m.KEYBOARD_REQ, m.KEYBOARD_EVT),
}
_RECV_CHUNK = 65536


class EisError(Exception):
    pass


class _EisDevice:
    def __init__(self, object_id):
        self.object_id = object_id
        self.name = ""
        self.regions: list = []
        self.sub: dict[str, int] = {}
        self._seq = 0

    def next_sequence(self):
        self._seq += 1
        return self._seq


class _EisClient:
    """Minimal EIS sender client — adapted from PyWaylandAuto's eis.py."""

    def __init__(self, fd: int):
        self._sock = socket.socket(fileno=fd)
        self._sock.setblocking(False)
        self._buf = bytearray()
        self._pending_fds: list = []
        self._objects: dict[int, str] = {}
        self._devices: dict[int, _EisDevice] = {}
        self._keyboard: _EisDevice | None = None
        self._pointer: _EisDevice | None = None
        self._pointer_abs: _EisDevice | None = None
        self._connection_id: int | None = None
        self._seat_id: int | None = None
        self._seat_mask: int = 0
        self._last_serial: int = 0
        self._server_version: int | None = None
        self._bound_mask: int | None = None
        self.keymap_text: str | None = None
        self.regions: list = []

    @property
    def fd(self):
        return self._sock.fileno()

    def close(self):
        try:
            if self._connection_id is not None:
                self._send(self._connection_id, *m.CONNECTION_REQ["disconnect"], ())
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def handshake(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while self._server_version is None:
            self._pump_once()
            if time.monotonic() >= deadline:
                raise EisError("EIS server did not send handshake_version")
        self._send(0, *m.HANDSHAKE_REQ["handshake_version"],
                   (min(self._server_version, 1),))
        self._send(0, *m.HANDSHAKE_REQ["context_type"], (m.CTX_SENDER,))
        self._send(0, *m.HANDSHAKE_REQ["name"], ("pywaylandauto",))
        for name, (version, _req, _evt) in _INTERFACES.items():
            self._send(0, *m.HANDSHAKE_REQ["interface_version"], (name, version))
        self._send(0, *m.HANDSHAKE_REQ["finish"], ())
        deadline = time.monotonic() + timeout
        while (self._connection_id is None or self._bound_mask is None
               or self._keyboard is None or self._pointer_abs is None
               or self.keymap_text is None):
            self._pump_once()
            if time.monotonic() >= deadline:
                raise EisError("EIS handshake timed out")
        for dev in [self._pointer_abs]:
            self.regions = [(r[0], r[1], r[2], r[3], r[4]) for r in dev.regions]

    @staticmethod
    def _monotonic_us():
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC) // 1000

    def _send(self, object_id, opcode, sig, args):
        try:
            self._sock.sendall(m.pack_message(object_id, opcode, sig, args))
        except OSError as e:
            raise EisError(f"EIS send failed: {e}") from e

    def _begin_frame(self, device):
        self._send(device.object_id, *m.DEVICE_REQ["start_emulating"],
                   (self._last_serial, device.next_sequence()))

    def _end_frame(self, device):
        self._send(device.object_id, *m.DEVICE_REQ["frame"],
                   (self._last_serial, self._monotonic_us()))
        self._send(device.object_id, *m.DEVICE_REQ["stop_emulating"],
                   (self._last_serial,))

    def move_abs(self, x, y):
        self._begin_frame(self._pointer_abs)
        self._send(self._pointer_abs.sub["ei_pointer_absolute"],
                   *m.POINTER_ABS_REQ["motion_absolute"], (x, y))
        self._end_frame(self._pointer_abs)

    def move_rel(self, dx, dy):
        self._begin_frame(self._pointer)
        self._send(self._pointer.sub["ei_pointer"],
                   *m.POINTER_REQ["motion_relative"], (dx, dy))
        self._end_frame(self._pointer)

    def button(self, btn, state):
        self._begin_frame(self._pointer)
        self._send(self._pointer.sub["ei_button"],
                   *m.BUTTON_REQ["button"], (btn, state))
        self._end_frame(self._pointer)

    def scroll_discrete(self, dx, dy):
        self._begin_frame(self._pointer)
        self._send(self._pointer.sub["ei_scroll"],
                   *m.SCROLL_REQ["scroll_discrete"], (dx, dy))
        self._end_frame(self._pointer)

    def key(self, keycode, state):
        self._begin_frame(self._keyboard)
        self._send(self._keyboard.sub["ei_keyboard"],
                   *m.KEYBOARD_REQ["key"], (keycode, state))
        self._end_frame(self._keyboard)

    def key_sequence(self, *key_events):
        """Send multiple key events in a SINGLE frame — for combos like ctrl+v."""
        self._begin_frame(self._keyboard)
        for keycode, press in key_events:
            self._send(self._keyboard.sub["ei_keyboard"],
                       *m.KEYBOARD_REQ["key"], (keycode, press))
        self._end_frame(self._keyboard)

    def key_combo_frame(self, *keycodes: int):
        """Send key combo in 2 frames: mods in frame 1, main+releases in frame 2."""
        kb = self._keyboard.sub["ei_keyboard"]
        PRESS = 1
        RELEASE = 0

        if len(keycodes) <= 1:
            self._begin_frame(self._keyboard)
            self._send(kb, *m.KEYBOARD_REQ["key"], (keycodes[0], PRESS))
            self._send(kb, *m.KEYBOARD_REQ["key"], (keycodes[0], RELEASE))
            self._end_frame(self._keyboard)
            return

        mods = keycodes[:-1]
        main = keycodes[-1]

        # Frame 1: press all modifiers
        self._begin_frame(self._keyboard)
        for kc in mods:
            self._send(kb, *m.KEYBOARD_REQ["key"], (kc, PRESS))
        self._end_frame(self._keyboard)

        # Frame 2: press modifiers again, main key, release all
        self._begin_frame(self._keyboard)
        for kc in mods:
            self._send(kb, *m.KEYBOARD_REQ["key"], (kc, PRESS))
        self._send(kb, *m.KEYBOARD_REQ["key"], (main, PRESS))
        self._send(kb, *m.KEYBOARD_REQ["key"], (main, RELEASE))
        for kc in reversed(mods):
            self._send(kb, *m.KEYBOARD_REQ["key"], (kc, RELEASE))
        self._end_frame(self._keyboard)

    def _pump_once(self):
        try:
            data, ancdata, _flags, _addr = self._sock.recvmsg(
                _RECV_CHUNK, socket.CMSG_SPACE(16 * 4))
        except BlockingIOError:
            return
        except OSError as e:
            raise EisError(f"EIS recv failed: {e}") from e
        if not data:
            raise EisError("EIS server closed the connection")
        for level, ctype, cdata in ancdata:
            if level == socket.SOL_SOCKET and ctype == socket.SCM_RIGHTS:
                count = len(cdata) // 4
                self._pending_fds.extend(struct.unpack(f"{count}i", cdata))
        self._buf.extend(data)
        while len(self._buf) >= 16:
            obj_id, length, opcode = m.unpack_header(bytes(self._buf[:16]))
            if len(self._buf) < length:
                break
            payload = bytes(self._buf[16:length])
            del self._buf[:length]
            self._dispatch(obj_id, opcode, payload)

    def _dispatch(self, obj_id, opcode, payload):
        iface = self._objects.get(obj_id, "ei_handshake")
        _, _req, evts = _INTERFACES.get(iface, (1, {}, {}))
        name = sig = None
        for evt_name, (evt_opcode, evt_sig) in evts.items():
            if evt_opcode == opcode:
                name, sig = evt_name, evt_sig
                break
        if iface == "ei_handshake":
            for evt_name, (evt_opcode, evt_sig) in m.HANDSHAKE_EVT.items():
                if evt_opcode == opcode:
                    name, sig = evt_name, evt_sig
                    break
        if name is None:
            return
        args, _ = m.unpack_args(sig, payload, 0, self._pending_fds)
        handler = getattr(self, f"_on_{iface.replace('ei_', '')}_{name}", None)
        if handler:
            handler(obj_id, args)

    def _on_handshake_handshake_version(self, obj_id, args):
        self._server_version = args[0]

    def _on_handshake_connection(self, obj_id, args):
        serial, conn_id, _version = args
        self._connection_id = conn_id
        self._objects[conn_id] = "ei_connection"
        self._last_serial = serial

    def _on_connection_seat(self, obj_id, args):
        seat_id, _version = args
        self._seat_id = seat_id
        self._objects[seat_id] = "ei_seat"

    def _on_seat_capability(self, obj_id, args):
        mask, _iface = args
        self._seat_mask |= mask

    def _on_seat_done(self, obj_id, args):
        self._bound_mask = self._seat_mask
        self._send(self._seat_id, *m.SEAT_REQ["bind"], (self._seat_mask,))

    def _on_seat_device(self, obj_id, args):
        device_id, _version = args
        self._objects[device_id] = "ei_device"
        self._devices[device_id] = _EisDevice(device_id)

    def _on_device_name(self, obj_id, args):
        self._devices[obj_id].name = args[0]

    def _on_device_device_type(self, obj_id, args):
        pass

    def _on_device_region(self, obj_id, args):
        self._devices[obj_id].regions.append(tuple(args))

    def _on_device_interface(self, obj_id, args):
        sub_id, iface_name, _version = args
        self._objects[sub_id] = iface_name
        device = self._devices[obj_id]
        device.sub[iface_name] = sub_id
        if iface_name == "ei_keyboard":
            self._keyboard = device
        elif iface_name == "ei_pointer":
            self._pointer = device
        elif iface_name == "ei_pointer_absolute":
            self._pointer_abs = device

    def _on_keyboard_keymap(self, obj_id, args):
        keymap_type, size, fd = args
        try:
            data = b""
            while len(data) < size:
                chunk = os.read(fd, size - len(data))
                if not chunk:
                    break
                data += chunk
        except OSError:
            data = b""
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        if keymap_type == m.KEYMAP_XKB and data:
            self.keymap_text = data.decode("utf-8", errors="replace")

    def _on_keyboard_modifiers(self, obj_id, args):
        self._last_serial = args[0]

    def _on_connection_ping(self, obj_id, args):
        ping_id, _version = args
        self._objects[ping_id] = "ei_pingpong"
        self._send(ping_id, *m.PINGPONG_REQ["done"], ())

    def _on_connection_disconnected(self, obj_id, args):
        raise EisError(f"EIS disconnected: reason={args[1]} {args[2]!r}")


class EisBackend(Backend):
    name = "eis"

    def __init__(self, connect_fn=None):
        self._state = "init"
        self._client: _EisClient | None = None
        self._resolver = None
        self.regions: list = []
        self._connect_fn = connect_fn or _default_connect

    @property
    def state(self):
        return self._state

    @property
    def fd(self):
        return self._client.fd if self._client else -1

    def pump(self):
        if self._client:
            try:
                self._client._pump_once()
            except EisError:
                pass

    def start(self):
        if self._state == "started":
            return
        self._state = "starting"
        fd = self._connect_fn()
        self._client = _EisClient(fd)
        self._client.handshake()
        self.regions = self._client.regions
        self._resolver = us_fallback().resolve
        self._state = "started"

    def stop(self):
        if self._client:
            self._client.close()
            self._client = None
        self._state = "stopped"

    def status(self):
        return {"state": self._state, "transport": "eis", "regions": self.regions}

    def move_abs(self, x, y):
        if self._state != "started":
            raise BackendError("backend not started")
        self._client.move_abs(x, y)

    def move_rel(self, dx, dy):
        if self._state != "started":
            raise BackendError("backend not started")
        self._client.move_rel(dx, dy)

    def button(self, button, press):
        if self._state != "started":
            raise BackendError("backend not started")
        code = BUTTONS.get(str(button).lower(), button) if isinstance(button, str) else button
        self._client.button(int(code), press)

    def scroll(self, dx, dy):
        if self._state != "started":
            raise BackendError("backend not started")
        self._client.scroll_discrete(int(dx), int(dy))

    def key(self, keycode, press):
        if self._state != "started":
            raise BackendError("backend not started")
        self._client.key(keycode, press)

    def key_sequence(self, *key_events):
        if self._state != "started":
            raise BackendError("backend not started")
        self._client.key_sequence(*key_events)

    def key_combo_frame(self, *keycodes: int):
        """Send key combo in 2 frames: mods press, then main + releases."""
        if self._state != "started":
            raise BackendError("backend not started")
        self._client.key_combo_frame(*keycodes)

    def resolve_key(self, keysym):
        if self._resolver is None:
            return None
        resolved = self._resolver(keysym)
        if resolved is None:
            return None
        return resolved[0]

    def type_text(self, text):
        if self._state != "started":
            raise BackendError("backend not started")
        for ch in text:
            codepoint = ord(ch)
            ks = codepoint if codepoint <= 0xFF else 0x01000000 + codepoint
            keycode = self.resolve_key(ks)
            if keycode is None:
                log.debug("skipping keysym 0x%04x (not in keymap)", ks)
                continue
            self._client.key(keycode, PRESS)
            self._client.key(keycode, RELEASE)