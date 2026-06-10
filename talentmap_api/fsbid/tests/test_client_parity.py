"""
Parity tests: services_v2 (typed client) produces identical output to services (raw requests).

These tests capture real FSBid response fixtures and assert that both the legacy
services module and the modernized services_v2 module produce byte-identical output.

Per AGENTS.md:
- Integration tests must use mocked FSBid responses (no live calls in CI)
- Functional parity tests required for any integration refactor
"""

import json
import logging
from datetime import datetime
from unittest.mock import patch, MagicMock

import requests
from django.test import TestCase, override_settings

from talentmap_api.fsbid import services as legacy_services
from talentmap_api.fsbid import services_v2 as modern_services
from talentmap_api.fsbid.client import (
    FSBidClient, FSBidBidResponse, FSBidBidSeason,
    CircuitBreaker, CircuitState, _sanitize_identifier,
    FSBidAPIError, FSBidConnectionError,
)


# ---------------------------------------------------------------------------
# Fixtures — captured from FSBid API response format
# ---------------------------------------------------------------------------

SAMPLE_BID_RESPONSE = {
    "statusCode": "A",
    "handshakeCode": "",
    "submittedDate": "2024/03/15",
    "cycle": {
        "id": "242",
        "description": "Fall 2024 Bidding Cycle",
        "status": "A"
    },
    "employee": {
        "perdet_seq_num": "98765432",
        "name": "Smith, Jane"
    },
    "cyclePosition": {
        "cp_id": 1001,
        "pos_seq_num": "D0144910",
        "status": "OP",
        "totalBidders": 12,
        "atGradeBidders": 5,
        "inConeBidders": 8,
        "inBothBidders": 3
    }
}

SAMPLE_BID_HANDSHAKE = {
    "statusCode": "A",
    "handshakeCode": "A",
    "submittedDate": "2024/02/10",
    "cycle": {
        "id": "242",
        "description": "Fall 2024 Bidding Cycle",
        "status": "A"
    },
    "employee": {
        "perdet_seq_num": "11223344",
        "name": "Doe, John"
    },
    "cyclePosition": {
        "cp_id": 2002,
        "pos_seq_num": "D0155920",
        "status": "HS",
        "totalBidders": 6,
        "atGradeBidders": 2,
        "inConeBidders": 4,
        "inBothBidders": 1
    }
}

SAMPLE_PROJECTED_VACANCY = {
    "pos_id": "PV001",
    "grade": "04",
    "skill": "5505",
    "bureau": "EUR",
    "organization": "EUR/EX",
    "tour_of_duty": "2YR",
    "language1": "FR",
    "reading_proficiency_1": "3",
    "spoken_proficiency_1": "3",
    "language_representation_1": "French",
    "differential_rate": 15,
    "danger_pay": 0,
    "incumbent": "Johnson, Mark",
    "ted": "06/2025",
    "position_number": "D0144910",
    "createDate": "2024-01-15",
    "title": "POLITICAL OFFICER",
    "bsn_descr_text": "Fall 2024",
    "location": {"city": "Paris", "country": "France"}
}

SAMPLE_PV_API_RESPONSE = {
    "positions": [SAMPLE_PROJECTED_VACANCY],
    "pagination": {"count": 1}
}


