"""Cal.com integration: availability lookup + booking.

Docs: https://cal.com/docs/api-reference/v2/introduction
All calls are async httpx requests against CALCOM_API_BASE_URL. No API key
is required to import/test this module -- calls will raise at request time
if CALCOM_API_KEY is unset, which is what we want during scaffolding.
"""

from datetime import date as date_type

import httpx

from app.config import get_settings
from app.tools.schemas import BookingResult, TimeSlot


class CalComError(RuntimeError):
    """Raised when Cal.com returns a non-2xx response or unexpected payload."""


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.calcom_api_key}",
        "Content-Type": "application/json",
        "cal-api-version": "2024-08-13",
    }


async def check_availability(
    on_date: date_type,
    event_type_id: str | None = None,
    timezone: str | None = None,
) -> list[TimeSlot]:
    """Return open slots for `on_date`.

    Args:
        on_date: the calendar day to check.
        event_type_id: Cal.com event type id; defaults to settings.calcom_event_type_id.
        timezone: IANA tz name; defaults to settings.office_timezone.

    Returns:
        List of TimeSlot, empty if nothing is open that day.

    TODO: once real credentials are wired up, confirm the exact `/slots`
    response shape against a live Cal.com account -- field names have shifted
    between v1 and v2 of their API in the past.
    """
    settings = get_settings()
    event_type_id = event_type_id or settings.calcom_event_type_id
    timezone = timezone or settings.office_timezone

    async with httpx.AsyncClient(base_url=settings.calcom_api_base_url, timeout=10.0) as client:
        response = await client.get(
            "/slots",
            headers=_headers(),
            params={
                "eventTypeId": event_type_id,
                "startTime": f"{on_date.isoformat()}T00:00:00",
                "endTime": f"{on_date.isoformat()}T23:59:59",
                "timeZone": timezone,
            },
        )
    if response.status_code != 200:
        raise CalComError(f"check_availability failed: {response.status_code} {response.text}")

    payload = response.json()
    slots_by_day = payload.get("data", {}).get("slots", {})
    day_slots = slots_by_day.get(on_date.isoformat(), [])
    return [TimeSlot(start=s["time"], end=s.get("end", s["time"])) for s in day_slots]


async def book_slot(
    slot_start: str,
    attendee_name: str,
    attendee_email: str,
    attendee_phone: str,
    event_type_id: str | None = None,
    notes: str | None = None,
) -> BookingResult:
    """Book `slot_start` (ISO 8601) for the given attendee.

    Returns a BookingResult with the Cal.com booking UID, which must be
    stored (e.g. on the LangGraph state / `sessions` row) so it can be used
    later for reschedule/cancel.
    """
    settings = get_settings()
    event_type_id = event_type_id or settings.calcom_event_type_id

    async with httpx.AsyncClient(base_url=settings.calcom_api_base_url, timeout=10.0) as client:
        response = await client.post(
            "/bookings",
            headers=_headers(),
            json={
                "eventTypeId": event_type_id,
                "start": slot_start,
                "attendee": {
                    "name": attendee_name,
                    "email": attendee_email,
                    "phoneNumber": attendee_phone,
                    "timeZone": settings.office_timezone,
                },
                "metadata": {"notes": notes} if notes else {},
            },
        )
    if response.status_code not in (200, 201):
        raise CalComError(f"book_slot failed: {response.status_code} {response.text}")

    booking = response.json().get("data", {})
    return BookingResult(
        booking_uid=booking["uid"],
        start=booking["start"],
        end=booking["end"],
        status="confirmed",
    )


async def reschedule_booking(booking_uid: str, new_slot_start: str) -> BookingResult:
    """Move an existing booking to a new start time."""
    settings = get_settings()

    async with httpx.AsyncClient(base_url=settings.calcom_api_base_url, timeout=10.0) as client:
        response = await client.post(
            f"/bookings/{booking_uid}/reschedule",
            headers=_headers(),
            json={"start": new_slot_start},
        )
    if response.status_code not in (200, 201):
        raise CalComError(f"reschedule_booking failed: {response.status_code} {response.text}")

    booking = response.json().get("data", {})
    return BookingResult(
        booking_uid=booking.get("uid", booking_uid),
        start=booking["start"],
        end=booking["end"],
        status="rescheduled",
    )


async def cancel_booking(booking_uid: str, reason: str | None = None) -> BookingResult:
    """Cancel an existing booking (used for the escalation/abandon path)."""
    settings = get_settings()

    async with httpx.AsyncClient(base_url=settings.calcom_api_base_url, timeout=10.0) as client:
        response = await client.post(
            f"/bookings/{booking_uid}/cancel",
            headers=_headers(),
            json={"reason": reason or "Cancelled by Chairside voice agent"},
        )
    if response.status_code not in (200, 201):
        raise CalComError(f"cancel_booking failed: {response.status_code} {response.text}")

    return BookingResult(booking_uid=booking_uid, start="", end="", status="cancelled")
