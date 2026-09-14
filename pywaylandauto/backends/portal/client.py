"""Thin D-Bus glue for XDG Desktop Portal RemoteDesktop.

PortalSession depends on this narrow interface, so the state machine is
testable against a fake and the D-Bus layer can be swapped (e.g. to
gi.Gio.DBus) without touching the flow logic.
"""

import logging

import dbus
import dbus.exceptions
import dbus.mainloop.glib

from ...protocol import (
    ERR_CANCELLED,
    ERR_PERMISSION_DENIED,
    ERR_PORTAL_FAILED,
    ERR_PORTAL_UNAVAILABLE,
    ProtocolError,
)

log = logging.getLogger(__name__)

PORTAL_DEST = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
RD_IFACE = "org.freedesktop.portal.RemoteDesktop"
SESSION_IFACE = "org.freedesktop.portal.Session"

ERR_NOT_ALLOWED = "org.freedesktop.portal.Error.NotAllowed"
ERR_CANCELLED_DBUS = "org.freedesktop.portal.Error.Cancelled"
ERR_INVALID_ARG = "org.freedesktop.portal.Error.InvalidArgument"
ERR_EXISTS = "org.freedesktop.portal.Error.Exists"
ERR_NOT_FOUND = "org.freedesktop.portal.Error.NotFound"
ERR_FAILED = "org.freedesktop.portal.Error.Failed"


def map_dbus_error(e: dbus.exceptions.DBusException) -> ProtocolError:
    name = e.get_dbus_name()
    if name in (ERR_NOT_ALLOWED, "org.freedesktop.DBus.Error.AccessDenied"):
        return ProtocolError(ERR_PERMISSION_DENIED, str(e))
    if name == ERR_CANCELLED_DBUS:
        return ProtocolError(ERR_CANCELLED, str(e))
    if name in (ERR_INVALID_ARG, ERR_EXISTS, ERR_NOT_FOUND, ERR_FAILED):
        return ProtocolError(ERR_PORTAL_FAILED, str(e))
    if name in ("org.freedesktop.DBus.Error.ServiceUnknown",
                "org.freedesktop.DBus.Error.UnknownMethod",
                "org.freedesktop.DBus.Error.UnknownInterface"):
        return ProtocolError(ERR_PORTAL_UNAVAILABLE, str(e))
    return ProtocolError(ERR_PORTAL_FAILED, str(e))


class PortalClient:
    def __init__(self, bus=None):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = bus if bus is not None else dbus.SessionBus()
        obj = self.bus.get_object(PORTAL_DEST, PORTAL_PATH)
        self._rd = dbus.Interface(obj, RD_IFACE)
        unique = self.bus.get_unique_name()
        self._sender = unique.lstrip(":").replace(".", "_")

    @property
    def sender(self) -> str:
        return self._sender

    def request_path(self, token: str) -> str:
        return f"/org/freedesktop/portal/desktop/request/{self._sender}/{token}"

    def add_response_listener(self, token: str, callback) -> None:
        path = self.request_path(token)
        self.bus.add_signal_receiver(
            lambda response, results: callback(int(response), results),
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.Request",
            path=path,
        )
        self.bus.add_signal_receiver(
            lambda _token, response, results: callback(int(response), results),
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.PersistentRequest",
            path=path,
        )

    def add_session_closed_listener(self, session_path: str, callback) -> None:
        self.bus.add_signal_receiver(
            lambda details: callback(),
            signal_name="Closed",
            dbus_interface=SESSION_IFACE,
            path=session_path,
        )

    def create_session(self, options: dict) -> str:
        return str(self._rd.CreateSession(options))

    def select_devices(self, session_path: str, options: dict) -> None:
        self._rd.SelectDevices(session_path, options)

    def start(self, session_path: str, parent_window: str, options: dict) -> None:
        self._rd.Start(session_path, parent_window, options)

    def notify_pointer_motion(self, session_path: str, dx: float, dy: float) -> None:
        self._rd.NotifyPointerMotion(session_path, {}, dx, dy)

    def notify_pointer_motion_absolute(self, session_path: str, x: float, y: float) -> None:
        self._rd.NotifyPointerMotionAbsolute(session_path, {}, 0, x, y)

    def notify_pointer_button(self, session_path: str, button: int, state: int) -> None:
        self._rd.NotifyPointerButton(session_path, {}, button, state)

    def notify_pointer_axis(self, session_path: str, dx: float, dy: float) -> None:
        self._rd.NotifyPointerAxis(session_path, {}, dx, dy)

    def notify_pointer_axis_discrete(self, session_path: str, axis: int, steps: int) -> None:
        self._rd.NotifyPointerAxisDiscrete(session_path, {}, axis, steps)

    def notify_keyboard_keycode(self, session_path: str, keycode: int, state: int) -> None:
        self._rd.NotifyKeyboardKeycode(session_path, {}, keycode, state)

    def notify_keyboard_keysym(self, session_path: str, keysym: int, state: int) -> None:
        self._rd.NotifyKeyboardKeysym(session_path, {}, keysym, state)

    def connect_to_eis(self, session_path: str) -> int:
        return self._rd.ConnectToEIS(session_path, {}).take()

    def close_session(self, session_path: str) -> None:
        try:
            obj = self.bus.get_object(PORTAL_DEST, session_path)
            dbus.Interface(obj, SESSION_IFACE).Close()
        except dbus.exceptions.DBusException as e:
            log.debug("Session.Close on %s: %s", session_path, e)