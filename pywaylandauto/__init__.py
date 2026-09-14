"""pywaylandauto — Wayland keyboard/mouse input injection for Kylin OS."""
from .__version__ import VERSION
__version__ = VERSION

from .client import Client

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = Client(auto_spawn=True)
    return _client

def move(x, y):        _get_client().move_abs(x, y)
def move_rel(dx, dy):  _get_client().move_rel(dx, dy)
def click(x, y, button="left"): _get_client().click(x, y, button)
def right_click(x, y):  _get_client().click(x, y, "right")
def middle_click(x, y): _get_client().click(x, y, "middle")
def double_click(x, y, button="left"): _get_client().double_click(x, y, button)
def mouse_down(x, y, button="left"): _get_client().mouse_down(x, y, button)
def mouse_up(x, y, button="left"):   _get_client().mouse_up(x, y, button)
def drag(x1, y1, x2, y2, button="left"): _get_client().drag(x1, y1, x2, y2, button)
def scroll(x, y, dx=0, dy=-1): _get_client().scroll(x, y, dx, dy)
def input(text):        _get_client().type_text(text)
def key(*keys):    _get_client().key(*keys)
def key_down(key):      _get_client().key_down(key)
def key_up(key):        _get_client().key_up(key)

def mouse_position():
    return _get_client().mouse_position()

def get_clipboard():
    return _get_client().get_clipboard()

def daemon_start():
    """启动 daemon（前台阻塞运行）"""
    from .daemon import Daemon; Daemon().run()