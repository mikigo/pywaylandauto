import pytest
from pywaylandauto.backends.wlroots.backend import WlrootsBackend

class TestWlrootsBackendInit:
    def test_initial_state(self):
        be = WlrootsBackend()
        assert be.state == "init"
        assert be.name == "wlroots"