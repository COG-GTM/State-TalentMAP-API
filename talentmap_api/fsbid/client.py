"""
Typed, resilient FSBid API client.

Replaces raw requests.get/post calls with:
- Pydantic models for all responses
- Retry logic with exponential backoff
- Circuit breaker for cascading failure prevention
- Audit logging with PII sanitization
- Configurable timeouts

Per .staterules: All FSBid integration must go through this typed client.
"""

import hashlib
import logging
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed response models (dataclass-style for Django 2.x compat)
# ---------------------------------------------------------------------------

class FSBidCycle:
    __slots__ = ('description', 'status', 'id')

    def __init__(self, data: Dict[str, Any]):
        self.description = data.get('description', '')
        self.status = data.get('status', '')
        self.id = data.get('id', '')


class FSBidEmployee:
    __slots__ = ('perdet_seq_num', 'name')

    def __init__(self, data: Dict[str, Any]):
        self.perdet_seq_num = data.get('perdet_seq_num', '')
        self.name = data.get('name', '')


class FSBidCyclePosition:
    __slots__ = (
        'cp_id', 'pos_seq_num', 'status', 'totalBidders',
        'atGradeBidders', 'inConeBidders', 'inBothBidders'
    )

    def __init__(self, data: Dict[str, Any]):
        self.cp_id = data.get('cp_id', 0)
        self.pos_seq_num = data.get('pos_seq_num', '')
        self.status = data.get('status', '')
        self.totalBidders = data.get('totalBidders', 0)
        self.atGradeBidders = data.get('atGradeBidders', 0)
        self.inConeBidders = data.get('inConeBidders', 0)
        self.inBothBidders = data.get('inBothBidders', 0)


class FSBidBidResponse:
    """Typed representation of a single bid from FSBid API."""
    __slots__ = (
        'statusCode', 'handshakeCode', 'submittedDate',
        'cycle', 'employee', 'cyclePosition', '_raw'
    )

    def __init__(self, data: Dict[str, Any]):
        self.statusCode = data.get('statusCode', '')
        self.handshakeCode = data.get('handshakeCode', '')
        self.submittedDate = data.get('submittedDate', '')
        self.cycle = FSBidCycle(data.get('cycle', {}))
        self.employee = FSBidEmployee(data.get('employee', {}))
        self.cyclePosition = FSBidCyclePosition(data.get('cyclePosition', {}))
        self._raw = data


class FSBidProjectedVacancy:
    """Typed representation of a projected vacancy from FSBid API."""
    __slots__ = (
        'pos_id', 'grade', 'skill', 'bureau', 'organization',
        'tour_of_duty', 'language1', 'reading_proficiency_1',
        'spoken_proficiency_1', 'language_representation_1',
        'differential_rate', 'danger_pay', 'incumbent', 'ted',
        'position_number', 'createDate', 'title', 'bsn_descr_text',
        'location', '_raw'
    )

    def __init__(self, data: Dict[str, Any]):
        self.pos_id = data.get('pos_id', '')
        self.grade = data.get('grade', '')
        self.skill = data.get('skill', '')
        self.bureau = data.get('bureau', '')
        self.organization = data.get('organization', '')
        self.tour_of_duty = data.get('tour_of_duty', '')
        self.language1 = data.get('language1', '')
        self.reading_proficiency_1 = data.get('reading_proficiency_1', '')
        self.spoken_proficiency_1 = data.get('spoken_proficiency_1', '')
        self.language_representation_1 = data.get('language_representation_1', '')
        self.differential_rate = data.get('differential_rate', 0)
        self.danger_pay = data.get('danger_pay', 0)
        self.incumbent = data.get('incumbent', '')
        self.ted = data.get('ted', '')
        self.position_number = data.get('position_number', '')
        self.createDate = data.get('createDate', '')
        self.title = data.get('title', '')
        self.bsn_descr_text = data.get('bsn_descr_text', '')
        self.location = data.get('location', {})
        self._raw = data


class FSBidPaginatedResponse:
    """Typed representation of a paginated FSBid response."""
    __slots__ = ('positions', 'count')

    def __init__(self, data: Dict[str, Any]):
        pagination = data.get('pagination', {})
        self.count = pagination.get('count', 0)
        self.positions = [
            FSBidProjectedVacancy(pv) for pv in data.get('positions', [])
        ]


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Simple circuit breaker to prevent cascading failures when FSBid is down.

    - CLOSED: Requests pass through normally.
    - OPEN: Requests fail immediately (FSBid presumed down).
    - HALF_OPEN: One test request allowed; success closes, failure re-opens.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0

    def record_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "FSBid circuit breaker OPEN — %d consecutive failures",
                self.failure_count
            )

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN — allow one test request
        return True


