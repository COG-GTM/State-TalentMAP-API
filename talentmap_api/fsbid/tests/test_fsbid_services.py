import pytest
from datetime import datetime
from django.http import QueryDict

import talentmap_api.fsbid.services as services
from talentmap_api.bidding.models import Bid


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

BID_DATA = {
    "submittedDate": "2019/01/01",
    "statusCode": "A",
    "handshakeCode": "N",
    "cycle": {"description": "Summer 2019", "status": "A"},
    "employee": {"perdet_seq_num": "42"},
    "cyclePosition": {
        "cp_id": 7,
        "status": "A",
        "pos_seq_num": "100",
        "totalBidders": 5,
        "atGradeBidders": 3,
        "inConeBidders": 2,
        "inBothBidders": 1,
    },
}

PV_DATA = {
    "pos_id": 10,
    "grade": "05",
    "skill": "CONSULAR",
    "bureau": "EUR",
    "organization": "Embassy Paris",
    "tour_of_duty": "2YR",
    "language1": "French",
    "reading_proficiency_1": "3",
    "spoken_proficiency_1": "3",
    "language_representation_1": "FR",
    "differential_rate": 10,
    "danger_pay": 0,
    "incumbent": "Smith, John",
    "ted": "06/2020",
    "position_number": "D0144910",
    "createDate": "2019-03-15",
    "title": "SPECIAL AGENT",
    "bsn_descr_text": "Summer 2019",
}

BID_SEASON_DATA = {
    "bsn_id": 99,
    "bsn_descr_text": "Winter 2020",
    "bsn_start_date": "2020/01/15",
    "bsn_end_date": "2020/06/30",
    "bsn_panel_cutoff_date": "2020/05/15",
}


# ---------------------------------------------------------------------------
# get_bid_status
# ---------------------------------------------------------------------------

class TestGetBidStatus:

    def test_handshake_accepted_takes_priority(self):
        """handshakeCode 'A' overrides any statusCode."""
        assert services.get_bid_status("A", "A") == Bid.Status.handshake_accepted
        assert services.get_bid_status("W", "A") == Bid.Status.handshake_accepted
        assert services.get_bid_status("P", "A") == Bid.Status.handshake_accepted

    def test_status_closed(self):
        assert services.get_bid_status("C", "N") == Bid.Status.closed

    def test_status_in_panel(self):
        assert services.get_bid_status("P", "N") == Bid.Status.in_panel

    def test_status_draft(self):
        assert services.get_bid_status("W", "N") == Bid.Status.draft

    def test_status_submitted(self):
        assert services.get_bid_status("A", "N") == Bid.Status.submitted

    def test_unknown_codes_return_none(self):
        assert services.get_bid_status("Z", "Z") is None
        assert services.get_bid_status("X", "N") is None


# ---------------------------------------------------------------------------
# can_delete_bid
# ---------------------------------------------------------------------------

class TestCanDeleteBid:

    def test_draft_is_always_deletable(self):
        assert services.can_delete_bid(Bid.Status.draft, {"status": "A"}) is True
        assert services.can_delete_bid(Bid.Status.draft, {"status": "C"}) is True

    def test_submitted_active_cycle_is_deletable(self):
        assert services.can_delete_bid(Bid.Status.submitted, {"status": "A"}) is True

    def test_submitted_inactive_cycle_not_deletable(self):
        assert services.can_delete_bid(Bid.Status.submitted, {"status": "C"}) is False

    def test_handshake_accepted_not_deletable(self):
        assert services.can_delete_bid(Bid.Status.handshake_accepted, {"status": "A"}) is False

    def test_in_panel_not_deletable(self):
        assert services.can_delete_bid(Bid.Status.in_panel, {"status": "A"}) is False

    def test_closed_not_deletable(self):
        assert services.can_delete_bid(Bid.Status.closed, {"status": "A"}) is False


# ---------------------------------------------------------------------------
# fsbid_bid_to_talentmap_bid
# ---------------------------------------------------------------------------

