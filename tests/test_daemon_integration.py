"""Integration tests: daemon dispatch with fake backend injected."""

import threading
import time

import pytest

from pywaylandauto import protocol
from pywaylandauto.client import Client
from pywaylandauto.daemon import Daemon


class _FakeStartedBackend:
    """Backend that always reports started."""

    def __init__(self):
        self.name = "fake"
        self._state = "started"
        self.calls = []
        self.keymap = _FakeKeymap()
        self._keymap = self.keymap  # wlroots-style access

    @property
    def state(self):
        return self._state

    def move_abs(self, x, y):
        self.calls.append(("move_abs", x, y))

    def move_rel(self, dx, dy):
        self.calls.append(("move_rel", dx, dy))

    def button(self, b, p):
        self.calls.append(("button", b, p))

    def scroll(self, dx, dy):
        self.calls.append(("scroll", dx, dy))

    def key(self, kc, press):
        self.calls.append(("key", kc, press))

    def key_sequence(self, *events):
        for keycode, press in events:
            self.calls.append(("key", keycode, press))

    def key_combo_frame(self, *keycodes):
        self.calls.append(("key_combo_frame", *keycodes))

    def type_text(self, t):
        self.calls.append(("type_text", t))

    def resolve_key(self, ks):
        return 30

    def stop(self):
        pass

    def status(self):
        return {"state": "started", "transport": "fake"}

    def start(self):
        self._state = "started"


class _FakeEisBackend(_FakeStartedBackend):
    def __init__(self):
        super().__init__()
        self.name = "eis"


class _FakeKeymap:
    def resolve(self, keysym):
        return (30, 0)  # keycode=30 (a), level=0


def _run_daemon(sock, pid, backend):
    d = Daemon(socket_path=sock, pid_path=pid)
    d._backend = backend
    d.run()


class TestDaemonDispatchIntegration:
    def test_ping_through_socket(self, tmp_path):
        sock = str(tmp_path / "sock")
        pid = str(tmp_path / "pid")
        t = threading.Thread(target=_run_daemon, args=(sock, pid, _FakeStartedBackend()), daemon=True)
        t.start()
        time.sleep(0.5)

        c = Client(socket_path=sock, auto_spawn=False)
        result = c.ping()
        assert "version" in result

        c.daemon_stop()
        t.join(timeout=2)

    def test_move_abs_through_socket(self, tmp_path):
        sock = str(tmp_path / "sock")
        pid = str(tmp_path / "pid")
        t = threading.Thread(target=_run_daemon, args=(sock, pid, _FakeStartedBackend()), daemon=True)
        t.start()
        time.sleep(0.5)

        c = Client(socket_path=sock, auto_spawn=False)
        result = c.move_abs(100, 200)
        assert result == {}

        c.daemon_stop()
        t.join(timeout=2)

    def test_all_client_convenience_methods(self, tmp_path):
        sock = str(tmp_path / "sock")
        pid = str(tmp_path / "pid")
        t = threading.Thread(target=_run_daemon, args=(sock, pid, _FakeStartedBackend()), daemon=True)
        t.start()
        time.sleep(0.5)

        c = Client(socket_path=sock, auto_spawn=False)

        assert c.move_abs(1, 2) == {}
        assert c.move_rel(3, 4) == {}
        assert c.click(5, 6) == {}
        assert c.click(5, 6, "right") == {}
        assert c.double_click(7, 8) == {}
        assert c.mouse_down(9, 10) == {}
        assert c.mouse_up(11, 12) == {}
        assert c.drag(0, 0, 10, 10) == {}
        assert c.scroll(100, 200) == {}
        assert c.scroll(100, 200, dx=1, dy=2) == {}
        assert c.type_text("hello") == {}

        c.daemon_stop()
        t.join(timeout=2)

    def test_key_actions_eis_backend(self, tmp_path):
        sock = str(tmp_path / "sock")
        pid = str(tmp_path / "pid")
        t = threading.Thread(target=_run_daemon, args=(sock, pid, _FakeEisBackend()), daemon=True)
        t.start()
        time.sleep(0.5)

        c = Client(socket_path=sock, auto_spawn=False)

        assert c.key("ctrl", "c") == {}
        assert c.key("enter") == {}
        assert c.key_down("a") == {}
        assert c.key_up("a") == {}

        c.daemon_stop()
        t.join(timeout=2)

    def test_invalid_method(self, tmp_path):
        sock = str(tmp_path / "sock")
        pid = str(tmp_path / "pid")
        t = threading.Thread(target=_run_daemon, args=(sock, pid, _FakeStartedBackend()), daemon=True)
        t.start()
        time.sleep(0.5)

        c = Client(socket_path=sock, auto_spawn=False)
        with pytest.raises(protocol.RemoteError) as e:
            c.request("invalid.method", {})
        assert e.value.code == protocol.ERR_METHOD_NOT_FOUND

        c.daemon_stop()
        t.join(timeout=2)

    def test_already_running_detection(self, tmp_path):
        sock = str(tmp_path / "sock")
        pid = str(tmp_path / "pid")
        t = threading.Thread(target=_run_daemon, args=(sock, pid, _FakeStartedBackend()), daemon=True)
        t.start()
        time.sleep(0.5)

        from pywaylandauto.daemon import AlreadyRunningError
        d2 = Daemon(socket_path=sock, pid_path=pid)
        with pytest.raises(AlreadyRunningError):
            d2.run()

        c = Client(socket_path=sock, auto_spawn=False)
        c.daemon_stop()
        t.join(timeout=2)