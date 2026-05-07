"""Unit tests for scripts/dev_workflow helpers."""

import socket

import pytest

from scripts.dev_workflow import assert_port_available


class TestAssertPortAvailable:
    """Regression coverage for the bind-based stale-server guard."""

    def test_raises_runtime_error_when_port_is_in_use(self):
        """Binding a socket should block assert_port_available from succeeding."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

            with pytest.raises(RuntimeError) as exc_info:
                assert_port_available("127.0.0.1", port)

        msg = str(exc_info.value)
        assert str(port) in msg
        assert "--port" in msg

    def test_succeeds_when_port_is_free(self):
        """assert_port_available should return quietly for an available port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        # Port is now free (socket closed)
        assert_port_available("127.0.0.1", port)
