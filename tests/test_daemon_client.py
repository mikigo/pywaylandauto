import threading, time
from pywaylandauto.daemon import Daemon
from pywaylandauto.client import Client
from pywaylandauto import protocol

def _start_daemon(daemon):
    t = threading.Thread(target=daemon.run, daemon=True)
    t.start()
    time.sleep(0.5)
    return t

def test_daemon_ping(tmp_path):
    sock, pid = str(tmp_path/"sock"), str(tmp_path/"pid")
    daemon = Daemon(socket_path=sock, pid_path=pid)
    t = _start_daemon(daemon)
    client = Client(socket_path=sock, auto_spawn=False)
    result = client.ping()
    assert result["version"] == "0.1.0"
    client.daemon_stop()
    t.join(timeout=2)

def test_daemon_status(tmp_path):
    sock, pid = str(tmp_path/"sock"), str(tmp_path/"pid")
    daemon = Daemon(socket_path=sock, pid_path=pid)
    t = _start_daemon(daemon)
    client = Client(socket_path=sock, auto_spawn=False)
    result = client.status()
    assert "backend" in result
    client.daemon_stop()
    t.join(timeout=2)

def test_unknown_method(tmp_path):
    sock, pid = str(tmp_path/"sock"), str(tmp_path/"pid")
    daemon = Daemon(socket_path=sock, pid_path=pid)
    t = _start_daemon(daemon)
    client = Client(socket_path=sock, auto_spawn=False)
    try:
        client.request("nonexistent.method")
        assert False, "should have raised"
    except protocol.RemoteError as e:
        assert e.code == "method_not_found"
    client.daemon_stop()
    t.join(timeout=2)