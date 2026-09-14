"""Wlroots backend: zwlr_virtual_pointer/zwp_virtual_keyboard protocols."""

import logging
import os
import socket
import time

from ..base import BUTTONS, PRESS, RELEASE, Backend, BackendError
from .wayland import (
    to_fixed, WaylandConnection,
    VIRTUAL_POINTER_REQ, VIRTUAL_KEYBOARD_REQ,
    VIRTUAL_POINTER_MGR_REQ, VIRTUAL_KEYBOARD_MGR_REQ,
)
from ..xkb import us_fallback

log = logging.getLogger(__name__)

MINIMAL_US_KEYMAP = b"""xkb_keymap {
xkb_keycodes "evdev" { minimum = 8; maximum = 255; };
xkb_types "default" {};
xkb_compatibility "default" {};
xkb_symbols "pc+us" {};
};"""


class WlrootsBackend(Backend):
    name = "wlroots"

    def __init__(self):
        self._state = "init"
        self._conn = None
        self._pointer_id = None
        self._keyboard_id = None
        self._pointer_mgr_id = None
        self._keyboard_mgr_id = None
        self._seat_id = None
        self._outputs = []
        self._keymap = us_fallback()

    @property
    def state(self):
        return self._state

    def start(self):
        if self._state == "started":
            return
        self._state = "starting"
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        wayland_display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        path = os.path.join(runtime, wayland_display)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(path)
        self._conn = WaylandConnection(sock.detach())
        self._conn.handler = self
        registry_id = self._conn.alloc_id()
        self._conn.objects[registry_id] = "wl_registry"
        self._conn.send(self._conn.display_id, "wl_display", "get_registry", (registry_id,))
        self._pump_until(lambda: self._pointer_mgr_id is not None and self._keyboard_mgr_id is not None, timeout=3.0)
        if self._pointer_mgr_id is None:
            raise BackendError("zwlr_virtual_pointer_manager_v1 not available")
        if self._keyboard_mgr_id is None:
            raise BackendError("zwp_virtual_keyboard_manager_v1 not available")
        self._pointer_id = self._conn.alloc_id()
        self._conn.objects[self._pointer_id] = "zwlr_virtual_pointer_v1"
        output_id = self._outputs[0]["id"] if self._outputs else 0
        if output_id:
            self._conn.send(self._pointer_mgr_id, "zwlr_virtual_pointer_manager_v1", "create_virtual_pointer_with_output", (self._seat_id, output_id, self._pointer_id))
        else:
            self._conn.send(self._pointer_mgr_id, "zwlr_virtual_pointer_manager_v1", "create_virtual_pointer", (self._seat_id, self._pointer_id))
        self._keyboard_id = self._conn.alloc_id()
        self._conn.objects[self._keyboard_id] = "zwp_virtual_keyboard_v1"
        self._conn.send(self._keyboard_mgr_id, "zwp_virtual_keyboard_manager_v1", "create_virtual_keyboard", (self._seat_id, self._keyboard_id))
        self._send_keymap()
        self._conn.sync(timeout=2.0)
        self._state = "started"

    def _send_keymap(self):
        fd = os.memfd_create("keymap", 0)
        os.write(fd, MINIMAL_US_KEYMAP)
        os.lseek(fd, 0, os.SEEK_SET)
        self._conn.send(self._keyboard_id, "zwp_virtual_keyboard_v1", "keymap", (1, fd, len(MINIMAL_US_KEYMAP)))
        os.close(fd)

    def _pump_until(self, condition, timeout):
        deadline = time.monotonic() + timeout
        while not condition():
            self._conn.pump(timeout=0.1)
            if time.monotonic() >= deadline:
                raise BackendError("timeout waiting for Wayland globals")

    def stop(self):
        if self._conn:
            try: self._conn.close()
            except Exception: pass
            self._conn = None
        self._state = "stopped"

    def status(self):
        return {"state": self._state, "transport": "wlroots", "outputs": self._outputs}

    def move_abs(self, x, y):
        if self._state != "started": raise BackendError("backend not started")
        if not self._outputs: raise BackendError("no wl_output for absolute move")
        self._conn.send(self._pointer_id, "zwlr_virtual_pointer_v1", "motion_absolute", (0, to_fixed(float(x)), to_fixed(float(y))))

    def move_rel(self, dx, dy):
        if self._state != "started": raise BackendError("backend not started")
        self._conn.send(self._pointer_id, "zwlr_virtual_pointer_v1", "motion", (0, to_fixed(float(dx)), to_fixed(float(dy))))

    def button(self, button, press):
        if self._state != "started": raise BackendError("backend not started")
        code = BUTTONS.get(str(button).lower(), button) if isinstance(button, str) else button
        self._conn.send(self._pointer_id, "zwlr_virtual_pointer_v1", "button", (0, int(code), press))

    def scroll(self, dx, dy):
        if self._state != "started": raise BackendError("backend not started")
        if dy:
            self._conn.send(self._pointer_id, "zwlr_virtual_pointer_v1", "axis_discrete", (0, 0, to_fixed(float(dy)), dy))
        if dx:
            self._conn.send(self._pointer_id, "zwlr_virtual_pointer_v1", "axis_discrete", (0, 1, to_fixed(float(dx)), dx))

    def key(self, keycode, press):
        if self._state != "started": raise BackendError("backend not started")
        self._conn.send(self._keyboard_id, "zwp_virtual_keyboard_v1", "key", (0, keycode, press))

    def type_text(self, text):
        if self._state != "started": raise BackendError("backend not started")
        for ch in text:
            codepoint = ord(ch)
            ks = codepoint if codepoint <= 0xFF else 0x01000000 + codepoint
            resolved = self._keymap.resolve(ks)
            if resolved is None: continue
            keycode, _level = resolved
            self._conn.send(self._keyboard_id, "zwp_virtual_keyboard_v1", "key", (0, keycode, PRESS))
            self._conn.send(self._keyboard_id, "zwp_virtual_keyboard_v1", "key", (0, keycode, RELEASE))

    def _on_wl_registry_global(self, obj_id, args):
        name, iface, version = args
        if iface == "zwlr_virtual_pointer_manager_v1":
            self._pointer_mgr_id = self._conn.bind(obj_id, name, iface, 1)
        elif iface == "zwp_virtual_keyboard_manager_v1":
            self._keyboard_mgr_id = self._conn.bind(obj_id, name, iface, 1)
        elif iface == "wl_seat":
            self._seat_id = self._conn.bind(obj_id, name, iface, 1)
        elif iface == "wl_output":
            out_id = self._conn.bind(obj_id, name, iface, 1)
            self._outputs.append({"id": out_id, "name": f"output-{name}"})

    def _on_wl_registry_global_remove(self, obj_id, args): pass
    def _on_wl_output_geometry(self, obj_id, args): pass
    def _on_wl_output_mode(self, obj_id, args): pass
    def _on_wl_output_done(self, obj_id, args): pass
    def _on_wl_output_scale(self, obj_id, args): pass
    def _on_wl_seat_capabilities(self, obj_id, args): pass
    def _on_wl_seat_name(self, obj_id, args): pass