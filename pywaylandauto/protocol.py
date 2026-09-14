"""JSON line protocol between client and daemon.

Framing: one UTF-8 JSON object per line, ``\n`` terminated (``\r\n``
tolerated on read), max line length 1 MiB.  Pure stdlib, no deps.

Request:  {"id": <int>, "method": <str>, "params": {<str>: <any>}}
Response: {"id": <int>, "ok": true,  "result": <any>}
          {"id": <int>, "ok": false, "error": {"code": <str>, "message": <str>}}
"""

import json

MAX_LINE = 1_048_576  # 1 MiB

ERR_INVALID_JSON = "invalid_json"
ERR_INVALID_PARAMS = "invalid_params"
ERR_METHOD_NOT_FOUND = "method_not_found"
ERR_INTERNAL = "internal_error"
ERR_BACKEND_ERROR = "backend_error"
ERR_BACKEND_UNAVAILABLE = "backend_unavailable"
ERR_MONITOR_LAYOUT = "monitor_layout_unavailable"
ERR_UNSUPPORTED_CHAR = "unsupported_character"


class ProtocolError(Exception):
    """Framing or schema violation on a line received from the peer."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class RemoteError(Exception):
    """A daemon-reported error, mapped from backend/session failures."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _encode(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def encode_request(req_id: int, method: str, params: dict | None = None) -> bytes:
    return _encode({"id": req_id, "method": method, "params": params or {}})


def encode_response(req_id: int, ok: bool = True, result=None, error=None) -> bytes:
    payload: dict = {"id": req_id, "ok": ok}
    if ok:
        payload["result"] = result if result is not None else {}
    else:
        payload["error"] = error if error is not None else {}
    return _encode(payload)


def decode_request(line: str) -> dict:
    obj = _loads(line)
    if not isinstance(obj, dict):
        raise ProtocolError(ERR_INVALID_JSON, "request must be a JSON object")
    if not isinstance(obj.get("id"), int):
        raise ProtocolError(ERR_INVALID_PARAMS, "'id' must be an int")
    if not isinstance(obj.get("method"), str) or not obj["method"]:
        raise ProtocolError(ERR_INVALID_PARAMS, "'method' must be a non-empty string")
    params = obj.get("params", {})
    if not isinstance(params, dict):
        raise ProtocolError(ERR_INVALID_PARAMS, "'params' must be an object")
    return {"id": obj["id"], "method": obj["method"], "params": params}


def decode_response(line: str) -> dict:
    obj = _loads(line)
    if not isinstance(obj, dict) or not isinstance(obj.get("id"), int):
        raise ProtocolError(ERR_INVALID_JSON, "response must be a JSON object with int 'id'")
    if obj.get("ok") is True:
        if "result" not in obj:
            raise ProtocolError(ERR_INVALID_JSON, "success response missing 'result'")
        return {"id": obj["id"], "ok": True, "result": obj["result"]}
    if obj.get("ok") is False:
        err = obj.get("error")
        if not isinstance(err, dict) or not isinstance(err.get("code"), str):
            raise ProtocolError(ERR_INVALID_JSON, "error response missing 'error.code'")
        return {"id": obj["id"], "ok": False, "code": err["code"], "message": str(err.get("message", ""))}
    raise ProtocolError(ERR_INVALID_JSON, "'ok' must be true or false")


def _loads(line: str) -> object:
    if len(line) > MAX_LINE:
        raise ProtocolError(ERR_INVALID_JSON, f"line exceeds {MAX_LINE} bytes")
    try:
        return json.loads(line)
    except (ValueError, UnicodeDecodeError) as e:
        raise ProtocolError(ERR_INVALID_JSON, f"invalid JSON: {e}") from e