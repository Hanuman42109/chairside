"""Deterministic fake data for TOOLS_MOCK_MODE=true (local demo without real
Cal.com/HubSpot/Twilio accounts). Each function's shape mirrors the real
provider call it stands in for -- see app/tools/schemas.py."""

import uuid
from datetime import date as date_type
from datetime import datetime, time

from app.tools.schemas import BookingResult, ContactResult, SmsResult, TimeSlot


def fake_slots(on_date: date_type) -> list[TimeSlot]:
    tz = "-04:00"
    return [
        TimeSlot(
            start=datetime.combine(on_date, time(hour)).isoformat() + tz,
            end=datetime.combine(on_date, time(hour + 1)).isoformat() + tz,
        )
        for hour in (9, 11, 14)
    ]


def fake_booking(slot_start: str, status: str = "confirmed") -> BookingResult:
    return BookingResult(
        booking_uid=f"mock-{uuid.uuid4().hex[:10]}",
        start=slot_start,
        end=slot_start,
        status=status,
    )


def fake_contact(created: bool = True) -> ContactResult:
    return ContactResult(contact_id=f"mock-contact-{uuid.uuid4().hex[:8]}", created=created)


def fake_sms() -> SmsResult:
    return SmsResult(message_sid=f"mock-sms-{uuid.uuid4().hex[:10]}", status="delivered")
