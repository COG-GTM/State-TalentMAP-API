"""Pydantic models for FSBid API responses.

Each model maps to a distinct FSBid endpoint response structure.
Models are used for ingress validation; `.dict()` produces the same
dict shape the existing transformation functions expect.
"""
from pydantic import BaseModel
from typing import List, Optional


# ---------------------------------------------------------------------------
# /bids/ endpoint
# ---------------------------------------------------------------------------

class FSBidCycle(BaseModel):
    description: str = ''
    status: str = ''


class FSBidEmployee(BaseModel):
    perdet_seq_num: str


class FSBidCyclePosition(BaseModel):
    cp_id: int
    status: str = ''
    pos_seq_num: str = ''
    totalBidders: int = 0
    atGradeBidders: int = 0
    inConeBidders: int = 0
    inBothBidders: int = 0


class FSBidBidResponse(BaseModel):
    submittedDate: str
    statusCode: str
    handshakeCode: str
    cycle: FSBidCycle
    employee: FSBidEmployee
    cyclePosition: FSBidCyclePosition


# ---------------------------------------------------------------------------
# /projectedVacancies endpoint
# ---------------------------------------------------------------------------

class FSBidProjectedVacancy(BaseModel):
    pos_id: str
    grade: str
    skill: str
    bureau: str
    organization: str
    tour_of_duty: str
    language1: str
    reading_proficiency_1: str
    spoken_proficiency_1: str
    language_representation_1: str
    differential_rate: str
    danger_pay: str
    incumbent: str
    ted: str
    position_number: str
    createDate: str
    title: str
    bsn_descr_text: str


class FSBidPagination(BaseModel):
    count: int
    limit: Optional[int] = None


class FSBidProjectedVacanciesResponse(BaseModel):
    positions: List[FSBidProjectedVacancy]
    pagination: FSBidPagination


# ---------------------------------------------------------------------------
# /bidSeasons endpoint
# ---------------------------------------------------------------------------

class FSBidBidSeason(BaseModel):
    bsn_id: str
    bsn_descr_text: str
    bsn_start_date: str
    bsn_end_date: str
    bsn_panel_cutoff_date: str
