"""
Resilient HTTP client for FSBid API integration.

Provides:
- Retry logic with exponential backoff
- Circuit breaker pattern for cascading failure prevention
- Request/response logging for audit trail
- Configurable timeouts
"""
import time
import logging
import threading

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (overridable via Django settings)
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = getattr(settings, 'FSBID_TIMEOUT', 30)
MAX_RETRIES = getattr(settings, 'FSBID_MAX_RETRIES', 3)
BACKOFF_BASE = getattr(settings, 'FSBID_BACKOFF_BASE', 2)
BACKOFF_MAX = getattr(settings, 'FSBID_BACKOFF_MAX', 30)

# Circuit breaker settings
CB_FAILURE_THRESHOLD = getattr(settings, 'FSBID_CB_FAILURE_THRESHOLD', 5)
CB_RECOVERY_TIMEOUT = getattr(settings, 'FSBID_CB_RECOVERY_TIMEOUT', 60)
CB_SUCCESS_THRESHOLD = getattr(settings, 'FSBID_CB_SUCCESS_THRESHOLD', 3)


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open and requests are blocked."""
    pass


class CircuitBreaker(object):
    """
    Thread-safe circuit breaker implementation.

    States:
        CLOSED  - Normal operation; failures are counted.
        OPEN    - Requests are blocked; after recovery_timeout transitions
                  to HALF_OPEN.
        HALF_OPEN - A limited number of probe requests are allowed. If they
                    succeed the circuit closes; if they fail it re-opens.
    """
    STATE_CLOSED = 'closed'
    STATE_OPEN = 'open'
    STATE_HALF_OPEN = 'half_open'

    def __init__(self, failure_threshold=CB_FAILURE_THRESHOLD,
                 recovery_timeout=CB_RECOVERY_TIMEOUT,
                 success_threshold=CB_SUCCESS_THRESHOLD):
        self._lock = threading.Lock()
        self._state = self.STATE_CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold

    @property
    def state(self):
        with self._lock:
            if self._state == self.STATE_OPEN:
                if (time.time() - self._last_failure_time) >= self._recovery_timeout:
                    self._state = self.STATE_HALF_OPEN
                    self._success_count = 0
            return self._state

    def record_success(self):
        with self._lock:
            if self._state == self.STATE_HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._success_threshold:
                    self._state = self.STATE_CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("FSBid circuit breaker closed after successful probes")
            else:
                self._failure_count = 0

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == self.STATE_HALF_OPEN:
                self._state = self.STATE_OPEN
                logger.warning("FSBid circuit breaker re-opened after probe failure")
            elif self._failure_count >= self._failure_threshold:
                self._state = self.STATE_OPEN
                logger.warning(
                    "FSBid circuit breaker opened after %d consecutive failures",
                    self._failure_count
                )

    def allow_request(self):
        current_state = self.state
        if current_state == self.STATE_CLOSED:
            return True
        if current_state == self.STATE_HALF_OPEN:
            return True
        return False


# Module-level circuit breaker instance (shared across all requests)
_circuit_breaker = CircuitBreaker()


def get_circuit_breaker():
    """Return the module-level circuit breaker (allows test injection)."""
    return _circuit_breaker


def reset_circuit_breaker():
    """Reset circuit breaker state (primarily for testing)."""
    global _circuit_breaker
    _circuit_breaker = CircuitBreaker()


# ---------------------------------------------------------------------------
# Resilient HTTP Client
# ---------------------------------------------------------------------------

class FSBidClient(object):
    """
    Typed, resilient HTTP client for the FSBid API.

    Usage::

        client = FSBidClient()
        response = client.get("/bids/", params={"employeeId": "12345"})
        data = response.json()
    """

    def __init__(self, base_url=None, timeout=None, max_retries=None,
                 circuit_breaker=None):
        self.base_url = base_url or settings.FSBID_API_URL
        self.timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.max_retries = max_retries if max_retries is not None else MAX_RETRIES
        self.circuit_breaker = circuit_breaker or get_circuit_breaker()
        self._session = requests.Session()

    def _build_url(self, path):
        if path.startswith('http'):
            return path
        base = self.base_url.rstrip('/')
        path = path if path.startswith('/') else '/' + path
        return base + path

    def _log_request(self, method, url, **kwargs):
        logger.info(
            "FSBid API request: %s %s | params=%s | timeout=%s",
            method.upper(), url,
            kwargs.get('params') or kwargs.get('data'),
            self.timeout
        )

    def _log_response(self, method, url, response, elapsed_ms):
        logger.info(
            "FSBid API response: %s %s | status=%d | elapsed=%dms | size=%d",
            method.upper(), url,
            response.status_code,
            elapsed_ms,
            len(response.content)
        )

    def _should_retry(self, exception, response):
        """Determine if a request should be retried."""
        if exception is not None:
            return isinstance(exception, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ))
        if response is not None:
            return response.status_code in (502, 503, 504, 429)
        return False

    def _execute_with_retry(self, method, url, **kwargs):
        """Execute HTTP request with retry and circuit breaker logic."""
        if not self.circuit_breaker.allow_request():
            logger.error(
                "FSBid circuit breaker OPEN: blocking %s %s",
                method.upper(), url
            )
            raise CircuitBreakerOpen(
                "FSBid API circuit breaker is open. "
                "Service appears unavailable."
            )

        kwargs.setdefault('timeout', self.timeout)
        self._log_request(method, url, **kwargs)

        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                start_time = time.time()
                response = self._session.request(method, url, **kwargs)
                elapsed_ms = int((time.time() - start_time) * 1000)
                self._log_response(method, url, response, elapsed_ms)

                if self._should_retry(None, response):
                    last_exception = requests.exceptions.HTTPError(
                        "Retryable status: {}".format(response.status_code),
                        response=response
                    )
                    if attempt < self.max_retries:
                        sleep_time = min(
                            BACKOFF_BASE ** attempt,
                            BACKOFF_MAX
                        )
                        logger.warning(
                            "FSBid retryable status %d on attempt %d/%d, "
                            "sleeping %.1fs",
                            response.status_code, attempt + 1,
                            self.max_retries + 1, sleep_time
                        )
                        time.sleep(sleep_time)
                        continue
                    # Final attempt with retryable status — record failure
                    self.circuit_breaker.record_failure()
                    return response

                self.circuit_breaker.record_success()
                return response

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    sleep_time = min(
                        BACKOFF_BASE ** attempt,
                        BACKOFF_MAX
                    )
                    logger.warning(
                        "FSBid request failed on attempt %d/%d (%s), "
                        "sleeping %.1fs",
                        attempt + 1, self.max_retries + 1,
                        type(exc).__name__, sleep_time
                    )
                    time.sleep(sleep_time)
                else:
                    self.circuit_breaker.record_failure()
                    raise

        # Should not reach here, but safety net
        self.circuit_breaker.record_failure()
        raise last_exception

    def get(self, path, **kwargs):
        """Send a GET request to the FSBid API."""
        url = self._build_url(path)
        return self._execute_with_retry('GET', url, **kwargs)

    def post(self, path, **kwargs):
        """Send a POST request to the FSBid API."""
        url = self._build_url(path)
        return self._execute_with_retry('POST', url, **kwargs)

    def delete(self, path, **kwargs):
        """Send a DELETE request to the FSBid API."""
        url = self._build_url(path)
        return self._execute_with_retry('DELETE', url, **kwargs)


# Module-level default client instance
_default_client = None


def get_client():
    """
    Return a module-level FSBidClient singleton.

    Lazily initialized to allow Django settings to be fully loaded.
    """
    global _default_client
    if _default_client is None:
        _default_client = FSBidClient()
    return _default_client


def reset_client():
    """Reset the default client (primarily for testing)."""
    global _default_client
    _default_client = None
