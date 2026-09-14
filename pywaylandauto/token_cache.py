"""Cache for the RemoteDesktop portal restore token.

A restore token is a durable grant credential (persist_mode=2: valid until
revoked), so it lives in $XDG_STATE_HOME — it must survive reboots, unlike
$XDG_RUNTIME_DIR, and it is not regenerable data, unlike ~/.cache.

File mode 0600, directory 0700, written atomically (temp file + rename).
Override the location with PYWAYLANDAUTO_TOKEN_FILE (tests, CI).
"""

import os
import tempfile


class TokenCache:
    def __init__(self, path: str | None = None):
        if path is None:
            path = os.environ.get("PYWAYLANDAUTO_TOKEN_FILE") or self._default_path()
        self.path = path

    @staticmethod
    def _default_path() -> str:
        state_home = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
            "~/.local/state"
        )
        return os.path.join(state_home, "pywaylandauto", "portal.token")

    def load(self) -> str | None:
        try:
            with open(self.path, encoding="utf-8") as f:
                token = f.read().strip()
        except (FileNotFoundError, NotADirectoryError, OSError):
            return None
        return token or None

    def save(self, token: str) -> None:
        token = token.strip()
        if not token:
            raise ValueError("refusing to cache an empty token")
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        os.chmod(directory, 0o700)
        fd, tmp_path = tempfile.mkstemp(prefix=".token-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(token)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.path)
            self._fsync_dir(directory)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def revoke(self) -> None:
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    @staticmethod
    def _fsync_dir(directory: str) -> None:
        try:
            dfd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dfd)
        except OSError:
            pass
        finally:
            os.close(dfd)