class TestFsbidBidToTalentmapBid:

    def test_basic_field_mapping(self):
        result = services.fsbid_bid_to_talentmap_bid(BID_DATA)

        assert result["bidcycle"] == "Summer 2019"
        assert result["emp_id"] == "42"
        assert result["status"] == Bid.Status.submitted
        assert result["submitted_date"] == datetime(2019, 1, 1)
        assert result["create_date"] == datetime(2019, 1, 1)
        assert result["is_priority"] is False
        assert result["panel_reschedule_count"] == 0
        assert result["waivers"] == []

    def test_position_mapping(self):
        result = services.fsbid_bid_to_talentmap_bid(BID_DATA)
        pos = result["position"]

        assert pos["id"] == "100"
        assert pos["position_number"] == "100"
        assert pos["status"] == "A"
        assert pos["create_date"] == "2019/01/01"

    def test_bid_statistics(self):
        result = services.fsbid_bid_to_talentmap_bid(BID_DATA)
        stats = result["bid_statistics"][0]

        assert stats["bidcycle"] == "Summer 2019"
        assert stats["total_bids"] == 5
        assert stats["in_grade"] == 3
        assert stats["at_skill"] == 2
        assert stats["in_grade_at_skill"] == 1
        assert stats["has_handshake_offered"] is False
        assert stats["has_handshake_accepted"] is False

    def test_can_delete_for_submitted_active(self):
        """Submitted bid in an active cycle should be deletable."""
        result = services.fsbid_bid_to_talentmap_bid(BID_DATA)
        assert result["can_delete"] is True

    def test_can_delete_for_draft(self):
        data = _bid_data_with(statusCode="W")
        result = services.fsbid_bid_to_talentmap_bid(data)
        assert result["can_delete"] is True

    def test_handshake_status(self):
        data = _bid_data_with(handshakeCode="A")
        result = services.fsbid_bid_to_talentmap_bid(data)
        assert result["status"] == Bid.Status.handshake_accepted
        assert result["can_delete"] is False

    def test_handshake_offered_flag(self):
        """cyclePosition status 'HS' sets handshake flags."""
        data = _bid_data_with()
        data["cyclePosition"]["status"] = "HS"
        result = services.fsbid_bid_to_talentmap_bid(data)
        assert result["bid_statistics"][0]["has_handshake_offered"] is True
        assert result["bid_statistics"][0]["has_handshake_accepted"] is True


# ---------------------------------------------------------------------------
# get_pagination
# ---------------------------------------------------------------------------

class TestGetPagination:

    def test_basic_pagination(self):
        query = QueryDict(mutable=True)
        query["page"] = "2"
        query["limit"] = "10"
        result = services.get_pagination(query, 50, "/api/v1/test/", "http://localhost")

        assert result["count"] == 50
        assert result["next"] is not None
        assert "page=3" in result["next"]
        assert result["previous"] is not None
        assert "page=1" in result["previous"]

    def test_first_page_no_previous(self):
        query = QueryDict(mutable=True)
        query["page"] = "1"
        query["limit"] = "10"
        result = services.get_pagination(query, 50, "/api/v1/test/", "http://localhost")

        assert result["previous"] is None
        assert result["next"] is not None

    def test_last_page_no_next(self):
        query = QueryDict(mutable=True)
        query["page"] = "5"
        query["limit"] = "10"
        result = services.get_pagination(query, 50, "/api/v1/test/", "http://localhost")

        assert result["next"] is None
        assert result["previous"] is not None

    def test_no_host_returns_no_urls(self):
        query = QueryDict(mutable=True)
        query["page"] = "2"
        query["limit"] = "10"
        result = services.get_pagination(query, 50, "/api/v1/test/")

        assert result["count"] == 50
        assert result["next"] is None
        assert result["previous"] is None

    def test_defaults_page_zero_limit_25(self):
        query = QueryDict(mutable=True)
        result = services.get_pagination(query, 100, "/api/v1/test/", "http://localhost")

        assert result["count"] == 100
        # page=0: no previous, has next because 0*25=0 < 100
        assert result["previous"] is None
        assert result["next"] is not None

    def test_url_missing_query_separator(self):
        """Documents pre-existing bug: URLs lack '?' between path and query string.

        get_pagination builds ``{host}{base_url}{query.urlencode()}`` which
        produces e.g. ``http://localhost/api/v1/test/page=3&limit=10`` instead
        of ``http://localhost/api/v1/test/?page=3&limit=10``.
        """
        query = QueryDict(mutable=True)
        query["page"] = "2"
        query["limit"] = "10"
        result = services.get_pagination(query, 50, "/api/v1/test/", "http://localhost")

        # Current (buggy) behaviour: no '?' before query params
        assert "test/page=" in result["next"]
        assert "test/?" not in result["next"]

    def test_page_zero_and_one_both_lack_previous(self):
        """Documents pre-existing off-by-one: page>1 gate means both page 0
        and page 1 produce no previous URL."""
        q0 = QueryDict(mutable=True)
        q0["page"] = "0"
        q1 = QueryDict(mutable=True)
        q1["page"] = "1"

        r0 = services.get_pagination(q0, 100, "/api/v1/test/", "http://localhost")
        r1 = services.get_pagination(q1, 100, "/api/v1/test/", "http://localhost")

        assert r0["previous"] is None
        assert r1["previous"] is None


# ---------------------------------------------------------------------------
# convert_pv_query
# ---------------------------------------------------------------------------

