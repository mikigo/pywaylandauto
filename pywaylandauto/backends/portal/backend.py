"""Portal backend — XDG Desktop Portal RemoteDesktop session + EIS transport.

The portal session flow is async (D-Bus signals), so start() is non-blocking.
When the session is ready, on_eis_ready() callback fires so the daemon can
register the EIS pump.
"""

import logging
import secrets

import dbus
import dbus.exceptions

from ... import token_cache
from ..base import (
    AXIS_HORIZONTAL, AXIS_VERTICAL,
    BUTTONS, PRESS, RELEASE,
    Backend, BackendError,
)
from ...keysyms import lookup as lookup_keysym
from ...protocol import (
    ERR_PERMISSION_DENIED,
    ERR_PERMISSION_PENDING,
    ERR_PORTAL_FAILED,
    ERR_SESSION_NOT_STARTED,
    ProtocolError,
)
from ..eis.backend import EisBackend, EisError
from ..xkb import build_resolver
from .client import PortalClient, map_dbus_error

log = logging.getLogger(__name__)

PERSIST_MODE = 2
DEVICE_TYPES = 1 | 2  # keyboard | pointer


def new_handle_token() -> str:
    return "pywaylandauto_" + secrets.token_hex(8)


class _SessionHelper:
    """Portal session flow state machine.

    Manages the CreateSession → SelectDevices → Start portal flow.
    Callbacks arrive via GLib D-Bus signal handlers.
    """

    def __init__(self, portal_client: PortalClient, tk_cache=None):
        self._portal = portal_client
        self._tk = tk_cache if tk_cache is not None else token_cache.TokenCache()
        self.state = "init"
        self.session_path: str | None = None
        self.devices: list = []
        self.transport: str | None = None
        self.last_error: ProtocolError | None = None
        self._has_token = False
        self.on_started = None

    def start(self) -> None:
        if self.state in ("starting", "started"):
            return
        self.state = "starting"
        self.last_error = None
        self.session_path = None
        self.devices = []
        self.transport = None
        self._has_token = self._tk.load() is not None
        flow_token = new_handle_token()
        self._portal.add_response_listener(flow_token, self._on_create_session)
        options = {
            "handle_token": dbus.String(flow_token),
            "session_handle_token": dbus.String(new_handle_token()),
        }
        try:
            self._portal.create_session(options)
        except dbus.exceptions.DBusException as e:
            self._fail(map_dbus_error(e))

    def _on_create_session(self, code: int, results: dict) -> None:
        try:
            if code != 0:
                self._fail(ProtocolError(
                    ERR_PORTAL_FAILED,
                    f"CreateSession failed with code {code}",
                ))
                return
            self.session_path = str(results["session_handle"])
            self._portal.add_session_closed_listener(
                self.session_path, self._on_closed,
            )
            self._select_devices()
        except Exception:
            log.exception("CreateSession callback failed")
            self._fail(ProtocolError(ERR_PORTAL_FAILED, "callback error"))

    def _select_devices(self) -> None:
        token = new_handle_token()
        self._portal.add_response_listener(token, self._on_select_devices)
        options = {
            "types": dbus.UInt32(DEVICE_TYPES),
            "persist_mode": dbus.UInt32(PERSIST_MODE),
            "handle_token": dbus.String(token),
        }
        if self._has_token:
            cached = self._tk.load()
            if cached:
                options["restore_token"] = dbus.String(cached)
        try:
            self._portal.select_devices(self.session_path, options)
        except dbus.exceptions.DBusException as e:
            self._fail(map_dbus_error(e))

    def _on_select_devices(self, code: int, results: dict) -> None:
        try:
            if code != 0:
                self._fail(ProtocolError(
                    ERR_PORTAL_FAILED,
                    f"SelectDevices failed with code {code}",
                ))
                return
            token = new_handle_token()
            self._portal.add_response_listener(token, self._on_start)
            self._portal.start(self.session_path, "",
                               {"handle_token": dbus.String(token)})
        except dbus.exceptions.DBusException as e:
            self._fail(map_dbus_error(e))

    def _on_start(self, code: int, results: dict) -> None:
        try:
            if code == 0:
                if "restore_token" in results:
                    self._tk.save(str(results["restore_token"]))
                    self._has_token = True
                devices = results.get("devices", [])
                if isinstance(devices, (int, dbus.UInt32)):
                    devices = [devices]
                self.devices = [str(d) for d in devices]
                self.state = "started"
                log.info("Portal session %s started; devices=%s",
                         self.session_path, self.devices)
                if self.on_started:
                    self._schedule(self.on_started)
            elif code == 1:
                self._fail(ProtocolError(
                    ERR_PERMISSION_DENIED,
                    "user denied the interaction dialog",
                ))
            else:
                self._fail(ProtocolError(
                    ERR_PORTAL_FAILED,
                    f"Start failed with code {code}",
                ))
        except Exception:
            log.exception("Start callback failed")
            self._fail(ProtocolError(ERR_PORTAL_FAILED, "callback error"))

    def _on_closed(self) -> None:
        log.info("Session %s closed externally", self.session_path)
        if self.state != "stopped":
            self.state = "stopped"
            self.session_path = None
            self.devices = []
            if self.last_error is None:
                self.last_error = ProtocolError(
                    ERR_SESSION_NOT_STARTED,
                    "session closed by the portal",
                )

    def _fail(self, error: ProtocolError) -> None:
        self.state = "stopped"
        self.last_error = error
        self.session_path = None
        self.devices = []
        log.error("Session failed: %s", error)

    def stop(self) -> None:
        if self.session_path is not None:
            self._portal.close_session(self.session_path)
        self.state = "stopped"
        self.session_path = None
        self.devices = []

    def status(self) -> dict:
        return {
            "state": self.state,
            "devices": list(self.devices),
            "transport": self.transport,
            "has_token": self._has_token,
            "persist_mode": PERSIST_MODE,
            "error": (type(self.last_error).__name__
                      if self.last_error else None),
        }

    @staticmethod
    def _schedule(fn):
        try:
            import gi
            gi.require_version("GLib", "2.0")
            from gi.repository import GLib
            GLib.idle_add(fn)
        except Exception:
            fn()


