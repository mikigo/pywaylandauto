import errno
import logging
import os
import socket
import time

import gi
gi.require_version("GLib", "2.0")
from gi.repository import GLib

try:
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix
except (ImportError, ValueError):
    GLibUnix = None

from . import __version__, protocol
from .backends.base import BUTTONS, PRESS, RELEASE, BackendError
from .backends.eis.backend import EisBackend, EisError
from .backends.eis.kylin import connect as kylin_connect
from .backends.portal.backend import PortalBackend
from .backends.wlroots.backend import WlrootsBackend
from .backends.wlroots.clipboard import set_clipboard, get_clipboard
from .keysyms import lookup as lookup_keysym

log = logging.getLogger(__name__)

RECV_CHUNK = 65536
IDLE_TIMEOUT = 7200  # seconds (2 hours)


class AlreadyRunningError(Exception):
    """A live daemon already owns the socket."""


def default_socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return os.path.join(runtime, "pywaylandauto.sock")
    return f"/tmp/pywaylandauto-{os.getuid()}.sock"


def default_pid_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return os.path.join(runtime, "pywaylandauto.pid")
    return f"/tmp/pywaylandauto-{os.getuid()}.pid"


def _error_code_for(exc: Exception) -> str:
    if isinstance(exc, protocol.ProtocolError):
        return exc.code
    if isinstance(exc, BackendError):
        return protocol.ERR_BACKEND_ERROR
    return protocol.ERR_INTERNAL


def _param(params: dict, key: str, types, default=None):
    value = params.get(key, default)
    if value is not None and (not isinstance(value, types) or isinstance(value, bool)):
        raise protocol.ProtocolError(
            protocol.ERR_INVALID_PARAMS, f"param {key!r} has invalid type"
        )
    return value