class TestConvertPvQuery:

    def test_maps_known_params(self):
        query = {
            "is_available_in_bidseason": "123",
            "bureau__code__in": "EUR",
            "grade__code__in": "05",
            "skill__code__in": "CONSULAR",
            "limit": "25",
            "page": "1",
        }
        encoded = services.convert_pv_query(query)

        assert "bsn_id=123" in encoded
        assert "bureauCode=EUR" in encoded
        assert "gradeCode=05" in encoded
        assert "skillCode=CONSULAR" in encoded
        assert "limit=25" in encoded
        assert "page=1" in encoded

    def test_excludes_none_values(self):
        query = {"is_available_in_bidseason": "1"}
        encoded = services.convert_pv_query(query)

        assert "bsn_id=1" in encoded
        assert "bureauCode" not in encoded
        assert "dangerPay" not in encoded

    def test_all_optional_params(self):
        query = {
            "post__danger_pay__in": "25",
            "language_codes": "FR",
            "post__differential_rate__in": "15",
            "post__tour_of_duty__code__in": "2YR",
            "post__in": "ORG1",
            "position_number__in": "D0144910",
        }
        encoded = services.convert_pv_query(query)

        assert "dangerPay=25" in encoded
        assert "languageCode=FR" in encoded
        assert "postDifferential=15" in encoded
        assert "tourOfDutyCode=2YR" in encoded
        assert "organizationCode=ORG1" in encoded
        assert "positionNumber=D0144910" in encoded

    def test_empty_query(self):
        assert services.convert_pv_query({}) == ""


# ---------------------------------------------------------------------------
# fsbid_pv_to_talentmap_pv
# ---------------------------------------------------------------------------

class TestFsbidPvToTalentmapPv:

    def test_basic_fields(self):
        result = services.fsbid_pv_to_talentmap_pv(PV_DATA)

        assert result["id"] == 10
        assert result["grade"] == "05"
        assert result["skill"] == "CONSULAR"
        assert result["bureau"] == "EUR"
        assert result["organization"] == "Embassy Paris"
        assert result["tour_of_duty"] == "2YR"
        assert result["position_number"] == "D0144910"
        assert result["title"] == "SPECIAL AGENT"

    def test_language_mapping(self):
        result = services.fsbid_pv_to_talentmap_pv(PV_DATA)
        lang = result["languages"][0]

        assert lang["language"] == "French"
        assert lang["reading_proficiency"] == "3"
        assert lang["spoken_proficiency"] == "3"
        assert lang["representation"] == "FR"

    def test_post_mapping(self):
        result = services.fsbid_pv_to_talentmap_pv(PV_DATA)
        post = result["post"]

        assert post["tour_of_duty"] == "2YR"
        assert post["differential_rate"] == 10
        assert post["danger_pay"] == 0

    def test_current_assignment(self):
        result = services.fsbid_pv_to_talentmap_pv(PV_DATA)
        ca = result["current_assignment"]

        assert ca["user"] == "Smith, John"
        assert ca["estimated_end_date"] == datetime(2020, 6, 1)

    def test_posted_date(self):
        result = services.fsbid_pv_to_talentmap_pv(PV_DATA)
        assert result["posted_date"] == datetime(2019, 3, 15)

    def test_bid_cycle_statuses(self):
        result = services.fsbid_pv_to_talentmap_pv(PV_DATA)
        bcs = result["bid_cycle_statuses"][0]

        assert bcs["id"] == 10
        assert bcs["bidcycle"] == "Summer 2019"
        assert bcs["status_code"] == "OP"

    def test_bid_statistics_defaults(self):
        result = services.fsbid_pv_to_talentmap_pv(PV_DATA)
        bs = result["bid_statistics"][0]

        assert bs["total_bids"] == 0
        assert bs["has_handshake_offered"] is False

    def test_availability(self):
        result = services.fsbid_pv_to_talentmap_pv(PV_DATA)
        assert result["availability"]["availability"] is True
        assert result["availability"]["reason"] == ""


# ---------------------------------------------------------------------------
# fsbid_bid_season_to_talentmap_bid_season
# ---------------------------------------------------------------------------

class TestFsbidBidSeasonToTalentmapBidSeason:

    def test_basic_fields(self):
        result = services.fsbid_bid_season_to_talentmap_bid_season(BID_SEASON_DATA)

        assert result["id"] == 99
        assert result["description"] == "Winter 2020"

    def test_date_parsing(self):
        result = services.fsbid_bid_season_to_talentmap_bid_season(BID_SEASON_DATA)

        assert result["start_date"] == datetime(2020, 1, 15)
        assert result["end_date"] == datetime(2020, 6, 30)
        assert result["panel_cut_off_date"] == datetime(2020, 5, 15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bid_data_with(**overrides):
    """Return a copy of BID_DATA with top-level overrides applied."""
    import copy
    data = copy.deepcopy(BID_DATA)
    data.update(overrides)
    return data
