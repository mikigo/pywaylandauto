"""Wayland clipboard via zwlr_data_control_manager_v1 — no serial required."""

import logging
import os
import socket
import threading
import time

from .wayland import WaylandConnection

log = logging.getLogger(__name__)

# wlr-data-control protocol tables
WLR_DATA_CONTROL_MGR_REQ = {
    "create_data_source": (0, "n"),
    "get_data_device": (1, "no"),
}
WLR_DATA_CONTROL_DEVICE_REQ = {
    "set_selection": (0, "o"),
    "destroy": (1, ""),
}
WLR_DATA_CONTROL_SOURCE_REQ = {
    "offer": (0, "s"),
    "destroy": (1, ""),
}
WLR_DATA_CONTROL_SOURCE_EVT = {
    "send": (0, "sh"),
    "cancelled": (1, ""),
}


class ClipboardError(Exception):
    pass


class _ClipboardSession:
    def __init__(self, text: str):
        self._text = text.encode("utf-8")
        self._conn = None
        self._manager_id = None
        self._seat_id = None
        self._data_device_id = None
        self._done = threading.Event()
        self._selection_set = threading.Event()

    def run(self):
        try:
            self._connect()
            self._set_selection()
            deadline = time.monotonic() + 3.0
            while not self._done.is_set() and time.monotonic() < deadline:
                self._conn.pump(timeout=0.1)
        except Exception as e:
            log.debug("clipboard error: %s", e)
        finally:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass

    def _connect(self):
        rt = os.environ.get("XDG_RUNTIME_DIR")
        disp = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(os.path.join(rt, disp))
        self._conn = WaylandConnection(sock.detach())
        self._conn.handler = self
        self._conn.objects[self._conn.display_id] = "wl_display"
        rid = self._conn.alloc_id()
        self._conn.objects[rid] = "wl_registry"
        self._conn.send(self._conn.display_id, "wl_display",
                        "get_registry", (rid,))

        dl = time.monotonic() + 2.0
        while self._manager_id is None or self._seat_id is None:
            self._conn.pump(timeout=0.1)
            if time.monotonic() >= dl:
                raise ClipboardError("wlr_data_control not available")

        self._data_device_id = self._conn.alloc_id()
        self._conn.objects[self._data_device_id] = "zwlr_data_control_device_v1"
        self._conn.send(self._manager_id, "zwlr_data_control_manager_v1",
                        "get_data_device",
                        (self._data_device_id, self._seat_id))
        self._conn.sync(timeout=1.0)

    def _set_selection(self):
        sid = self._conn.alloc_id()
        self._conn.objects[sid] = "zwlr_data_control_source_v1"
        self._conn.send(self._manager_id, "zwlr_data_control_manager_v1",
                        "create_data_source", (sid,))
        self._conn.send(sid, "zwlr_data_control_source_v1",
                        "offer", ("text/plain;charset=utf-8",))
        # set_selection, then roundtrip to ensure compositor processes it
        self._conn.send(self._data_device_id, "zwlr_data_control_device_v1",
                        "set_selection", (sid,))
        self._conn.sync(timeout=2.0)

    # -- Wayland event handlers -------------------------------------------

    def _on_wl_registry_global(self, obj_id, args):
        name, iface, version = args
        if iface == "zwlr_data_control_manager_v1":
            self._manager_id = self._conn.bind(obj_id, name, iface, 1)
        elif iface == "wl_seat":
            self._seat_id = self._conn.bind(obj_id, name, iface, 1)

    def _on_wl_registry_global_remove(self, obj_id, args):
        pass

    def _on_zwlr_data_control_source_v1_send(self, obj_id, args):
        _mime_type, fd = args
        try:
            os.write(fd, self._text)
        except OSError:
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def _on_zwlr_data_control_source_v1_cancelled(self, obj_id, args):
        self._done.set()

    def _on_wl_seat_capabilities(self, obj_id, args):
        pass

    def _on_wl_seat_name(self, obj_id, args):
        pass


def set_clipboard(text: str):
    log.info("clipboard: setting %d bytes via wlr-data-control", len(text.encode("utf-8")))
    session = _ClipboardSession(text)
    t = threading.Thread(target=session.run, daemon=True)
    t.start()
    time.sleep(0.2)
    return t