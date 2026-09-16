"""Shared data shapes returned by tool modules.

Keeping these separate from the LangGraph state schema (app/graph/state.py)
means tool modules stay importable/testable without pulling in LangGraph.
"""

from pydantic import BaseModel


class TimeSlot(BaseModel):
    start: str  # ISO 8601, e.g. "2026-09-22T14:00:00-04:00"
    end: str


class BookingResult(BaseModel):
    booking_uid: str
    start: str
    end: str
    status: str  # "confirmed" | "cancelled" | "rescheduled"


class ContactResult(BaseModel):
    contact_id: str
    created: bool  # True if newly created, False if an existing contact was updated


class SmsResult(BaseModel):
    message_sid: str
    status: str


class FaqAnswer(BaseModel):
    answer: str
    source_question: str
    score: float
