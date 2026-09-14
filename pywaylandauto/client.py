import os
import socket
import subprocess
import sys
import time

from . import protocol
from .daemon import default_socket_path

DEFAULT_CONNECT_TIMEOUT = 2.0
DEFAULT_REQUEST_TIMEOUT = 30.0


class Client:
    def __init__(self, socket_path: str | None = None,
                 auto_spawn: bool = True,
                 connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
                 request_timeout: float = DEFAULT_REQUEST_TIMEOUT):
        self.socket_path = socket_path
        self.auto_spawn = auto_spawn
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._req_id = 0

    def connect(self) -> None:
        if self._sock is not None:
            return
        path = self.socket_path or default_socket_path()
        try:
            self._sock = self._try_connect(path)
        except (ConnectionRefusedError, FileNotFoundError) as e:
            if not self.auto_spawn:
                raise ConnectionError(f"daemon not reachable at {path}: {e}") from e
            self._spawn_daemon()
            deadline = time.monotonic() + self.connect_timeout
            while True:
                try:
                    self._sock = self._try_connect(path)
                    break
                except (ConnectionRefusedError, FileNotFoundError):
                    if time.monotonic() >= deadline:
                        raise ConnectionError(
                            f"daemon did not come up at {path} within "
                            f"{self.connect_timeout}s"
                        ) from e
                    time.sleep(0.1)

    @staticmethod
    def _try_connect(path: str) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(path)
        return sock

    @staticmethod
    def _spawn_daemon() -> None:
        subprocess.Popen(
            [sys.executable, "-m", "pywaylandauto", "daemon", "start"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._buf = bytearray()

    def request(self, method: str, params: dict | None = None) -> dict:
        self.connect()
        self._req_id += 1
        self._sock.sendall(protocol.encode_request(self._req_id, method, params))
        deadline = time.monotonic() + self.request_timeout
        while True:
            line = self._read_line(deadline)
            resp = protocol.decode_response(line)
            if resp["id"] != self._req_id:
                continue
            if resp["ok"]:
                return resp["result"]
            raise protocol.RemoteError(resp["code"], resp["message"])

    def _read_line(self, deadline: float) -> str:
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"daemon did not respond within {self.request_timeout}s"
                )
            self._sock.settimeout(remaining)
            try:
                data = self._sock.recv(65536)
            except socket.timeout:
                raise TimeoutError(
                    f"daemon did not respond within {self.request_timeout}s"
                ) from None
            if not data:
                raise ConnectionError("daemon closed the connection")
            self._buf.extend(data)
        line, _, rest = self._buf.partition(b"\n")
        del self._buf[: len(line) + 1]
        return line.decode("utf-8")

    def ping(self) -> dict:
        return self.request("ping")

    def status(self) -> dict:
        return self.request("status")

    def move_abs(self, x: float, y: float) -> dict:
        return self.request("input.move_abs", {"x": x, "y": y})

    def move_rel(self, dx: float, dy: float) -> dict:
        return self.request("input.move_rel", {"dx": dx, "dy": dy})

    def click(self, x: float, y: float, button: str = "left") -> dict:
        return self.request("input.click", {"x": x, "y": y, "button": button})

    def double_click(self, x: float, y: float, button: str = "left") -> dict:
        return self.request("input.double_click", {"x": x, "y": y, "button": button})

    def mouse_down(self, x: float, y: float, button: str = "left") -> dict:
        return self.request("input.mouse_down", {"x": x, "y": y, "button": button})

    def mouse_up(self, x: float, y: float, button: str = "left") -> dict:
        return self.request("input.mouse_up", {"x": x, "y": y, "button": button})

    def drag(self, x1: float, y1: float, x2: float, y2: float,
             button: str = "left") -> dict:
        return self.request("input.drag",
                            {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "button": button})

    def scroll(self, x: float, y: float, dx: int = 0, dy: int = -1) -> dict:
        return self.request("input.scroll", {"x": x, "y": y, "dx": dx, "dy": dy})

    def key(self, *keys: str) -> dict:
        return self.request("input.presskey", {"keys": list(keys)})

    def key_down(self, key: str) -> dict:
        return self.request("input.key_down", {"key": key})

    def key_up(self, key: str) -> dict:
        return self.request("input.key_up", {"key": key})

    def type_text(self, text: str) -> dict:
        return self.request("input.type_text", {"text": text})

    def mouse_position(self) -> dict:
        return self.request("input.mouse_position")

    def daemon_stop(self) -> dict:
        return self.request("daemon.stop")