"""Wayland clipboard — wlr-data-control + Portal Clipboard + GTK fallback."""

import logging
import os
import socket
import subprocess
import threading
import time

from .wayland import WaylandConnection

log = logging.getLogger(__name__)

CLIPBOARD_TIMEOUT = 5.0


class ClipboardError(Exception):
    pass


# --- wlr-data-control (for wlroots / Sway / Kylin) ------------------------

class _WlrSession:
    def __init__(self, text: str):
        self._text = text.encode("utf-8")
        self._conn = None
        self._manager_id = None
        self._seat_id = None
        self._data_device_id = None
        self._ready = threading.Event()
        self._error = None

    def run(self):
        try:
            self._connect()
            self._set_selection()
        except Exception as e:
            log.warning("wlr-data-control error: %s", e)
            self._error = str(e)
        finally:
            self._ready.set()

        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and self._conn:
                self._conn.pump(timeout=0.1)
        except Exception:
            pass
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

        dl = time.monotonic() + 3.0
        while self._manager_id is None or self._seat_id is None:
            self._conn.pump(timeout=0.1)
            if time.monotonic() >= dl:
                raise ClipboardError("wlr_data_control not available")

        self._data_device_id = self._conn.alloc_id()
        self._conn.objects[self._data_device_id] = "zwlr_data_control_device_v1"
        self._conn.send(self._manager_id, "zwlr_data_control_manager_v1",
                        "get_data_device",
                        (self._data_device_id, self._seat_id))
        self._conn.sync(timeout=2.0)

    def _set_selection(self):
        sid = self._conn.alloc_id()
        self._conn.objects[sid] = "zwlr_data_control_source_v1"
        self._conn.send(self._manager_id, "zwlr_data_control_manager_v1",
                        "create_data_source", (sid,))
        self._conn.send(sid, "zwlr_data_control_source_v1",
                        "offer", ("text/plain;charset=utf-8",))
        self._conn.send(self._data_device_id, "zwlr_data_control_device_v1",
                        "set_selection", (sid,))
        self._conn.sync(timeout=2.0)

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
        pass

    def _on_wl_seat_capabilities(self, obj_id, args):
        pass

    def _on_wl_seat_name(self, obj_id, args):
        pass


def set_clipboard_wlr(text: str, pump_fn=None) -> bool:
    session = _WlrSession(text)
    t = threading.Thread(target=session.run, daemon=True)
    t.start()

    deadline = time.monotonic() + CLIPBOARD_TIMEOUT
    while not session._ready.is_set() and time.monotonic() < deadline:
        if pump_fn:
            pump_fn()
        time.sleep(0.05)

    if not session._ready.is_set():
        log.warning("wlr-clipboard: timed out after %.1fs", CLIPBOARD_TIMEOUT)
        return False
    if session._error is not None:
        log.warning("wlr-clipboard: failed: %s", session._error)
        return False
    time.sleep(0.2)
    return True


# --- GTK clipboard (for GNOME) -------------------------------------------

def _gdk_display():
    import gi
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk

    display = Gdk.Display.get_default()
    if not display:
        disp_name = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        try:
            display = Gdk.Display.open(disp_name)
        except Exception as e:
            log.warning("Gdk.Display.open(%s) failed: %s", disp_name, e)
            return None
    return display


def _set_clipboard_wlcopy(text: str) -> subprocess.Popen | None:
    """Start wl-copy, write text, return process handle. Caller must terminate."""
    import subprocess
    try:
        proc = subprocess.Popen(
            ["wl-copy"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
        time.sleep(0.2)
        log.info("wl-copy: set %d bytes", len(text.encode("utf-8")))
        return proc
    except FileNotFoundError:
        log.debug("wl-copy not found")
        return None
    except Exception as e:
        log.warning("wl-copy failed: %s", e)
        return None


def _kill_wlcopy(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        pass


def set_clipboard_gtk(text: str) -> bool:
    proc = _set_clipboard_wlcopy(text)
    if proc is not None:
        time.sleep(0.1)
        _kill_wlcopy(proc)
        return True

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gtk, Gdk

    display = _gdk_display()
    if not display:
        log.warning("gtk-clipboard: no Gdk display")
        return False

    try:
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()
        log.info("gtk-clipboard: set %d bytes via GTK", len(text.encode("utf-8")))
        return True
    except Exception as e:
        log.warning("gtk-clipboard: failed: %s", e)
        return False


# --- unified API --------------------------------------------------------

def set_clipboard(text: str, pump_fn=None, session_path: str | None = None) -> tuple[bool, callable | None]:
    log.info("clipboard: setting %d bytes", len(text.encode("utf-8")))

    proc = _set_clipboard_wlcopy(text)
    if proc is not None:
        log.info("clipboard: set via wl-copy")
        return True, lambda: _kill_wlcopy(proc)

    if set_clipboard_wlr(text, pump_fn=pump_fn):
        log.info("clipboard: set via wlr-data-control")
        return True, None

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gtk, Gdk

    display = _gdk_display()
    if display:
        try:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(text, -1)
            clipboard.store()
            log.info("clipboard: set via GTK")
            return True, None
        except Exception as e:
            log.warning("gtk-clipboard: failed: %s", e)

    log.warning("clipboard: all methods failed")
    return False, None


def get_clipboard() -> str | None:
    import subprocess

    try:
        result = subprocess.run(
            ["wl-paste", "--no-newline"],
            capture_output=True, text=True, timeout=5.0,
        )
        if result.returncode == 0:
            text = result.stdout
            log.info("clipboard get: %d bytes via wl-paste", len(text.encode("utf-8")))
            return text
    except FileNotFoundError:
        log.debug("wl-paste not found, trying GTK")
    except Exception as e:
        log.warning("clipboard get via wl-paste: %s, trying GTK", e)

    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gtk, Gdk

        display = _gdk_display()
        if not display:
            return None

        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = clipboard.wait_for_text()
        if text is not None:
            log.info("clipboard get: %d bytes via GTK", len(text.encode("utf-8")))
        return text
    except Exception as e:
        log.warning("clipboard get via GTK: %s", e)
        return None