class Daemon:
    def __init__(self, socket_path=None, pid_path=None):
        self.socket_path = socket_path or default_socket_path()
        self.pid_path = pid_path or default_pid_path()
        self._backend = None
        self._loop = None
        self._server = None
        self._buffers = {}
        self._pump_source = None
        self._mouse_x = 0.0
        self._mouse_y = 0.0
        self._scale = 1.0
        self._idle_source = None

    def _to_logical(self, x: float, y: float) -> tuple[float, float]:
        return x, y

    def _reset_idle_timeout(self) -> None:
        if self._idle_source is not None:
            GLib.source_remove(self._idle_source)
            self._idle_source = None
        self._idle_source = GLib.timeout_add_seconds(
            IDLE_TIMEOUT, self._on_idle_timeout
        )

    def _on_idle_timeout(self) -> bool:
        log.info("idle timeout (%ds) reached, shutting down", IDLE_TIMEOUT)
        self.stop()
        return False

    # -- lifecycle -------------------------------------------------------

    def run(self) -> int:
        self._server = self._bind()
        self._write_pid()
        if self._backend is None:
            self._start_backend()
        self._loop = GLib.MainLoop()
        GLib.io_add_watch(self._server, GLib.PRIORITY_DEFAULT, GLib.IO_IN,
                          self._on_server_ready)
        for signum in (15, 2):  # SIGTERM, SIGINT
            if GLibUnix is not None:
                GLibUnix.signal_add_full(GLib.PRIORITY_DEFAULT, signum,
                                         self._on_signal, None)
            else:
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self._on_signal)
        log.info("daemon listening on %s (pid %d)", self.socket_path, os.getpid())
        self._reset_idle_timeout()
        try:
            self._loop.run()
        finally:
            self._cleanup()
        return 0

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.quit()

    def _on_signal(self, *args) -> bool:
        log.info("signal received, shutting down")
        self.stop()
        return False

    def _bind(self) -> socket.socket:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            srv.bind(self.socket_path)
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
            if self._probe_live():
                raise AlreadyRunningError(
                    f"a live daemon already owns {self.socket_path}"
                ) from e
            os.unlink(self.socket_path)
            srv.bind(self.socket_path)
        srv.listen(8)
        os.chmod(self.socket_path, 0o600)
        return srv

    def _probe_live(self) -> bool:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.2)
        try:
            probe.connect(self.socket_path)
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def _write_pid(self) -> None:
        try:
            with open(self.pid_path, "w") as f:
                f.write(str(os.getpid()))
            os.chmod(self.pid_path, 0o600)
        except OSError as e:
            log.warning("cannot write pid file %s: %s", self.pid_path, e)

    def _cleanup(self) -> None:
        if self._idle_source is not None:
            GLib.source_remove(self._idle_source)
            self._idle_source = None
        if self._pump_source is not None:
            GLib.source_remove(self._pump_source)
            self._pump_source = None
        if self._backend is not None:
            try:
                self._backend.stop()
            except Exception:
                pass
        for path in (self.socket_path, self.pid_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as e:
                log.warning("cannot unlink %s: %s", path, e)

    # -- backend ----------------------------------------------------------

    def _start_backend(self) -> None:
        # 1) Kylin EIS (original)
        try:
            be = EisBackend(connect_fn=kylin_connect)
            be.start()
            self._backend = be
            self._start_eis_pump()
            if be.regions:
                self._scale = be.regions[0][4]
            log.info("transport: eis (kylin)  scale=%.1f", self._scale)
            return
        except Exception as e:
            log.info("Kylin EIS backend not available: %s", e)

        # 2) Portal EIS (GNOME/Ubuntu)
        try:
            be = PortalBackend()
            be.on_eis_ready = self._start_eis_pump
            be.start()
            self._backend = be
            log.info("transport: portal (initiating session flow)")
            return
        except Exception as e:
            log.info("Portal backend not available: %s", e)

        # 3) wlroots fallback
        try:
            be = WlrootsBackend()
            be.start()
            self._backend = be
            log.info("transport: wlroots")
        except Exception as e2:
            log.warning("wlroots backend also failed: %s", e2)
            self._backend = None

    def _start_eis_pump(self, *args) -> None:
        if self._backend is None:
            return
        name = getattr(self._backend, "name", "")
        if name not in ("eis", "portal-eis"):
            return
        fd = getattr(self._backend, "fd", -1)
        if fd < 0:
            return
        if self._pump_source is not None:
            GLib.source_remove(self._pump_source)
        self._pump_source = GLib.io_add_watch(
            fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN, self._on_eis_ready
        )
        regions = getattr(self._backend, "regions", None)
        if regions:
            self._scale = regions[0][4]
            log.info("scale updated to %.1f from backend regions", self._scale)

    def _on_eis_ready(self, fd, cond) -> bool:
        if self._backend is None:
            return False
        try:
            self._backend.pump()
        except Exception:
            log.exception("EIS pump failed")
        return True

    def _ensure_started(self) -> None:
        if self._backend is None:
            raise BackendError("backend not ready")
        state = self._backend.state
        if state == "started":
            return
        if state == "starting":
            raise protocol.ProtocolError(
                protocol.ERR_PERMISSION_PENDING,
                "session is starting — grant the dialog and retry",
            )
        raise BackendError("backend not ready")

    def _do_move_abs(self, x: float, y: float) -> None:
        lx, ly = self._to_logical(x, y)
        log.info("_do_move_abs: input=(%.1f, %.1f) logical=(%.1f, %.1f) scale=%.2f backend=%s",
                 x, y, lx, ly, self._scale, getattr(self._backend, "name", "?"))
        self._backend.move_abs(lx, ly)
        self._mouse_x, self._mouse_y = x, y

    def _type_via_clipboard(self, text: str) -> None:
        ok, cleanup = set_clipboard(text)
        if not ok:
            raise BackendError(
                "clipboard set failed — no clipboard backend available"
            )
        time.sleep(0.3)
        self._presskey(["ctrl", "v"])
        time.sleep(0.3)
        if cleanup:
            cleanup()

    def _presskey(self, keys: list[str]) -> None:
        if getattr(self._backend, "name", "") in ("eis", "portal-eis"):
            self._presskey_eis(keys)
        else:
            self._presskey_wlroots(keys)

    # -- socket handling -------------------------------------------------

    def _on_server_ready(self, channel, cond) -> bool:
        try:
            conn, _ = channel.accept()
        except OSError:
            return True
        conn.settimeout(1.0)
        self._buffers[conn.fileno()] = bytearray()
        GLib.io_add_watch(conn, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                          self._on_client_ready)
        return True

    def _on_client_ready(self, channel, cond) -> bool:
        if cond & (GLib.IO_HUP | GLib.IO_ERR):
            self._drop_client(channel)
            return False
        try:
            data = channel.recv(RECV_CHUNK)
        except (socket.timeout, OSError):
            return True
        if not data:
            self._drop_client(channel)
            return False
        buf = self._buffers[channel.fileno()]
        buf.extend(data)
        while b"\n" in buf:
            line, _, rest = buf.partition(b"\n")
            del buf[: len(line) + 1]
            response = self._handle_line(bytes(line))
            if response is not None:
                try:
                    channel.sendall(response)
                except OSError:
                    self._drop_client(channel)
                    return False
        if len(buf) > protocol.MAX_LINE:
            log.warning("client exceeded max line length; dropping")
            self._drop_client(channel)
            return False
        return True

    def _drop_client(self, channel) -> None:
        self._buffers.pop(channel.fileno(), None)
        try:
            channel.close()
        except OSError:
            pass

    # -- dispatch --------------------------------------------------------

    def _handle_line(self, line: bytes) -> bytes | None:
        try:
            req = protocol.decode_request(line.decode("utf-8"))
        except (protocol.ProtocolError, UnicodeDecodeError) as e:
            code = getattr(e, "code", protocol.ERR_INVALID_JSON)
            return protocol.encode_response(
                0, ok=False, error={"code": code, "message": str(e)}
            )
        quit_after = req["method"] == "daemon.stop"
        try:
            result = self._dispatch(req["method"], req["params"])
        except Exception as e:
            code = _error_code_for(e)
            if code == protocol.ERR_INTERNAL:
                log.exception("internal error handling %r", req["method"])
            else:
                log.info("%s -> %s: %s", req["method"], code, e)
            return protocol.encode_response(
                req["id"], ok=False, error={"code": code, "message": str(e)}
            )
        self._reset_idle_timeout()
        response = protocol.encode_response(req["id"], ok=True, result=result)
        if quit_after:
            GLib.timeout_add(50, self._quit_soon)
        return response

    def _quit_soon(self) -> bool:
        self.stop()
        return False

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "ping":
            return {"version": __version__}
        if method == "status":
            return self._status()
        if method == "session.start":
            self._backend.start()
            return {"state": self._backend.state}
        if method == "daemon.stop":
            return {"stopped": True}

        # -- mouse --------------------------------------------------------
        if method == "input.move_abs":
            x = float(_param(params, "x", (int, float), 0))
            y = float(_param(params, "y", (int, float), 0))
            self._ensure_started()
            self._do_move_abs(x, y)
            return {}
        if method == "input.move_rel":
            dx = float(_param(params, "dx", (int, float), 0))
            dy = float(_param(params, "dy", (int, float), 0))
            self._ensure_started()
            self._backend.move_rel(dx, dy)
            self._mouse_x += dx
            self._mouse_y += dy
            return {}
        if method == "input.click":
            x = _param(params, "x", (int, float))
            y = _param(params, "y", (int, float))
            button = params.get("button", "left")
            self._ensure_started()
            if x is not None and y is not None:
                self._do_move_abs(float(x), float(y))
            self._click(button)
            return {}
        if method == "input.double_click":
            x = _param(params, "x", (int, float))
            y = _param(params, "y", (int, float))
            button = params.get("button", "left")
            self._ensure_started()
            if x is not None and y is not None:
                self._do_move_abs(float(x), float(y))
            self._click(button)
            self._click(button)
            return {}
        if method == "input.mouse_down":
            x = _param(params, "x", (int, float))
            y = _param(params, "y", (int, float))
            button = params.get("button", "left")
            self._ensure_started()
            if x is not None and y is not None:
                self._do_move_abs(float(x), float(y))
            self._backend.button(button, PRESS)
            return {}
        if method == "input.mouse_up":
            x = _param(params, "x", (int, float))
            y = _param(params, "y", (int, float))
            button = params.get("button", "left")
            self._ensure_started()
            if x is not None and y is not None:
                self._do_move_abs(float(x), float(y))
            self._backend.button(button, RELEASE)
            return {}
        if method == "input.drag":
            x1 = float(_param(params, "x1", (int, float), 0))
            y1 = float(_param(params, "y1", (int, float), 0))
            x2 = float(_param(params, "x2", (int, float), 0))
            y2 = float(_param(params, "y2", (int, float), 0))
            button = params.get("button", "left")
            self._ensure_started()
            self._do_move_abs(x1, y1)
            self._backend.button(button, PRESS)
            self._do_move_abs(x2, y2)
            self._backend.button(button, RELEASE)
            return {}
        if method == "input.scroll":
            x = _param(params, "x", (int, float))
            y = _param(params, "y", (int, float))
            dx = int(params.get("dx", 0))
            dy = int(params.get("dy", -1))
            self._ensure_started()
            if x is not None and y is not None:
                self._do_move_abs(float(x), float(y))
            self._backend.scroll(dx, dy)
            return {}

        # -- keyboard -----------------------------------------------------
        if method == "input.presskey":
            keys = _param(params, "keys", (list,), [])
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                raise protocol.ProtocolError(
                    protocol.ERR_INVALID_PARAMS,
                    "param 'keys' must be a list of strings",
                )
            self._ensure_started()
            if getattr(self._backend, "name", "") in ("eis", "portal-eis"):
                self._presskey_eis(keys)
            else:
                self._presskey_wlroots(keys)
            return {}
        if method == "input.key_down":
            key = _param(params, "key", (str,), "")
            self._ensure_started()
            self._key_action(key, PRESS)
            return {}
        if method == "input.key_up":
            key = _param(params, "key", (str,), "")
            self._ensure_started()
            self._key_action(key, RELEASE)
            return {}
        if method == "input.type_text":
            text = _param(params, "text", (str,), "")
            self._ensure_started()
            if any(ord(ch) > 0xFF for ch in text):
                log.info("type_text via clipboard: %r", text)
                self._type_via_clipboard(text)
            else:
                log.info("type_text via keyboard: %r", text)
                self._backend.type_text(text)
            return {}
        if method == "input.mouse_position":
            return {"x": self._mouse_x, "y": self._mouse_y}
        if method == "input.get_clipboard":
            text = get_clipboard()
            return {"text": text}

        raise protocol.ProtocolError(
            protocol.ERR_METHOD_NOT_FOUND, f"unknown method {method!r}"
        )

    # -- helpers ----------------------------------------------------------

    def _click(self, button: str) -> None:
        self._backend.button(button, PRESS)
        self._backend.button(button, RELEASE)

    def _key_action(self, key: str, press: int) -> None:
        keysym = lookup_keysym(key)
        if keysym is None:
            raise BackendError(f"unknown key: {key!r}")
        if getattr(self._backend, "name", "") in ("eis", "portal-eis"):
            keycode = self._backend.resolve_key(keysym)
            if keycode is None:
                raise BackendError(f"keysym 0x{keysym:04x} not in keymap")
        else:
            resolved = self._backend._keymap.resolve(keysym)
            if resolved is None:
                raise BackendError(f"keysym 0x{keysym:04x} not in keymap")
            keycode = resolved[0]
        self._backend.key(keycode, press)

    def _presskey_eis(self, keys: list[str]) -> None:
        from .backends.base import PRESS, RELEASE
        keycodes = []
        for key_name in keys:
            keysym = lookup_keysym(key_name)
            if keysym is None:
                raise BackendError(f"unknown key: {key_name!r}")
            kc = self._backend.resolve_key(keysym)
            if kc is None:
                raise BackendError(f"keysym 0x{keysym:04x} not in keymap")
            keycodes.append(kc)
        for kc in keycodes:
            self._backend.key(kc, PRESS)
            time.sleep(0.05)
        for kc in reversed(keycodes):
            self._backend.key(kc, RELEASE)
            time.sleep(0.05)

    def _presskey_wlroots(self, keys: list[str]) -> None:
        keycodes = []
        for key_name in keys:
            keysym = lookup_keysym(key_name)
            if keysym is None:
                raise BackendError(f"unknown key: {key_name!r}")
            resolved = self._backend._keymap.resolve(keysym)
            if resolved is None:
                raise BackendError(f"keysym 0x{keysym:04x} not in keymap")
            keycodes.append(resolved[0])
        for kc in keycodes:
            self._backend.key(kc, PRESS)
        for kc in reversed(keycodes):
            self._backend.key(kc, RELEASE)

    # -- status -----------------------------------------------------------

    def _status(self) -> dict:
        backend_info = {}
        if self._backend is not None:
            backend_info = self._backend.status()

        keymap_info = {}
        try:
            if hasattr(self._backend, '_resolver') and self._backend._resolver is not None:
                ctrl_kc = self._backend._resolver(0xFFE3)  # Control_L
                v_kc = self._backend._resolver(0x0076)     # v
                keymap_info = {"ctrl_keycode": ctrl_kc, "v_keycode": v_kc}
        except Exception:
            pass

        return {
            "daemon": {"pid": os.getpid(), "socket": self.socket_path},
            "backend": backend_info,
            "mouse": {"x": self._mouse_x, "y": self._mouse_y},
            "scale": self._scale,
            "keymap": keymap_info,
        }