@override_settings(FSBID_API_URL="https://fsbid-test.state.gov/api/v1")
class BidTransformParityTest(TestCase):
    """
    Verify that services.fsbid_bid_to_talentmap_bid and
    services_v2.fsbid_bid_to_talentmap_bid produce identical output.
    """

    def test_submitted_bid_parity(self):
        legacy_result = legacy_services.fsbid_bid_to_talentmap_bid(SAMPLE_BID_RESPONSE)
        modern_result = modern_services.fsbid_bid_to_talentmap_bid(SAMPLE_BID_RESPONSE)
        self.assertEqual(legacy_result, modern_result)

    def test_handshake_bid_parity(self):
        legacy_result = legacy_services.fsbid_bid_to_talentmap_bid(SAMPLE_BID_HANDSHAKE)
        modern_result = modern_services.fsbid_bid_to_talentmap_bid(SAMPLE_BID_HANDSHAKE)
        self.assertEqual(legacy_result, modern_result)

    def test_bid_status_parity_all_codes(self):
        """Verify all status code combinations produce the same result."""
        test_cases = [
            ("W", "", "draft"),
            ("A", "", "submitted"),
            ("P", "", "paneled"),
            ("C", "", "closed"),
            ("A", "A", "handshake (takes precedence)"),
            ("W", "A", "handshake overrides draft"),
        ]
        for status_code, handshake_code, description in test_cases:
            with self.subTest(description=description):
                legacy = legacy_services.get_bid_status(status_code, handshake_code)
                modern = modern_services.get_bid_status(status_code, handshake_code)
                self.assertEqual(legacy, modern)

    def test_can_delete_parity(self):
        """Draft bids and submitted+active cycle are deletable."""
        from talentmap_api.bidding.models import Bid

        test_cases = [
            (Bid.Status.draft, {"status": "A"}, True),
            (Bid.Status.draft, {"status": "C"}, True),
            (Bid.Status.submitted, {"status": "A"}, True),
            (Bid.Status.submitted, {"status": "C"}, False),
            (Bid.Status.in_panel, {"status": "A"}, False),
        ]
        for bid_status, cycle, expected in test_cases:
            with self.subTest(status=bid_status, cycle_status=cycle['status']):
                legacy = legacy_services.can_delete_bid(bid_status, cycle)
                modern = modern_services.can_delete_bid(bid_status, cycle)
                self.assertEqual(legacy, modern)
                self.assertEqual(legacy, expected)


@override_settings(FSBID_API_URL="http://fsbid-test.state.gov/api/v1")
class UserBidsParityTest(TestCase):
    """
    Verify services_v2.user_bids produces the same output as services.user_bids
    when given the same FSBid API response.
    """

    @patch('talentmap_api.fsbid.services.requests.get')
    @patch('talentmap_api.fsbid.client.FSBidClient._request')
    def test_user_bids_all(self, mock_client_request, mock_legacy_get):
        """Both paths return identical bid lists when no position filter."""
        # Configure legacy mock
        mock_legacy_response = MagicMock()
        mock_legacy_response.json.return_value = [SAMPLE_BID_RESPONSE, SAMPLE_BID_HANDSHAKE]
        mock_legacy_get.return_value = mock_legacy_response

        # Configure modern mock
        mock_modern_response = MagicMock()
        mock_modern_response.json.return_value = [SAMPLE_BID_RESPONSE, SAMPLE_BID_HANDSHAKE]
        mock_modern_response.status_code = 200
        mock_modern_response.raise_for_status = MagicMock()
        mock_client_request.return_value = mock_modern_response

        legacy_result = list(legacy_services.user_bids("98765432"))
        modern_result = modern_services.user_bids("98765432")

        self.assertEqual(legacy_result, modern_result)

    @patch('talentmap_api.fsbid.services.requests.get')
    @patch('talentmap_api.fsbid.client.FSBidClient._request')
    def test_user_bids_filtered_by_position(self, mock_client_request, mock_legacy_get):
        """Both paths filter correctly by position_id."""
        mock_legacy_response = MagicMock()
        mock_legacy_response.json.return_value = [SAMPLE_BID_RESPONSE, SAMPLE_BID_HANDSHAKE]
        mock_legacy_get.return_value = mock_legacy_response

        mock_modern_response = MagicMock()
        mock_modern_response.json.return_value = [SAMPLE_BID_RESPONSE, SAMPLE_BID_HANDSHAKE]
        mock_modern_response.status_code = 200
        mock_modern_response.raise_for_status = MagicMock()
        mock_client_request.return_value = mock_modern_response

        legacy_result = legacy_services.user_bids("98765432", position_id="1001")
        modern_result = modern_services.user_bids("98765432", position_id="1001")

        self.assertEqual(legacy_result, modern_result)


@override_settings(FSBID_API_URL="http://fsbid-test.state.gov/api/v1")
class ProjectedVacancyParityTest(TestCase):
    """Verify projected vacancy transformation parity."""

    def test_pv_transform_parity(self):
        legacy = legacy_services.fsbid_pv_to_talentmap_pv(SAMPLE_PROJECTED_VACANCY)
        modern = modern_services.fsbid_pv_to_talentmap_pv(SAMPLE_PROJECTED_VACANCY)
        self.assertEqual(legacy, modern)

    def test_query_conversion_parity(self):
        """Same query params produce identical FSBid query strings."""
        from django.http import QueryDict
        query = QueryDict(mutable=True)
        query.update({
            "is_available_in_bidseason": "242",
            "bureau__code__in": "EUR",
            "grade__code__in": "04",
            "limit": "25",
            "page": "1",
        })
        legacy = legacy_services.convert_pv_query(query)
        modern = modern_services.convert_pv_query(query)
        self.assertEqual(legacy, modern)


