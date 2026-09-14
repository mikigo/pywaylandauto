"""Unit tests for Client — verify convenience methods produce correct protocol requests."""

from pywaylandauto.client import Client


def _capture(client, block):
    """Help: call block(), intercepting client.request to capture (method, params)."""
    orig = client.request
    captured = []

    def fake(method, params=None):
        captured.append((method, params))
        return {}

    client.request = fake
    try:
        block()
    finally:
        client.request = orig
    return captured[0] if captured else None


class TestClientParams:
    def test_all_convenience_methods(self):
        c = Client.__new__(Client)
        c._sock = None  # prevent connect()

        checks = [
            (lambda: c.move_abs(100, 200), ("input.move_abs", {"x": 100, "y": 200})),
            (lambda: c.move_rel(10, -5), ("input.move_rel", {"dx": 10, "dy": -5})),
            (lambda: c.click(1, 2), ("input.click", {"x": 1, "y": 2, "button": "left"})),
            (lambda: c.click(1, 2, "right"), ("input.click", {"x": 1, "y": 2, "button": "right"})),
            (lambda: c.double_click(3, 4), ("input.double_click", {"x": 3, "y": 4, "button": "left"})),
            (lambda: c.double_click(3, 4, "right"), ("input.double_click", {"x": 3, "y": 4, "button": "right"})),
            (lambda: c.mouse_down(5, 6), ("input.mouse_down", {"x": 5, "y": 6, "button": "left"})),
            (lambda: c.mouse_down(5, 6, "middle"), ("input.mouse_down", {"x": 5, "y": 6, "button": "middle"})),
            (lambda: c.mouse_up(7, 8), ("input.mouse_up", {"x": 7, "y": 8, "button": "left"})),
            (lambda: c.mouse_up(7, 8, "right"), ("input.mouse_up", {"x": 7, "y": 8, "button": "right"})),
            (lambda: c.drag(0, 0, 10, 10), ("input.drag", {"x1": 0, "y1": 0, "x2": 10, "y2": 10, "button": "left"})),
            (lambda: c.drag(0, 0, 10, 10, "right"), ("input.drag", {"x1": 0, "y1": 0, "x2": 10, "y2": 10, "button": "right"})),
            (lambda: c.scroll(1, 2), ("input.scroll", {"x": 1, "y": 2, "dx": 0, "dy": -1})),
            (lambda: c.scroll(1, 2, dx=3, dy=4), ("input.scroll", {"x": 1, "y": 2, "dx": 3, "dy": 4})),
            (lambda: c.key("ctrl", "c"), ("input.presskey", {"keys": ["ctrl", "c"]})),
            (lambda: c.key("enter"), ("input.presskey", {"keys": ["enter"]})),
            (lambda: c.key_down("shift"), ("input.key_down", {"key": "shift"})),
            (lambda: c.key_up("alt"), ("input.key_up", {"key": "alt"})),
            (lambda: c.type_text("hello"), ("input.type_text", {"text": "hello"})),
            (lambda: c.mouse_position(), ("input.mouse_position", None)),
            (lambda: c.ping(), ("ping", None)),
            (lambda: c.daemon_stop(), ("daemon.stop", None)),
        ]

        for block, expected in checks:
            actual = _capture(c, block)
            assert actual == expected, f"expected {expected}, got {actual}"