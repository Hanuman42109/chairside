from datetime import date

import pytest

from app.config import get_settings
from app.tools import calcom, hubspot, twilio_sms
from app.tools.schemas import BookingResult, ContactResult, SmsResult, TimeSlot


@pytest.fixture(autouse=True)
def _force_mock_mode(monkeypatch):
    # These tests assert the mock path specifically -- don't depend on
    # whatever TOOLS_MOCK_MODE happens to be set to in the developer's .env.
    monkeypatch.setenv("TOOLS_MOCK_MODE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_check_availability_returns_fake_slots_without_network():
    slots = await calcom.check_availability(date(2026, 9, 22))
    assert slots
    assert all(isinstance(s, TimeSlot) for s in slots)


async def test_book_slot_returns_fake_booking_without_network():
    result = await calcom.book_slot(
        slot_start="2026-09-22T09:00:00-04:00",
        attendee_name="Jane Doe",
        attendee_email="jane@example.com",
        attendee_phone="+15551234567",
    )
    assert isinstance(result, BookingResult)
    assert result.status == "confirmed"


async def test_reschedule_booking_returns_fake_result_without_network():
    result = await calcom.reschedule_booking("cal-abc123", "2026-09-23T09:00:00-04:00")
    assert isinstance(result, BookingResult)
    assert result.status == "rescheduled"


async def test_upsert_contact_returns_fake_contact_without_network():
    result = await hubspot.upsert_contact(phone="+15551234567", first_name="Jane")
    assert isinstance(result, ContactResult)


async def test_send_sms_returns_fake_result_without_network():
    result = await twilio_sms.send_sms(to="+15551234567", body="hi")
    assert isinstance(result, SmsResult)
    assert result.status == "delivered"