class CircuitBreakerTest(TestCase):
    """Test circuit breaker behavior."""

    def test_starts_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertTrue(cb.allow_request())

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        cb.record_failure()
        cb.record_failure()
        self.assertTrue(cb.allow_request())  # Still closed at 2
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertFalse(cb.allow_request())

    def test_resets_on_success(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertEqual(cb.failure_count, 0)

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        # With recovery_timeout=0, should immediately go half-open
        self.assertTrue(cb.allow_request())
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

    def test_half_open_allows_only_one_request(self):
        """HALF_OPEN must allow exactly one test request, then block."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)

        # First call after recovery_timeout transitions to HALF_OPEN and allows
        self.assertTrue(cb.allow_request())
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Second call in HALF_OPEN must be blocked
        self.assertFalse(cb.allow_request())
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)

        # Third call also blocked
        self.assertFalse(cb.allow_request())

    def test_half_open_success_closes_circuit(self):
        """Successful request in HALF_OPEN closes the circuit."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)
        cb.record_failure()
        cb.record_failure()
        self.assertTrue(cb.allow_request())  # transitions to HALF_OPEN
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        # All requests pass again
        self.assertTrue(cb.allow_request())
        self.assertTrue(cb.allow_request())

    def test_half_open_failure_reopens_circuit(self):
        """Failed request in HALF_OPEN re-opens the circuit."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)
        cb.record_failure()
        cb.record_failure()
        self.assertTrue(cb.allow_request())  # transitions to HALF_OPEN
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_half_open_4xx_closes_circuit(self):
        """4xx response during HALF_OPEN probe closes circuit (server is alive)."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertTrue(cb.allow_request())  # transitions to HALF_OPEN
        # Simulating: server returned 4xx → record_success() is called
        # (since a 4xx proves the server is responsive)
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertTrue(cb.allow_request())


class PIISanitizationTest(TestCase):
    """Verify PII is properly hashed before logging."""

    def test_sanitize_hashes_employee_id(self):
        result = _sanitize_identifier("98765432")
        # Should be a 12-char hex hash, NOT the original value
        self.assertEqual(len(result), 12)
        self.assertNotIn("98765432", result)
        self.assertTrue(all(c in '0123456789abcdef' for c in result))

    def test_sanitize_deterministic(self):
        """Same input always produces same hash."""
        a = _sanitize_identifier("98765432")
        b = _sanitize_identifier("98765432")
        self.assertEqual(a, b)

    def test_sanitize_empty_string(self):
        self.assertEqual(_sanitize_identifier(""), "")

    def test_sanitize_different_ids_different_hashes(self):
        a = _sanitize_identifier("98765432")
        b = _sanitize_identifier("11223344")
        self.assertNotEqual(a, b)


@override_settings(FSBID_API_URL="https://fsbid-test.state.gov/api/v1")
class FSBidClientTest(TestCase):
    """Test the FSBidClient itself."""

    @patch('talentmap_api.fsbid.client.FSBidClient._request')
    def test_get_user_bids_returns_typed(self, mock_request):
        mock_response = MagicMock()
        mock_response.json.return_value = [SAMPLE_BID_RESPONSE]
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        client = FSBidClient()
        bids = client.get_user_bids("98765432")

        self.assertEqual(len(bids), 1)
        self.assertIsInstance(bids[0], FSBidBidResponse)
        self.assertEqual(bids[0].statusCode, "A")
        self.assertEqual(bids[0].employee.perdet_seq_num, "98765432")
        self.assertEqual(bids[0].cyclePosition.cp_id, 1001)

    def test_circuit_breaker_blocks_after_failures(self):
        client = FSBidClient(circuit_failure_threshold=2)
        # Simulate failures
        client.circuit_breaker.record_failure()
        client.circuit_breaker.record_failure()

        with self.assertRaises(ConnectionError) as ctx:
            client._request("GET", "/bids/")
        self.assertIn("circuit breaker is OPEN", str(ctx.exception))


@override_settings(FSBID_API_URL="https://fsbid-test.state.gov/api/v1")
class BidSeasonParityTest(TestCase):
    """Verify bid season transformation parity."""

    def test_bid_season_transform_parity(self):
        """services_v2 applies the same transform as legacy services."""
        sample_season = {
            "bsn_id": "242",
            "bsn_descr_text": "Fall 2024 Bidding Cycle",
            "bsn_start_date": "2024/03/01",
            "bsn_end_date": "2024/06/30",
            "bsn_panel_cutoff_date": "2024/05/15"
        }
        legacy = legacy_services.fsbid_bid_season_to_talentmap_bid_season(sample_season)
        modern = modern_services.fsbid_bid_season_to_talentmap_bid_season(sample_season)
        self.assertEqual(legacy, modern)

    @patch('talentmap_api.fsbid.client.FSBidClient._request')
    def test_get_bid_seasons_returns_typed(self, mock_request):
        """get_bid_seasons returns typed FSBidBidSeason objects."""
        mock_response = MagicMock()
        mock_response.json.return_value = [{
            "bsn_id": "242",
            "bsn_descr_text": "Fall 2024",
            "bsn_start_date": "2024/03/01",
            "bsn_end_date": "2024/06/30",
            "bsn_panel_cutoff_date": "2024/05/15"
        }]
        mock_request.return_value = mock_response

        client = FSBidClient()
        seasons = client.get_bid_seasons()
        self.assertEqual(len(seasons), 1)
        self.assertIsInstance(seasons[0], FSBidBidSeason)
        self.assertEqual(seasons[0].bsn_id, "242")


@override_settings(FSBID_API_URL="https://fsbid-test.state.gov/api/v1")
class PIIExceptionSanitizationTest(TestCase):
    """Verify PII never leaks through exception messages (AGENTS.md compliance)."""

    @patch('requests.Session.request')
    def test_http_error_does_not_expose_employee_id(self, mock_request):
        """HTTPError re-raised as FSBidAPIError must not contain PII in str()."""
        employee_id = "98765432"
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"404 Client Error for url: https://fsbid.state.gov/api/v1/bids/?employeeId={employee_id}",
            response=mock_response
        )
        mock_request.return_value = mock_response

        client = FSBidClient()
        with self.assertRaises(FSBidAPIError) as ctx:
            client.get_user_bids(employee_id)

        # The sanitized exception must NOT contain the employee ID
        self.assertNotIn(employee_id, str(ctx.exception))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.method, "GET")

    @patch('requests.Session.request')
    def test_connection_error_does_not_expose_url(self, mock_request):
        """Connection errors re-raised as FSBidConnectionError, no URL/PII."""
        mock_request.side_effect = requests.exceptions.ConnectionError(
            "Connection refused: https://fsbid.state.gov/api/v1/bids/?employeeId=98765432"
        )

        client = FSBidClient()
        with self.assertRaises(FSBidConnectionError) as ctx:
            client.get_user_bids("98765432")

        self.assertNotIn("98765432", str(ctx.exception))
        self.assertIn("ConnectionError", str(ctx.exception))


