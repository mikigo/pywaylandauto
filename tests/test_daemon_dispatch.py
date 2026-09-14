"""Unit tests for daemon dispatch — maps protocol methods to backend calls."""

from unittest.mock import MagicMock, call, patch

import pytest

from pywaylandauto import protocol
from pywaylandauto.daemon import Daemon, _param
from pywaylandauto.backends.base import BUTTONS, PRESS, RELEASE, BackendError


class _FakeBackend:
    """Fake backend that records calls. Both .state and .name, plus EIS .resolve_key."""

    def __init__(self, name="fake", with_resolve=True):
        self.name = name
        self._state = "started"
        self.calls = []
        self.keymap = MagicMock()
        self._resolved = {}  # keysym -> keycode

    @property
    def state(self):
        return self._state

    def move_abs(self, x, y):
        self.calls.append(("move_abs", x, y))

    def move_rel(self, dx, dy):
        self.calls.append(("move_rel", dx, dy))

    def button(self, button, press):
        self.calls.append(("button", button, press))

    def scroll(self, dx, dy):
        self.calls.append(("scroll", dx, dy))

    def key(self, keycode, press):
        self.calls.append(("key", keycode, press))

    def key_sequence(self, *events):
        for keycode, press in events:
            self.calls.append(("key", keycode, press))

    def type_text(self, text):
        self.calls.append(("type_text", text))

    def resolve_key(self, keysym):
        return self._resolved.get(keysym, 30)  # default keycode=30 (a)

    def stop(self):
        pass

    def status(self):
        return {"state": self._state, "transport": self.name}

    def start(self):
        self._state = "started"


def _make_daemon(backend=None):
    d = Daemon.__new__(Daemon)
    d.socket_path = "/tmp/test.sock"
    d.pid_path = "/tmp/test.pid"
    d._backend = backend or _FakeBackend()
    d._keymap_text = None
    d._resolver = None
    d._mouse_x = 0.0
    d._mouse_y = 0.0
    d._scale = 1.0
    return d