class PortalBackend(Backend):
    name = "portal-eis"

    def __init__(self, portal_client=None):
        self._portal_client = portal_client or PortalClient()
        self._session = _SessionHelper(self._portal_client)
        self._session.on_started = self._setup_eis
        self._resolver = None
        self._eis: EisBackend | None = None
        self._transport: str | None = None
        self._state = "init"
        self.regions: list = []
        self.on_eis_ready = None

    @property
    def state(self):
        return self._state

    @property
    def session_path(self):
        return self._session.session_path

    @property
    def fd(self):
        if self._eis:
            return getattr(self._eis, 'fd', -1)
        return -1

    def start(self):
        if self._state in ("starting", "started"):
            return
        self._state = "starting"
        self._session.start()

    def _setup_eis(self):
        if self._state != "starting" or self._session.state != "started":
            return
        try:
            from ..eis.portal import connect as portal_eis_connect
            fd = portal_eis_connect(self._session.session_path)
        except dbus.exceptions.DBusException as e:
            log.warning("ConnectToEIS failed (%s) — falling back to notify", e)
            self._probe_notify()
            return
        try:
            self._eis = EisBackend(connect_fn=lambda: fd)
            self._eis.start()
            self.regions = list(self._eis.regions)
            self._transport = "eis"
            self._state = "started"
            self._session.transport = "eis"
            self._build_resolver()
            log.info("Portal EIS transport ready (regions=%s)", self.regions)
            if self.on_eis_ready:
                try:
                    self.on_eis_ready()
                except Exception:
                    log.exception("on_eis_ready callback failed")
        except Exception as e:
            log.warning("EIS setup failed: %s; falling back to notify", e)
            self._probe_notify()

    def _probe_notify(self):
        try:
            self._portal_client.notify_pointer_motion(
                self._session.session_path, 0.0, 0.0,
            )
            self._transport = "notify"
            self._state = "started"
            self._session.transport = "notify"
            log.info("Transport: notify")
        except dbus.exceptions.DBusException as e:
            self._fail(ProtocolError(
                ERR_PORTAL_FAILED,
                f"portal rejected Notify* calls: {e}",
            ))

    def _fail(self, error):
        self._session._fail(error)
        self._state = "stopped"

    def _build_resolver(self):
        from ..xkb import us_fallback
        self._resolver = us_fallback().resolve

    def pump(self):
        if self._eis:
            try:
                self._eis.pump()
            except Exception:
                pass

    def stop(self):
        if self._eis:
            try:
                self._eis.stop()
            except Exception:
                pass
            self._eis = None
        self._session.stop()
        self._state = "stopped"

    def status(self):
        base = self._session.status()
        eis_status = {}
        if self._eis:
            eis_status = {"eis_state": self._eis.state,
                          "regions": self._eis.regions}
        return {**base, **eis_status, "transport": self._transport}

    def move_abs(self, x, y):
        self._require_started()
        if self._transport == "eis" and self._eis:
            self._eis.move_abs(float(x), float(y))
        elif self._transport == "notify":
            try:
                self._portal_client.notify_pointer_motion_absolute(
                    self._session.session_path, float(x), float(y))
            except dbus.exceptions.DBusException as e:
                raise map_dbus_error(e) from e
        else:
            raise BackendError("absolute pointer motion needs EIS transport")

    def move_rel(self, dx, dy):
        self._require_started()
        if self._transport == "eis" and self._eis:
            self._eis.move_rel(float(dx), float(dy))
        elif self._transport == "notify":
            try:
                self._portal_client.notify_pointer_motion(
                    self._session.session_path, float(dx), float(dy))
            except dbus.exceptions.DBusException as e:
                raise map_dbus_error(e) from e
        else:
            raise BackendError("no transport available")

    def button(self, button, press):
        self._require_started()
        code = self._button_code(button)
        if self._transport == "eis" and self._eis:
            self._eis.button(code, press)
        elif self._transport == "notify":
            try:
                self._portal_client.notify_pointer_button(
                    self._session.session_path, code, press)
            except dbus.exceptions.DBusException as e:
                raise map_dbus_error(e) from e

    @staticmethod
    def _button_code(button):
        if isinstance(button, int):
            return button
        code = BUTTONS.get(str(button).lower())
        if code is None:
            raise ValueError(f"unknown button {button!r}")
        return code

    def scroll(self, dx, dy):
        self._require_started()
        if self._transport == "eis" and self._eis:
            self._eis.scroll(int(dx), int(dy))
        elif self._transport == "notify":
            try:
                if dy:
                    self._portal_client.notify_pointer_axis_discrete(
                        self._session.session_path, AXIS_VERTICAL, int(dy))
                if dx:
                    self._portal_client.notify_pointer_axis_discrete(
                        self._session.session_path, AXIS_HORIZONTAL, int(dx))
            except dbus.exceptions.DBusException as e:
                raise map_dbus_error(e) from e

    def key(self, keycode, press):
        self._require_started()
        if self._transport == "eis" and self._eis:
            self._eis.key(keycode, press)
        elif self._transport == "notify":
            try:
                self._portal_client.notify_keyboard_keycode(
                    self._session.session_path, keycode, press)
            except dbus.exceptions.DBusException as e:
                raise map_dbus_error(e) from e

    def key_sequence(self, *key_events):
        self._require_started()
        if self._transport == "eis" and self._eis:
            self._eis.key_sequence(*key_events)
        else:
            for keycode, press in key_events:
                self.key(keycode, press)

    def key_combo_frame(self, *keycodes: int):
        self._require_started()
        if self._transport == "eis" and self._eis:
            self._eis.key_combo_frame(*keycodes)
        else:
            for kc in keycodes[:-1]:
                self.key(kc, 1)
            self.key(keycodes[-1], 1)
            self.key(keycodes[-1], 0)
            for kc in reversed(keycodes[:-1]):
                self.key(kc, 0)

    def resolve_key(self, keysym):
        if self._resolver is None:
            return None
        resolved = self._resolver(keysym)
        if resolved is None:
            return None
        return resolved[0]

    def type_text(self, text):
        self._require_started()
        if self._transport == "eis" and self._eis:
            self._eis.type_text(text)
        elif self._transport == "notify":
            for ch in text:
                codepoint = ord(ch)
                if codepoint > 0xFF:
                    raise BackendError(
                        f"character {ch!r} (U+{codepoint:04X}) is beyond Latin-1")
                try:
                    self._portal_client.notify_keyboard_keysym(
                        self._session.session_path, codepoint, PRESS)
                    self._portal_client.notify_keyboard_keysym(
                        self._session.session_path, codepoint, RELEASE)
                except dbus.exceptions.DBusException as e:
                    raise map_dbus_error(e) from e

    def _require_started(self):
        if self._state == "started":
            return
        if self._session.state == "starting":
            raise ProtocolError(
                ERR_PERMISSION_PENDING,
                "session start in progress — grant the dialog",
            )
        last = self._session.last_error
        if last:
            raise last
        raise ProtocolError(
            ERR_SESSION_NOT_STARTED, "no portal session",
        )