"""Typed, resilient HTTP client for FSBid API integration.

Provides:
- Automatic retry with exponential backoff (urllib3 Retry + HTTPAdapter)
- Circuit breaker for cascading failure prevention
- Structured request/response audit logging
- Configurable timeouts via Django settings

Django settings consumed (all optional, with sane defaults):
    FSBID_TIMEOUT               – (connect, read) tuple in seconds.  Default (5, 30).
    FSBID_RETRY_TOTAL           – Max retry attempts.  Default 3.
    FSBID_RETRY_BACKOFF_FACTOR  – Multiplier for exponential backoff.  Default 0.5.
    FSBID_CIRCUIT_FAILURE_THRESHOLD – Consecutive failures before opening.  Default 5.
    FSBID_CIRCUIT_RECOVERY_TIMEOUT  – Seconds before half-open probe.  Default 30.
"""
import logging
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open and requests are rejected."""
    pass


class CircuitBreaker(object):
    """Thread-safe circuit breaker.

    States
    ------
    CLOSED    – normal; requests flow through.
    OPEN      – failure threshold exceeded; requests fail fast.
    HALF_OPEN – recovery probe; one request allowed through.
    """
    CLOSED = 'closed'
    OPEN = 'open'
    HALF_OPEN = 'half_open'

    def __init__(self, failure_threshold=5, recovery_timeout=30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._lock = threading.Lock()

    @property
    def state(self):
        with self._lock:
            if self._state == self.OPEN and self._last_failure_time is not None:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = self.HALF_OPEN
            return self._state

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = self.OPEN
                logger.warning(
                    "FSBid circuit breaker OPENED after %d consecutive failures",
                    self._failure_count,
                )

    def allow_request(self):
        return self.state in (self.CLOSED, self.HALF_OPEN)


# ---------------------------------------------------------------------------
# FSBid HTTP client
# ---------------------------------------------------------------------------

class FSBidClient(object):
    """Resilient HTTP client for the FSBid API."""

    def __init__(self):
        self._timeout = getattr(settings, 'FSBID_TIMEOUT', (5, 30))
        self._session = self._build_session()
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=getattr(
                settings, 'FSBID_CIRCUIT_FAILURE_THRESHOLD', 5),
            recovery_timeout=getattr(
                settings, 'FSBID_CIRCUIT_RECOVERY_TIMEOUT', 30),
        )

    def _build_session(self):
        session = requests.Session()
        retry_strategy = Retry(
            total=getattr(settings, 'FSBID_RETRY_TOTAL', 3),
            backoff_factor=getattr(settings, 'FSBID_RETRY_BACKOFF_FACTOR', 0.5),
            status_forcelist=[500, 502, 503, 504],
            method_whitelist=['GET', 'DELETE'],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    # -- public HTTP verbs ---------------------------------------------------

    def get(self, url, **kwargs):
        """Send a GET request."""
        return self._request('get', url, **kwargs)

    def post(self, url, **kwargs):
        """Send a POST request."""
        return self._request('post', url, **kwargs)

    def delete(self, url, **kwargs):
        """Send a DELETE request."""
        return self._request('delete', url, **kwargs)

    # -- internals -----------------------------------------------------------

    def _request(self, method, url, **kwargs):
        if not self._circuit_breaker.allow_request():
            logger.error(
                "FSBid circuit breaker OPEN - rejected: %s %s",
                method.upper(), url,
            )
            raise CircuitBreakerOpenError(
                "FSBid circuit breaker is open; request to {} rejected".format(url)
            )

        kwargs.setdefault('timeout', self._timeout)
        start = time.time()
        logger.info("FSBid request: %s %s", method.upper(), url)

        try:
            response = getattr(self._session, method)(url, **kwargs)
            elapsed = time.time() - start
            logger.info(
                "FSBid response: %s %s -> %d (%.3fs)",
                method.upper(), url, response.status_code, elapsed,
            )
            self._circuit_breaker.record_success()
            return response
        except requests.exceptions.RequestException as exc:
            elapsed = time.time() - start
            logger.error(
                "FSBid request failed: %s %s -> %s (%.3fs)",
                method.upper(), url, exc, elapsed,
            )
            self._circuit_breaker.record_failure()
            raise


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client_instance = None
_client_lock = threading.Lock()


def get_client():
    """Return the module-level FSBidClient singleton (thread-safe lazy init)."""
    global _client_instance
    if _client_instance is None:
        with _client_lock:
            if _client_instance is None:
                _client_instance = FSBidClient()
    return _client_instance


def reset_client():
    """Reset the singleton — intended for test teardown."""
    global _client_instance
    with _client_lock:
        _client_instance = None