class TestDaemonDispatch:
    """Every protocol method → correct backend call."""

    # -- meta methods -------------------------------------------------------

    def test_ping(self):
        d = _make_daemon()
        r = d._dispatch("ping", {})
        assert r["version"] == "0.1.0"  # or whatever __version__ is

    def test_status(self):
        d = _make_daemon()
        r = d._dispatch("status", {})
        assert "daemon" in r
        assert "backend" in r
        assert "mouse" in r
        assert r["mouse"] == {"x": 0.0, "y": 0.0}

    def test_mouse_position(self):
        d = _make_daemon()
        d._dispatch("input.move_abs", {"x": 100.0, "y": 200.0})
        r = d._dispatch("input.mouse_position", {})
        assert r == {"x": 100.0, "y": 200.0}

    def test_mouse_position_tracked_in_status(self):
        d = _make_daemon()
        d._dispatch("input.move_abs", {"x": 300.0, "y": 400.0})
        r = d._dispatch("status", {})
        assert r["mouse"] == {"x": 300.0, "y": 400.0}

    def test_daemon_stop(self):
        d = _make_daemon()
        r = d._dispatch("daemon.stop", {})
        assert r == {"stopped": True}

    # -- mouse --------------------------------------------------------------

    def test_move_abs(self):
        d = _make_daemon()
        d._dispatch("input.move_abs", {"x": 100.0, "y": 200.0})
        assert d._backend.calls == [("move_abs", 100.0, 200.0)]

    def test_move_rel(self):
        d = _make_daemon()
        d._dispatch("input.move_rel", {"dx": 10.0, "dy": 20.0})
        assert d._backend.calls == [("move_rel", 10.0, 20.0)]

    def test_click(self):
        d = _make_daemon()
        d._dispatch("input.click", {"x": 100.0, "y": 200.0})
        assert d._backend.calls == [
            ("move_abs", 100.0, 200.0),
            ("button", "left", PRESS),
            ("button", "left", RELEASE),
        ]

    def test_click_right_button(self):
        d = _make_daemon()
        d._dispatch("input.click", {"x": 300, "y": 400, "button": "right"})
        assert d._backend.calls == [
            ("move_abs", 300.0, 400.0),
            ("button", "right", PRESS),
            ("button", "right", RELEASE),
        ]

    def test_double_click(self):
        d = _make_daemon()
        d._dispatch("input.double_click", {"x": 100, "y": 200})
        assert d._backend.calls == [
            ("move_abs", 100.0, 200.0),
            ("button", "left", PRESS),
            ("button", "left", RELEASE),
            ("button", "left", PRESS),
            ("button", "left", RELEASE),
        ]

    def test_mouse_down(self):
        d = _make_daemon()
        d._dispatch("input.mouse_down", {"x": 100, "y": 200})
        assert d._backend.calls == [
            ("move_abs", 100.0, 200.0),
            ("button", "left", PRESS),
        ]

    def test_mouse_up(self):
        d = _make_daemon()
        d._dispatch("input.mouse_up", {"x": 500, "y": 300, "button": "right"})
        assert d._backend.calls == [
            ("move_abs", 500.0, 300.0),
            ("button", "right", RELEASE),
        ]

    def test_drag(self):
        d = _make_daemon()
        d._dispatch("input.drag", {"x1": 10, "y1": 20, "x2": 100, "y2": 200})
        assert d._backend.calls == [
            ("move_abs", 10.0, 20.0),
            ("button", "left", PRESS),
            ("move_abs", 100.0, 200.0),
            ("button", "left", RELEASE),
        ]

    def test_drag_right_button(self):
        d = _make_daemon()
        d._dispatch("input.drag", {"x1": 0, "y1": 0, "x2": 50, "y2": 50, "button": "right"})
        assert [c[0] for c in d._backend.calls] == ["move_abs", "button", "move_abs", "button"]
        assert d._backend.calls[1] == ("button", "right", PRESS)
        assert d._backend.calls[3] == ("button", "right", RELEASE)

    def test_scroll(self):
        d = _make_daemon()
        d._dispatch("input.scroll", {"x": 100, "y": 200, "dx": 0, "dy": 3})
        assert d._backend.calls == [
            ("move_abs", 100.0, 200.0),
            ("scroll", 0, 3),
        ]

    # -- keyboard (EIS backend) ---------------------------------------------

    def test_presskey_eis(self):
        """Verify presskey calls backend with correct keycode sequence."""
        d = _make_daemon(FakeEisBackend("eis"))
        d._dispatch("input.presskey", {"keys": ["ctrl", "c"]})
        assert d._backend.calls == [
            ("key", 97, PRESS),   # ctrl → keycode 97
            ("key", 46, PRESS),   # c → keycode 46
            ("key", 46, RELEASE),
            ("key", 97, RELEASE),
        ]

    def test_key_down(self):
        d = _make_daemon(FakeEisBackend("eis"))
        d._dispatch("input.key_down", {"key": "a"})
        assert d._backend.calls == [("key", 30, PRESS)]

    def test_key_up(self):
        d = _make_daemon(FakeEisBackend("eis"))
        d._dispatch("input.key_up", {"key": "a"})
        assert d._backend.calls == [("key", 30, RELEASE)]

    def test_type_text(self):
        d = _make_daemon()
        d._dispatch("input.type_text", {"text": "ab"})
        assert d._backend.calls == [("type_text", "ab")]

    # -- error handling ----------------------------------------------------

    def test_unknown_method(self):
        d = _make_daemon()
        with pytest.raises(protocol.ProtocolError) as e:
            d._dispatch("nonexistent.method", {})
        assert e.value.code == protocol.ERR_METHOD_NOT_FOUND

    def test_move_abs_backend_not_started(self):
        d = _make_daemon()
        d._backend._state = "stopped"
        with pytest.raises(BackendError, match="backend not ready"):
            d._dispatch("input.move_abs", {"x": 10, "y": 20})

    def test_presskey_invalid_keys(self):
        d = _make_daemon()
        with pytest.raises(protocol.ProtocolError) as e:
            d._dispatch("input.presskey", {"keys": "not_a_list"})
        assert e.value.code == protocol.ERR_INVALID_PARAMS


# -- Fake EIS backend for presskey tests ----------------------------------

class FakeEisBackend(_FakeBackend):
    name = "eis"
    keymap = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._keymap = FakeKeymap()  # wlroots-style access for _key_action fallback

    def resolve_key(self, keysym):
        # Fake mapping for known keysym values
        fake_map = {
            0xFFE3: 97,   # Control_L → keycode 97
            0xFFE9: 56,   # Alt_L → keycode 56
            99: 46,       # 'c' → keycode 46
            97: 30,       # 'a' → keycode 30
        }
        return fake_map.get(keysym, keysym)


class FakeKeymap:
    def resolve(self, keysym):
        return (30, 0)


class TestParamValidation:
    def test_required_string(self):
        assert _param({"key": "a"}, "key", (str,)) == "a"

    def test_missing_key_returns_none(self):
        assert _param({}, "key", (str,)) is None

    def test_invalid_type(self):
        with pytest.raises(protocol.ProtocolError) as e:
            _param({"key": 123}, "key", (str,))
        assert e.value.code == protocol.ERR_INVALID_PARAMS

    def test_float_or_int(self):
        assert _param({"x": 1.5}, "x", (int, float)) == 1.5
        assert _param({"x": 3}, "x", (int, float)) == 3

    def test_with_default_not_present(self):
        assert _param({}, "opt", (str,), "default") == "default"

    def test_with_default_present(self):
        assert _param({"opt": "hello"}, "opt", (str,), "default") == "hello"