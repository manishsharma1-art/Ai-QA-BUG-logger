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




@pytest.fixture
def mock_sentence_transformer():
    class MockModel:
        def encode(self, texts, **kwargs):
            import numpy as np
            return np.zeros((len(texts), 384), dtype=np.float32)
    return MockModel()

@pytest.fixture
def tiny_corpus_rows():
    return [{"id": 1, "subject": "Test", "description_raw": "Test description", "bug_type": "Functional", "priority": "Medium"}]

@pytest.fixture
def fake_gcs_storage_client():
    class FakeStorageClient:
        def bucket(self, name):
            class FakeBucket:
                def blob(self, bname):
                    class FakeBlob:
                        def exists(self): return False
                        def download_as_bytes(self): return b""
                    return FakeBlob()
            return FakeBucket()
    return FakeStorageClient()

@pytest.fixture
def caplog_rag(caplog):
    return caplog