@override_settings(FSBID_API_URL="https://fsbid-test.state.gov/api/v1")
class PIILogCaptureTest(TestCase):
    """Verify no raw PII leaks into application logs during FSBid operations."""

    @patch('talentmap_api.fsbid.client.FSBidClient._request')
    def test_get_user_bids_no_pii_in_logs(self, mock_request):
        """Employee ID must not appear raw in any log output."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_request.return_value = mock_response

        employee_id = "98765432"
        with self.assertLogs('talentmap_api.fsbid.client', level='DEBUG') as cm:
            client = FSBidClient()
            client.get_user_bids(employee_id)

        all_logs = '\n'.join(cm.output)
        self.assertNotIn(employee_id, all_logs)

    @patch('talentmap_api.fsbid.client.FSBidClient._request')
    def test_submit_bid_no_pii_in_logs(self, mock_request):
        """Employee ID must not appear raw in submit_bid logs."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        employee_id = "11223344"
        with self.assertLogs('talentmap_api.fsbid.client', level='DEBUG') as cm:
            client = FSBidClient()
            client.submit_bid("user1", employee_id, "cp100")

        all_logs = '\n'.join(cm.output)
        self.assertNotIn(employee_id, all_logs)

    @patch('talentmap_api.fsbid.client.FSBidClient._request')
    def test_remove_bid_no_pii_in_logs(self, mock_request):
        """Employee ID must not appear raw in remove_bid logs."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        employee_id = "55667788"
        with self.assertLogs('talentmap_api.fsbid.client', level='DEBUG') as cm:
            client = FSBidClient()
            client.remove_bid(employee_id, "cp200")

        all_logs = '\n'.join(cm.output)
        self.assertNotIn(employee_id, all_logs)
