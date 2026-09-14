"""EIS (Emulated Input Server) backend — compositor-specific D-Bus entry points."""

from .backend import EisBackend, EisError  # noqa: F401
from .kylin import connect as kylin_connect  # noqa: F401