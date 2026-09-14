import pytest

@pytest.fixture
def tmp_socket_path(tmp_path):
    return str(tmp_path / "test.sock")

@pytest.fixture
def tmp_pid_path(tmp_path):
    return str(tmp_path / "test.pid")