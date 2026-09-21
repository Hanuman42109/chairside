"""Retell call-lifecycle webhook: call_started / call_ended / call_analyzed.

This is separate from the per-utterance Custom LLM websocket
(app/routes/llm_websocket.py) -- these are one-shot HTTP events Retell fires
for logging/analytics, not part of the live conversation loop.

Signature verification uses Retell's own `retell-sdk` (verified against
https://docs.retellai.com/features/secure-webhook and the RetellAI/
retell-python-sdk source): webhooks are signed HMAC-SHA256 over the raw body
concatenated with a timestamp, using the Retell **API key** as the secret
(not a separate webhook secret -- Retell doesn't issue one; only an API key
with the "webhook" badge in the dashboard can verify), with a ~5 minute replay
window built into the SDK's `verify()`. Hand-rolling this HMAC scheme would be
easy to get subtly wrong (timestamp concatenation, replay window), so we defer
to the SDK rather than reimplementing it.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from retell.lib.webhook_auth import verify as retell_verify

from app.config import get_settings
from app.db import repository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook/retell", tags=["retell-webhook"])


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    settings = get_settings()
    if not settings.retell_api_key:
        # No API key configured yet (local dev) -- accept everything.
        return True
    if not signature_header:
        return False
    return retell_verify(raw_body.decode("utf-8"), settings.retell_api_key, signature_header)


@router.post("/events")
async def retell_call_events(
    request: Request, x_retell_signature: str | None = Header(default=None)
) -> dict:
    raw_body = await request.body()
    if not verify_signature(raw_body, x_retell_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload: dict[str, Any] = await request.json()
    event = payload.get("event")
    call = payload.get("call", {})
    retell_call_id = call.get("call_id")
    caller_phone = call.get("from_number", "")

    if not retell_call_id:
        raise HTTPException(status_code=400, detail="Missing call.call_id")

    logger.info("retell event=%s call_id=%s", event, retell_call_id)

    if event == "call_started":
        call_id = await repository.create_call(retell_call_id, caller_phone)
        return {"received": True, "call_id": call_id}

    if event == "call_ended":
        call_id = await repository.create_call(retell_call_id, caller_phone)
        await repository.update_call(
            call_id,
            status="completed",
            ended_at=datetime.now(UTC),
            recording_url=call.get("recording_url"),
            transcript=call.get("transcript_object", []),
        )
        return {"received": True, "call_id": call_id}

    if event == "call_analyzed":
        # TODO: kick off eval scoring here (app/eval/run_eval.py logic) once a
        # real transcript + expected-outcome pairing strategy is decided --
        # e.g. compare Retell's call_analysis against the session's final state.
        return {"received": True}

    logger.warning("Unhandled Retell event type: %s", event)
    return {"received": True}
