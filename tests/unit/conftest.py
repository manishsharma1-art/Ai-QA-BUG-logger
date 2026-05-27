"""
Shared pytest fixtures for unit tests.

Most tests use pytest's built-in `caplog` fixture for log assertions.
The `_log_capture` deque from main.py is also available for tests that
need to inspect the in-memory log buffer the bot uses for /logs.
"""
import pytest


@pytest.fixture
def log_capture():
    """Yields the in-memory log deque from main.py, cleared before each test."""
    from main import _log_capture
    _log_capture.clear()
    yield _log_capture
    _log_capture.clear()
