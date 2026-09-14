import json, pytest
from pywaylandauto import protocol

class TestEncodeDecode:
    def test_request_roundtrip(self):
        raw = protocol.encode_request(1, "input.move_abs", {"x": 100, "y": 200})
        obj = json.loads(raw)
        assert obj["method"] == "input.move_abs"

    def test_decode_valid(self):
        req = protocol.decode_request(json.dumps({"id": 1, "method": "ping", "params": {}}))
        assert req["method"] == "ping"

    def test_decode_missing_id(self):
        with pytest.raises(protocol.ProtocolError):
            protocol.decode_request(json.dumps({"method": "ping"}))

    def test_response_ok(self):
        raw = protocol.encode_response(1, result={"version": "0.1.0"})
        resp = protocol.decode_response(raw.decode())
        assert resp["ok"] is True
        assert resp["result"]["version"] == "0.1.0"

    def test_response_error(self):
        raw = protocol.encode_response(1, ok=False, error={"code": "err", "message": "msg"})
        resp = protocol.decode_response(raw.decode())
        assert resp["code"] == "err"

    def test_line_too_long(self):
        line = "x" * (protocol.MAX_LINE + 1)
        with pytest.raises(protocol.ProtocolError):
            protocol.decode_request(line)

class TestRemoteError:
    def test_str(self):
        e = protocol.RemoteError("test", "msg")
        assert str(e) == "test: msg"

class TestErrorCodes:
    def test_backend_error_exists(self):
        assert protocol.ERR_BACKEND_ERROR == "backend_error"
    def test_backend_unavailable_exists(self):
        assert protocol.ERR_BACKEND_UNAVAILABLE == "backend_unavailable"
    def test_session_error_codes(self):
        assert protocol.ERR_SESSION_NOT_STARTED == "session_not_started"
        assert protocol.ERR_PERMISSION_PENDING == "permission_pending"
        assert protocol.ERR_PERMISSION_DENIED == "permission_denied"
        assert protocol.ERR_PORTAL_UNAVAILABLE == "portal_unavailable"
        assert protocol.ERR_PORTAL_FAILED == "portal_failed"
        assert protocol.ERR_CANCELLED == "cancelled"