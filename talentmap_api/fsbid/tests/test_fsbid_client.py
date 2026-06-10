import pytest
import logging
import logging.handlers
from unittest.mock import Mock, patch, MagicMock

import requests

from talentmap_api.fsbid.client import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    FSBidClient,
    get_client,
    reset_client,
)


# ---------------------------------------------------------------------------
# CircuitBreaker unit tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:

    def test_starts_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.allow_request() is True

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.allow_request() is True

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        for _ in range(3):
            cb.record_failure()
        # Access internal _state directly to avoid auto-transition
        assert cb._state == CircuitBreaker.OPEN
        assert cb.allow_request() is False

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED

    @patch('talentmap_api.fsbid.client.time.time')
    def test_transitions_to_half_open_after_recovery_timeout(self, mock_time):
        mock_time.return_value = 1000.0
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
        cb.record_failure()
        assert cb._state == CircuitBreaker.OPEN

        # Before timeout: still OPEN
        mock_time.return_value = 1025.0
        assert cb.state == CircuitBreaker.OPEN
        assert cb.allow_request() is False

        # After timeout: HALF_OPEN
        mock_time.return_value = 1031.0
        assert cb.state == CircuitBreaker.HALF_OPEN
        assert cb.allow_request() is True

    @patch('talentmap_api.fsbid.client.time.time')
    def test_half_open_success_closes(self, mock_time):
        mock_time.return_value = 1000.0
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
        cb.record_failure()

        mock_time.return_value = 1031.0
        assert cb.state == CircuitBreaker.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED

    @patch('talentmap_api.fsbid.client.time.time')
    def test_half_open_failure_reopens(self, mock_time):
        mock_time.return_value = 1000.0
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)
        cb.record_failure()

        mock_time.return_value = 1031.0
        assert cb.state == CircuitBreaker.HALF_OPEN
        cb.record_failure()
        assert cb._state == CircuitBreaker.OPEN


# ---------------------------------------------------------------------------
# FSBidClient unit tests
# ---------------------------------------------------------------------------

class TestFSBidClient:

    @patch('talentmap_api.fsbid.client.requests.Session')
    def test_get_delegates_to_session(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = Mock(status_code=200)
        mock_session.get.return_value = mock_response

        client = FSBidClient()
        result = client.get('http://example.com/api')

        mock_session.get.assert_called_once()
        assert result is mock_response

    @patch('talentmap_api.fsbid.client.requests.Session')
    def test_post_delegates_to_session(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = Mock(status_code=201)
        mock_session.post.return_value = mock_response

        client = FSBidClient()
        result = client.post('http://example.com/api', data={'key': 'val'})

        mock_session.post.assert_called_once()
        assert result is mock_response

    @patch('talentmap_api.fsbid.client.requests.Session')
    def test_delete_delegates_to_session(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = Mock(status_code=200)
        mock_session.delete.return_value = mock_response

        client = FSBidClient()
        result = client.delete('http://example.com/api')

        mock_session.delete.assert_called_once()
        assert result is mock_response

    @patch('talentmap_api.fsbid.client.requests.Session')
    def test_timeout_is_passed(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = Mock(status_code=200)

        client = FSBidClient()
        client.get('http://example.com/api')

        call_kwargs = mock_session.get.call_args[1]
        assert 'timeout' in call_kwargs

    @patch('talentmap_api.fsbid.client.requests.Session')
    def test_circuit_breaker_rejects_when_open(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.ConnectionError("down")

        client = FSBidClient()
        client._circuit_breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        for _ in range(2):
            with pytest.raises(requests.exceptions.ConnectionError):
                client.get('http://example.com/api')

        assert client._circuit_breaker._state == CircuitBreaker.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            client.get('http://example.com/api')

    @patch('talentmap_api.fsbid.client.requests.Session')
    def test_success_resets_circuit_breaker(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        client = FSBidClient()
        client._circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        mock_session.get.side_effect = requests.exceptions.ConnectionError("down")
        with pytest.raises(requests.exceptions.ConnectionError):
            client.get('http://example.com/api')

        mock_session.get.side_effect = None
        mock_session.get.return_value = Mock(status_code=200)
        client.get('http://example.com/api')

        assert client._circuit_breaker.state == CircuitBreaker.CLOSED

    @patch('talentmap_api.fsbid.client.requests.Session')
    def test_audit_logging_on_success(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.return_value = Mock(status_code=200)

        test_logger = logging.getLogger('talentmap_api.fsbid.client')
        handler = logging.handlers.MemoryHandler(capacity=100)
        handler.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)

        try:
            client = FSBidClient()
            client.get('http://example.com/api')

            handler.flush()
            messages = [r.getMessage() for r in handler.buffer]
            assert any('FSBid request: GET' in m for m in messages)
            assert any('FSBid response: GET' in m and '200' in m for m in messages)
        finally:
            test_logger.removeHandler(handler)

    @patch('talentmap_api.fsbid.client.requests.Session')
    def test_audit_logging_on_failure(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = requests.exceptions.Timeout("timed out")

        test_logger = logging.getLogger('talentmap_api.fsbid.client')
        handler = logging.handlers.MemoryHandler(capacity=100)
        handler.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.DEBUG)

        try:
            client = FSBidClient()
            with pytest.raises(requests.exceptions.Timeout):
                client.get('http://example.com/api')

            handler.flush()
            messages = [r.getMessage() for r in handler.buffer]
            assert any('FSBid request failed: GET' in m for m in messages)
        finally:
            test_logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------

class TestGetClient:

    def setup_method(self):
        reset_client()

    def teardown_method(self):
        reset_client()

    @patch('talentmap_api.fsbid.client.FSBidClient')
    def test_returns_same_instance(self, mock_cls):
        mock_cls.return_value = Mock()
        c1 = get_client()
        c2 = get_client()
        assert c1 is c2
        mock_cls.assert_called_once()

    def test_reset_clears_singleton(self):
        c1 = get_client()
        reset_client()
        c2 = get_client()
        assert c1 is not c2
