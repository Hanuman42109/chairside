"""Retell call-lifecycle webhook: call_started / call_ended / call_analyzed.

This is separate from the per-utterance Custom LLM websocket
(app/routes/llm_websocket.py) -- these are one-shot HTTP events Retell fires
for logging/analytics, not part of the live conversation loop.

TODO: confirm the exact signature header/algorithm against current Retell
docs before going live -- `verify_signature` below implements the common
HMAC-SHA256-over-raw-body pattern, but has not been checked against a real
Retell payload yet.
"""

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_settings
from app.db import repository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook/retell", tags=["retell-webhook"])


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    settings = get_settings()
    if not settings.retell_webhook_secret:
        # No secret configured yet (local dev) -- accept everything.
        return True
    if not signature_header:
        return False
    expected = hmac.new(
        settings.retell_webhook_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


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
