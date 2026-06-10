"""
Tests for the resilient FSBid HTTP client.

Proves:
- Retry logic with exponential backoff
- Circuit breaker state transitions
- Request/response audit logging
- Timeout configuration
- Functional parity with the previous raw requests.get/post/delete usage
"""
import time
import pytest
from unittest.mock import Mock, patch, call
import requests

from talentmap_api.fsbid.fsbid_client import (
    FSBidClient,
    CircuitBreaker,
    CircuitBreakerOpen,
    reset_circuit_breaker,
    reset_client,
)
from talentmap_api.fsbid.fsbid_models import (
    FSBidBidResponse,
    FSBidProjectedVacanciesResponse,
    FSBidBidSeason,
    FSBidBidOnPositionRequest,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Reset module-level state between tests."""
    reset_circuit_breaker()
    reset_client()
    yield
    reset_circuit_breaker()
    reset_client()


# ---------------------------------------------------------------------------
# Pydantic Model Validation Tests
# ---------------------------------------------------------------------------

class TestPydanticModels:

    def test_bid_response_validates_complete_data(self):
        data = {
            "submittedDate": "2019/01/01",
            "statusCode": "A",
            "handshakeCode": "N",
            "cycle": {"description": "Cycle 1", "status": "A"},
            "employee": {"perdet_seq_num": "12345"},
            "cyclePosition": {
                "cp_id": 1,
                "status": "A",
                "pos_seq_num": "99",
                "totalBidders": 5,
                "atGradeBidders": 2,
                "inConeBidders": 3,
                "inBothBidders": 1,
            },
        }
        model = FSBidBidResponse(**data)
        assert model.statusCode == "A"
        assert model.employee.perdet_seq_num == "12345"
        assert model.cyclePosition.cp_id == 1

    def test_bid_response_uses_defaults(self):
        data = {
            "submittedDate": "2019/01/01",
            "statusCode": "W",
            "handshakeCode": "N",
            "cycle": {},
            "employee": {"perdet_seq_num": "1"},
            "cyclePosition": {"cp_id": 2},
        }
        model = FSBidBidResponse(**data)
        assert model.cycle.description == ""
        assert model.cyclePosition.totalBidders == 0

    def test_projected_vacancy_response_validates(self):
        data = {
            "positions": [
                {
                    "pos_id": "42",
                    "grade": "05",
                    "skill": "ECON",
                    "bureau": "EUR",
                    "organization": "Embassy Paris",
                    "tour_of_duty": "2Y",
                    "language1": "FR",
                    "reading_proficiency_1": "3",
                    "spoken_proficiency_1": "3",
                    "language_representation_1": "French",
                    "differential_rate": "10",
                    "danger_pay": "N",
                    "incumbent": "Smith, John",
                    "ted": "06/2025",
                    "position_number": "P12345",
                    "createDate": "2024-01-15",
                    "title": "Economic Officer",
                    "bsn_descr_text": "Summer 2025",
                }
            ],
            "pagination": {"count": 1, "limit": 25},
        }
        model = FSBidProjectedVacanciesResponse(**data)
        assert len(model.positions) == 1
        assert model.positions[0].pos_id == "42"
        assert model.pagination.count == 1

    def test_bid_season_validates(self):
        data = {
            "bsn_id": "10",
            "bsn_descr_text": "Fall 2024",
            "bsn_start_date": "2024/09/01",
            "bsn_end_date": "2024/12/31",
            "bsn_panel_cutoff_date": "2025/01/15",
        }
        model = FSBidBidSeason(**data)
        assert model.bsn_id == "10"
        assert model.bsn_descr_text == "Fall 2024"

    def test_bid_on_position_request_validates(self):
        req = FSBidBidOnPositionRequest(
            perdet_seq_num="123", cp_id="456", userId="789"
        )
        assert req.perdet_seq_num == "123"


# ---------------------------------------------------------------------------
# Circuit Breaker Tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:

    def test_starts_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=5)
        assert cb.state == CircuitBreaker.STATE_CLOSED
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.STATE_CLOSED
        cb.record_failure()
        assert cb.state == CircuitBreaker.STATE_OPEN
        assert cb.allow_request() is False

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)
        cb.record_failure()
        cb.record_failure()
        # With recovery_timeout=0, state check immediately transitions to HALF_OPEN
        assert cb.state == CircuitBreaker.STATE_HALF_OPEN
        assert cb.allow_request() is True

    def test_closes_after_success_threshold_in_half_open(self):
        cb = CircuitBreaker(
            failure_threshold=2, recovery_timeout=0, success_threshold=2
        )
        cb.record_failure()
        cb.record_failure()
        # Now half-open (recovery_timeout=0)
        assert cb.state == CircuitBreaker.STATE_HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitBreaker.STATE_HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitBreaker.STATE_CLOSED

    def test_reopens_on_failure_in_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        # Manually transition to half_open for testing
        with cb._lock:
            cb._state = CircuitBreaker.STATE_HALF_OPEN
        assert cb.state == CircuitBreaker.STATE_HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitBreaker.STATE_OPEN

    def test_success_resets_failure_count_when_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        # After success, failure count resets
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.STATE_CLOSED


# ---------------------------------------------------------------------------
# Retry Logic Tests
# ---------------------------------------------------------------------------

class TestRetryLogic:

    @patch('talentmap_api.fsbid.fsbid_client.time.sleep')
    def test_retries_on_connection_error(self, mock_sleep):
        client = FSBidClient(
            base_url="http://fsbid-test",
            timeout=5,
            max_retries=2,
            circuit_breaker=CircuitBreaker(),
        )
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"ok": true}'

        with patch.object(client._session, 'request') as mock_req:
            mock_req.side_effect = [
                requests.exceptions.ConnectionError("Connection refused"),
                mock_response,
            ]
            result = client.get("/test")
            assert result == mock_response
            assert mock_req.call_count == 2
            mock_sleep.assert_called_once()

    @patch('talentmap_api.fsbid.fsbid_client.time.sleep')
    def test_retries_on_timeout(self, mock_sleep):
        client = FSBidClient(
            base_url="http://fsbid-test",
            timeout=5,
            max_retries=2,
            circuit_breaker=CircuitBreaker(),
        )
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{}'

        with patch.object(client._session, 'request') as mock_req:
            mock_req.side_effect = [
                requests.exceptions.Timeout("Timed out"),
                mock_response,
            ]
            result = client.get("/test")
            assert result == mock_response
            assert mock_req.call_count == 2

    @patch('talentmap_api.fsbid.fsbid_client.time.sleep')
    def test_retries_on_503(self, mock_sleep):
        client = FSBidClient(
            base_url="http://fsbid-test",
            timeout=5,
            max_retries=2,
            circuit_breaker=CircuitBreaker(),
        )
        bad_response = Mock()
        bad_response.status_code = 503
        bad_response.content = b'Service Unavailable'
        good_response = Mock()
        good_response.status_code = 200
        good_response.content = b'{}'

        with patch.object(client._session, 'request') as mock_req:
            mock_req.side_effect = [bad_response, good_response]
            result = client.get("/test")
            assert result.status_code == 200
            assert mock_req.call_count == 2

    @patch('talentmap_api.fsbid.fsbid_client.time.sleep')
    def test_raises_after_max_retries_exhausted(self, mock_sleep):
        client = FSBidClient(
            base_url="http://fsbid-test",
            timeout=5,
            max_retries=2,
            circuit_breaker=CircuitBreaker(),
        )
        with patch.object(client._session, 'request') as mock_req:
            mock_req.side_effect = requests.exceptions.ConnectionError("down")
            with pytest.raises(requests.exceptions.ConnectionError):
                client.get("/test")
            assert mock_req.call_count == 3  # initial + 2 retries

    @patch('talentmap_api.fsbid.fsbid_client.time.sleep')
    def test_exponential_backoff_timing(self, mock_sleep):
        client = FSBidClient(
            base_url="http://fsbid-test",
            timeout=5,
            max_retries=3,
            circuit_breaker=CircuitBreaker(),
        )
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{}'

        with patch.object(client._session, 'request') as mock_req:
            mock_req.side_effect = [
                requests.exceptions.ConnectionError("err"),
                requests.exceptions.ConnectionError("err"),
                requests.exceptions.ConnectionError("err"),
                mock_response,
            ]
            result = client.get("/test")
            # Backoff: 2^0=1, 2^1=2, 2^2=4
            assert mock_sleep.call_args_list == [
                call(1), call(2), call(4)
            ]

    def test_no_retry_on_4xx(self):
        client = FSBidClient(
            base_url="http://fsbid-test",
            timeout=5,
            max_retries=3,
            circuit_breaker=CircuitBreaker(),
        )
        bad_response = Mock()
        bad_response.status_code = 404
        bad_response.content = b'Not Found'

        with patch.object(client._session, 'request') as mock_req:
            mock_req.return_value = bad_response
            result = client.get("/test")
            assert result.status_code == 404
            assert mock_req.call_count == 1


# ---------------------------------------------------------------------------
# Circuit Breaker Integration Tests
# ---------------------------------------------------------------------------

class TestCircuitBreakerIntegration:

    @patch('talentmap_api.fsbid.fsbid_client.time.sleep')
    def test_circuit_opens_after_repeated_failures(self, mock_sleep):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        client = FSBidClient(
            base_url="http://fsbid-test",
            timeout=5,
            max_retries=0,
            circuit_breaker=cb,
        )

        with patch.object(client._session, 'request') as mock_req:
            mock_req.side_effect = requests.exceptions.ConnectionError("down")
            # First failure
            with pytest.raises(requests.exceptions.ConnectionError):
                client.get("/test1")
            # Second failure opens the circuit
            with pytest.raises(requests.exceptions.ConnectionError):
                client.get("/test2")
            # Third request blocked by circuit breaker
            with pytest.raises(CircuitBreakerOpen):
                client.get("/test3")

    def test_circuit_breaker_open_raises_immediately(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        client = FSBidClient(
            base_url="http://fsbid-test",
            timeout=5,
            max_retries=0,
            circuit_breaker=cb,
        )
        with pytest.raises(CircuitBreakerOpen):
            client.get("/blocked")


# ---------------------------------------------------------------------------
# Timeout Tests
# ---------------------------------------------------------------------------

class TestTimeout:

    def test_timeout_passed_to_session(self):
        client = FSBidClient(
            base_url="http://fsbid-test",
            timeout=7,
            max_retries=0,
            circuit_breaker=CircuitBreaker(),
        )
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{}'

        with patch.object(client._session, 'request') as mock_req:
            mock_req.return_value = mock_response
            client.get("/test")
            _, kwargs = mock_req.call_args
            assert kwargs['timeout'] == 7

    def test_default_timeout_from_settings(self):
        with patch('talentmap_api.fsbid.fsbid_client.DEFAULT_TIMEOUT', 42):
            client = FSBidClient(
                base_url="http://fsbid-test",
                max_retries=0,
                circuit_breaker=CircuitBreaker(),
            )
            assert client.timeout == 42


# ---------------------------------------------------------------------------
# Audit Logging Tests
# ---------------------------------------------------------------------------

class TestAuditLogging:

    def test_request_and_response_logged(self):
        client = FSBidClient(
            base_url="http://fsbid-test",
            timeout=5,
            max_retries=0,
            circuit_breaker=CircuitBreaker(),
        )
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": "value"}'

        with patch.object(client._session, 'request', return_value=mock_response):
            with patch('talentmap_api.fsbid.fsbid_client.logger') as mock_logger:
                client.get("/audit-test", params={"key": "val"})
                # Should have at least 2 info calls: request + response
                info_calls = mock_logger.info.call_args_list
                assert len(info_calls) >= 2
                # First call should be the request log
                assert "request" in info_calls[0][0][0].lower()
                # Second call should be the response log
                assert "response" in info_calls[1][0][0].lower()


# ---------------------------------------------------------------------------
# URL Building Tests
# ---------------------------------------------------------------------------

class TestURLBuilding:

    def test_relative_path(self):
        client = FSBidClient(base_url="http://fsbid:3333")
        assert client._build_url("/bids/") == "http://fsbid:3333/bids/"

    def test_absolute_url_passthrough(self):
        client = FSBidClient(base_url="http://fsbid:3333")
        url = "http://other-host/endpoint"
        assert client._build_url(url) == url

    def test_trailing_slash_handling(self):
        client = FSBidClient(base_url="http://fsbid:3333/")
        assert client._build_url("/bids") == "http://fsbid:3333/bids"


# ---------------------------------------------------------------------------
# Functional Parity Tests
# ---------------------------------------------------------------------------

class TestFunctionalParity:
    """
    Tests proving that the new client-based services produce identical
    outputs to the previous raw requests.get/post implementation.
    """

    def test_user_bids_returns_same_structure(self):
        """Verify user_bids output matches the expected TalentMap bid format."""
        from talentmap_api.fsbid.services import user_bids

        bid_data = {
            "submittedDate": "2019/01/01",
            "statusCode": "A",
            "handshakeCode": "N",
            "cycle": {"description": "Fall 2019", "status": "A"},
            "employee": {"perdet_seq_num": "99"},
            "cyclePosition": {
                "cp_id": 7,
                "status": "A",
                "pos_seq_num": "42",
                "totalBidders": 3,
                "atGradeBidders": 1,
                "inConeBidders": 2,
                "inBothBidders": 0,
            },
        }

        mock_client = Mock()
        mock_response = Mock()
        mock_response.json.return_value = [bid_data]
        mock_client.get.return_value = mock_response

        with patch('talentmap_api.fsbid.services.get_client', return_value=mock_client):
            result = list(user_bids("99"))

        assert len(result) == 1
        r = result[0]
        assert r['emp_id'] == "99"
        assert r['bidcycle'] == "Fall 2019"
        assert r['status'] == "submitted"
        assert r['can_delete'] is True
        assert r['bid_statistics'][0]['total_bids'] == 3
        assert r['position']['id'] == "42"

    def test_user_bids_filters_by_position_id(self):
        """Verify position_id filtering matches old behavior."""
        from talentmap_api.fsbid.services import user_bids

        bids_data = [
            {
                "submittedDate": "2019/01/01",
                "statusCode": "A",
                "handshakeCode": "N",
                "cycle": {"description": "", "status": "A"},
                "employee": {"perdet_seq_num": "1"},
                "cyclePosition": {
                    "cp_id": 10,
                    "status": "A",
                    "pos_seq_num": "1",
                    "totalBidders": 0,
                    "atGradeBidders": 0,
                    "inConeBidders": 0,
                    "inBothBidders": 0,
                },
            },
            {
                "submittedDate": "2019/02/01",
                "statusCode": "W",
                "handshakeCode": "N",
                "cycle": {"description": "", "status": "A"},
                "employee": {"perdet_seq_num": "1"},
                "cyclePosition": {
                    "cp_id": 20,
                    "status": "A",
                    "pos_seq_num": "2",
                    "totalBidders": 0,
                    "atGradeBidders": 0,
                    "inConeBidders": 0,
                    "inBothBidders": 0,
                },
            },
        ]

        mock_client = Mock()
        mock_response = Mock()
        mock_response.json.return_value = bids_data
        mock_client.get.return_value = mock_response

        with patch('talentmap_api.fsbid.services.get_client', return_value=mock_client):
            result = user_bids("1", position_id="10")

        assert len(result) == 1
        assert result[0]['status'] == "submitted"

    def test_bid_on_position_calls_post(self):
        """Verify bid_on_position sends correct POST data."""
        from talentmap_api.fsbid.services import bid_on_position

        mock_client = Mock()
        mock_client.post.return_value = Mock(status_code=201)

        with patch('talentmap_api.fsbid.services.get_client', return_value=mock_client):
            result = bid_on_position("user1", "emp1", "cp1")

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]['data'] == {
            "perdet_seq_num": "emp1",
            "cp_id": "cp1",
            "userId": "user1",
        }

    def test_remove_bid_calls_delete(self):
        """Verify remove_bid sends correct DELETE request."""
        from talentmap_api.fsbid.services import remove_bid

        mock_client = Mock()
        mock_client.delete.return_value = Mock(status_code=200)

        with patch('talentmap_api.fsbid.services.get_client', return_value=mock_client):
            result = remove_bid("emp1", "cp1")

        mock_client.delete.assert_called_once()
        url_arg = mock_client.delete.call_args[0][0]
        assert "cp_id=cp1" in url_arg
        assert "perdet_seq_num=emp1" in url_arg

    def test_get_projected_vacancies_returns_same_structure(self):
        """Verify projected vacancies output matches old format."""
        from talentmap_api.fsbid.services import get_projected_vacancies

        pv_data = {
            "positions": [
                {
                    "pos_id": "1",
                    "grade": "05",
                    "skill": "ECON",
                    "bureau": "EUR",
                    "organization": "Paris",
                    "tour_of_duty": "2Y",
                    "language1": "FR",
                    "reading_proficiency_1": "3",
                    "spoken_proficiency_1": "3",
                    "language_representation_1": "French",
                    "differential_rate": "15",
                    "danger_pay": "N",
                    "incumbent": "Doe, J",
                    "ted": "06/2025",
                    "position_number": "P999",
                    "createDate": "2024-01-01",
                    "title": "Econ Officer",
                    "bsn_descr_text": "Summer 2025",
                }
            ],
            "pagination": {"count": 1, "limit": 25},
        }

        mock_client = Mock()
        mock_response = Mock()
        mock_response.json.return_value = pv_data
        mock_client.get.return_value = mock_response

        from django.http import QueryDict
        query = QueryDict(mutable=True)

        with patch('talentmap_api.fsbid.services.get_client', return_value=mock_client):
            result = get_projected_vacancies(query, "http://testserver")

        assert result['count'] == 1
        results = list(result['results'])
        assert results[0]['id'] == "1"
        assert results[0]['grade'] == "05"
        assert results[0]['bureau'] == "EUR"
        assert results[0]['languages'][0]['language'] == "FR"

    def test_get_bid_seasons_returns_same_structure(self):
        """Verify bid seasons output matches old format."""
        from talentmap_api.fsbid.services import get_bid_seasons

        seasons_data = [
            {
                "bsn_id": "5",
                "bsn_descr_text": "Winter 2024",
                "bsn_start_date": "2024/01/01",
                "bsn_end_date": "2024/03/31",
                "bsn_panel_cutoff_date": "2024/04/15",
            }
        ]

        mock_client = Mock()
        mock_response = Mock()
        mock_response.json.return_value = seasons_data
        mock_client.get.return_value = mock_response

        with patch('talentmap_api.fsbid.services.get_client', return_value=mock_client):
            result = list(get_bid_seasons(None))

        assert len(result) == 1
        assert result[0]['id'] == "5"
        assert result[0]['description'] == "Winter 2024"

    def test_get_bid_status_mapping(self):
        """Verify status mapping unchanged."""
        from talentmap_api.fsbid.services import get_bid_status

        assert get_bid_status("W", "N") == "draft"
        assert get_bid_status("A", "N") == "submitted"
        assert get_bid_status("A", "A") == "handshake_accepted"
        assert get_bid_status("P", "N") == "in_panel"
        assert get_bid_status("C", "N") == "closed"

    def test_can_delete_bid_logic(self):
        """Verify can_delete logic unchanged."""
        from talentmap_api.fsbid.services import can_delete_bid

        assert can_delete_bid("draft", {"status": "A"}) is True
        assert can_delete_bid("draft", {"status": "C"}) is True
        assert can_delete_bid("submitted", {"status": "A"}) is True
        assert can_delete_bid("submitted", {"status": "C"}) is False
        assert can_delete_bid("in_panel", {"status": "A"}) is False