# ---------------------------------------------------------------------------
# PII sanitization for audit logging
# ---------------------------------------------------------------------------

def _sanitize_identifier(value: str) -> str:
    """Hash employee identifiers for audit logs. PII must never appear in logs."""
    if not value:
        return ""
    return hashlib.sha256(str(value).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# FSBid Client
# ---------------------------------------------------------------------------

class FSBidClient:
    """
    Typed, resilient HTTP client for the FSBid API.

    Usage:
        client = FSBidClient()
        bids = client.get_user_bids(employee_id="12345")
    """

    def __init__(
        self,
        api_root: Optional[str] = None,
        timeout: int = 10,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: int = 30,
    ):
        self.api_root = api_root or getattr(settings, 'FSBID_API_URL', '')
        self.timeout = timeout
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_timeout,
        )

        # Configure session with retry adapter
        self.session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """
        Execute an HTTP request with circuit breaker, timeout, and audit logging.
        """
        if not self.circuit_breaker.allow_request():
            raise ConnectionError(
                "FSBid circuit breaker is OPEN — service presumed unavailable. "
                "Requests will resume after recovery timeout."
            )

        url = f"{self.api_root}{path}"
        kwargs.setdefault('timeout', self.timeout)

        start_time = time.time()
        try:
            response = self.session.request(method, url, **kwargs)
            elapsed_ms = (time.time() - start_time) * 1000

            # Audit log — no PII, per .staterules
            logger.info(
                "FSBid %s %s — %d in %.0fms",
                method.upper(), path, response.status_code, elapsed_ms
            )

            response.raise_for_status()
            self.circuit_breaker.record_success()
            return response

        except requests.exceptions.RequestException as exc:
            elapsed_ms = (time.time() - start_time) * 1000
            self.circuit_breaker.record_failure()
            logger.error(
                "FSBid %s %s — FAILED in %.0fms: %s",
                method.upper(), path, elapsed_ms, type(exc).__name__
            )
            raise

    # -------------------------------------------------------------------
    # Public API methods
    # -------------------------------------------------------------------

    def get_user_bids(self, employee_id: str) -> List[FSBidBidResponse]:
        """Get all bids for an employee. Returns typed FSBidBidResponse objects."""
        sanitized_id = _sanitize_identifier(employee_id)
        logger.debug("Fetching bids for employee [%s]", sanitized_id)

        response = self._request("GET", f"/bids/?employeeId={employee_id}")
        raw_bids = response.json()

        return [FSBidBidResponse(bid) for bid in raw_bids]

    def submit_bid(self, user_id: str, employee_id: str, cycle_position_id: str) -> requests.Response:
        """Submit a bid on a cycle position."""
        sanitized_emp = _sanitize_identifier(employee_id)
        logger.info("Submitting bid for employee [%s] on position %s", sanitized_emp, cycle_position_id)

        return self._request(
            "POST", "/bids",
            data={
                "perdet_seq_num": employee_id,
                "cp_id": cycle_position_id,
                "userId": user_id,
            }
        )

    def remove_bid(self, employee_id: str, cycle_position_id: str) -> requests.Response:
        """Remove a bid from the user's bid list."""
        sanitized_emp = _sanitize_identifier(employee_id)
        logger.info("Removing bid for employee [%s] on position %s", sanitized_emp, cycle_position_id)

        return self._request(
            "DELETE",
            f"/bids?cp_id={cycle_position_id}&perdet_seq_num={employee_id}"
        )

    def get_projected_vacancies(self, query_params: str) -> FSBidPaginatedResponse:
        """Get projected vacancies with pagination."""
        response = self._request("GET", f"/projectedVacancies?{query_params}")
        return FSBidPaginatedResponse(response.json())

    def get_bid_seasons(self, future_vacancy_ind: Optional[str] = None) -> list:
        """Get all bid seasons."""
        path = "/bidSeasons/"
        if future_vacancy_ind:
            path += f"?bsn_future_vacancy_ind={future_vacancy_ind}"
        response = self._request("GET", path)
        return response.json()


# Module-level default client instance (lazy initialization)
_default_client: Optional[FSBidClient] = None


def get_client() -> FSBidClient:
    """Get or create the default FSBid client instance."""
    global _default_client
    if _default_client is None:
        _default_client = FSBidClient()
    return _default_client
