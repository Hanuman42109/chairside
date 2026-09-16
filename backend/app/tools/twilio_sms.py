"""Twilio integration: SMS booking confirmations.

Docs: https://www.twilio.com/docs/sms/send-messages
Uses the official `twilio` SDK. Twilio's SDK is synchronous, so calls are
offloaded to a thread via `asyncio.to_thread` to avoid blocking the FastAPI
event loop.
"""

import asyncio

from twilio.rest import Client

from app.config import get_settings
from app.tools.schemas import SmsResult


class TwilioError(RuntimeError):
    """Raised when Twilio rejects the send request."""


def _client() -> Client:
    settings = get_settings()
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def _send_sync(to: str, body: str) -> SmsResult:
    settings = get_settings()
    try:
        message = _client().messages.create(to=to, from_=settings.twilio_from_number, body=body)
    except Exception as exc:  # twilio.base.exceptions.TwilioRestException at runtime
        raise TwilioError(str(exc)) from exc
    return SmsResult(message_sid=message.sid, status=message.status)


async def send_sms(to: str, body: str) -> SmsResult:
    """Send an SMS. `to` must be E.164 (e.g. +15551234567)."""
    return await asyncio.to_thread(_send_sync, to, body)


def build_booking_confirmation_text(
    patient_first_name: str,
    appointment_start_local: str,
    office_name: str,
) -> str:
    """Compose the confirmation SMS body. Kept separate from `send_sms` so the
    copy can be unit-tested without touching the network."""
    return (
        f"Hi {patient_first_name}, this confirms your appointment at {office_name} "
        f"on {appointment_start_local}. Reply to this number if you need to reschedule."
    )
