import pytest
from pydantic import ValidationError

from talentmap_api.fsbid.schemas import (
    FSBidBidResponse,
    FSBidBidSeason,
    FSBidCycle,
    FSBidCyclePosition,
    FSBidEmployee,
    FSBidPagination,
    FSBidProjectedVacancy,
    FSBidProjectedVacanciesResponse,
)


# ---------------------------------------------------------------------------
# Bid response models
# ---------------------------------------------------------------------------

class TestFSBidBidResponse:

    VALID_BID = {
        "submittedDate": "2019/01/01",
        "statusCode": "A",
        "handshakeCode": "N",
        "cycle": {"description": "Fall 2019", "status": "A"},
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

    def test_valid_bid_parses(self):
        bid = FSBidBidResponse(**self.VALID_BID)
        assert bid.statusCode == "A"
        assert bid.cyclePosition.cp_id == 1
        assert bid.employee.perdet_seq_num == "12345"

    def test_dict_roundtrip_preserves_structure(self):
        bid = FSBidBidResponse(**self.VALID_BID)
        d = bid.dict()
        assert d['cyclePosition']['cp_id'] == 1
        assert d['cycle']['description'] == "Fall 2019"

    def test_missing_required_field_raises(self):
        incomplete = dict(self.VALID_BID)
        del incomplete['statusCode']
        with pytest.raises(ValidationError):
            FSBidBidResponse(**incomplete)

    def test_defaults_for_optional_nested_fields(self):
        minimal_cycle = {"description": "X"}
        bid_data = dict(self.VALID_BID, cycle=minimal_cycle)
        bid = FSBidBidResponse(**bid_data)
        assert bid.cycle.status == ''

    def test_cycle_position_defaults(self):
        minimal_cp = {"cp_id": 42}
        bid_data = dict(self.VALID_BID, cyclePosition=minimal_cp)
        bid = FSBidBidResponse(**bid_data)
        assert bid.cyclePosition.totalBidders == 0
        assert bid.cyclePosition.pos_seq_num == ''


# ---------------------------------------------------------------------------
# Projected vacancy models
# ---------------------------------------------------------------------------

class TestFSBidProjectedVacanciesResponse:

    VALID_PV = {
        "pos_id": "1",
        "grade": "05",
        "skill": "2010",
        "bureau": "NEA",
        "organization": "ORG",
        "tour_of_duty": "2 YRS",
        "language1": "AR",
        "reading_proficiency_1": "3",
        "spoken_proficiency_1": "3",
        "language_representation_1": "Arabic",
        "differential_rate": "15",
        "danger_pay": "N",
        "incumbent": "Smith, John",
        "ted": "06/2025",
        "position_number": "S12345",
        "createDate": "2024-01-15",
        "title": "Political Officer",
        "bsn_descr_text": "Fall 2024",
    }

    def test_valid_response_parses(self):
        resp = FSBidProjectedVacanciesResponse(
            positions=[self.VALID_PV],
            pagination={"count": 1},
        )
        assert len(resp.positions) == 1
        assert resp.pagination.count == 1

    def test_dict_roundtrip(self):
        resp = FSBidProjectedVacanciesResponse(
            positions=[self.VALID_PV],
            pagination={"count": 1},
        )
        d = resp.dict()
        assert d['positions'][0]['bureau'] == 'NEA'
        assert d['pagination']['count'] == 1

    def test_empty_positions_allowed(self):
        resp = FSBidProjectedVacanciesResponse(
            positions=[],
            pagination={"count": 0},
        )
        assert len(resp.positions) == 0

    def test_missing_position_field_raises(self):
        bad_pv = dict(self.VALID_PV)
        del bad_pv['pos_id']
        with pytest.raises(ValidationError):
            FSBidProjectedVacanciesResponse(
                positions=[bad_pv],
                pagination={"count": 1},
            )


# ---------------------------------------------------------------------------
# Bid season model
# ---------------------------------------------------------------------------

class TestFSBidBidSeason:

    VALID_BS = {
        "bsn_id": "42",
        "bsn_descr_text": "Spring 2024",
        "bsn_start_date": "2024/01/01",
        "bsn_end_date": "2024/03/31",
        "bsn_panel_cutoff_date": "2024/04/15",
    }

    def test_valid_season_parses(self):
        bs = FSBidBidSeason(**self.VALID_BS)
        assert bs.bsn_id == "42"

    def test_dict_roundtrip(self):
        bs = FSBidBidSeason(**self.VALID_BS)
        d = bs.dict()
        assert d == self.VALID_BS

    def test_missing_required_field_raises(self):
        bad = dict(self.VALID_BS)
        del bad['bsn_start_date']
        with pytest.raises(ValidationError):
            FSBidBidSeason(**bad)
