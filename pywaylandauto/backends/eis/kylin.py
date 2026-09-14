"""Kylin kylin-wlcom EIS connection via com.kylin.Wlcom.EIS.RemoteDesktop D-Bus."""

import dbus
import dbus.exceptions
import dbus.mainloop.glib


KYLIN_EIS_DEST = "com.kylin.Wlcom"
KYLIN_EIS_PATH = "/com/kylin/Wlcom/EIS/RemoteDesktop"
KYLIN_EIS_IFACE = "com.kylin.Wlcom.EIS.RemoteDesktop"


def connect():
    """Connect to kylin-wlcom's EIS server, return a socket fd."""
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    obj = bus.get_object(KYLIN_EIS_DEST, KYLIN_EIS_PATH)
    iface = dbus.Interface(obj, KYLIN_EIS_IFACE)
    return iface.ConnectToEIS().take()