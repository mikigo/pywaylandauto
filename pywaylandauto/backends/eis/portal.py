"""Portal EIS connection — GNOME/Ubuntu via XDG Desktop Portal ConnectToEIS."""

import dbus
import dbus.exceptions
import dbus.mainloop.glib

PORTAL_DEST = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
RD_IFACE = "org.freedesktop.portal.RemoteDesktop"


def connect(session_path: str) -> int:
    """Connect to the portal's EIS server, return a socket fd."""
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    obj = bus.get_object(PORTAL_DEST, PORTAL_PATH)
    iface = dbus.Interface(obj, RD_IFACE)
    return iface.ConnectToEIS(session_path, {}).take()