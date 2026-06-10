"""
Pydantic models for FSBid API responses.

These models provide typed validation for all data received from the
external FSBid API, ensuring data integrity at the integration boundary.
"""
from pydantic import BaseModel
from typing import List, Optional


class FSBidCycle(BaseModel):
    description: str = ""
    status: str = ""


class FSBidEmployee(BaseModel):
    perdet_seq_num: str


class FSBidCyclePosition(BaseModel):
    cp_id: int
    status: str = ""
    pos_seq_num: str = ""
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


class FSBidProjectedVacancy(BaseModel):
    pos_id: str
    grade: str
    skill: str
    bureau: str
    organization: str
    tour_of_duty: str
    language1: str = ""
    reading_proficiency_1: str = ""
    spoken_proficiency_1: str = ""
    language_representation_1: str = ""
    differential_rate: str = ""
    danger_pay: str = ""
    incumbent: str = ""
    ted: str
    position_number: str
    createDate: str
    title: str
    bsn_descr_text: str


class FSBidPagination(BaseModel):
    count: int
    limit: int = 25


class FSBidProjectedVacanciesResponse(BaseModel):
    positions: List[FSBidProjectedVacancy]
    pagination: FSBidPagination


class FSBidBidSeason(BaseModel):
    bsn_id: str
    bsn_descr_text: str
    bsn_start_date: str
    bsn_end_date: str
    bsn_panel_cutoff_date: str


class FSBidBidOnPositionRequest(BaseModel):
    perdet_seq_num: str
    cp_id: str
    userId: str
