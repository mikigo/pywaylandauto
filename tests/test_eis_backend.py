import pytest
from pywaylandauto.backends.eis.backend import EisBackend, EisError

class TestEisBackendInit:
    def test_initial_state(self):
        be = EisBackend()
        assert be.state == "init"
        assert be.name == "eis"
    def test_move_abs_before_start_raises(self):
        be = EisBackend()
        with pytest.raises(Exception):
            be.move_abs(100, 200)